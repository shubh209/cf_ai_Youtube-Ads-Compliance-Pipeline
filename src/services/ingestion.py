import io
import logging
import xml.etree.ElementTree as ET

import requests
import yt_dlp

from src.services.video_indexer import VideoIndexerService, _extract_video_id

logger = logging.getLogger("ingestion")


def _fetch_captions_via_timedtext(video_id: str) -> str | None:
    for lang in ("en", "en-US", "en-GB"):
        url = f"https://www.youtube.com/api/timedtext?v={video_id}&lang={lang}"
        response = requests.get(url, timeout=15)
        if response.status_code != 200 or not response.text.strip():
            continue
        try:
            root = ET.fromstring(response.text)
            lines = [elem.text.strip() for elem in root.iter("text") if elem.text]
            if lines:
                return " ".join(lines)
        except ET.ParseError:
            continue
    return None


def _fetch_captions_via_ytdlp(video_url: str) -> str | None:
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            subs = info.get("automatic_captions") or info.get("subtitles") or {}
            en_tracks = subs.get("en") or subs.get("en-US") or []
            if not en_tracks:
                return None
            track_url = en_tracks[0].get("url")
            if not track_url:
                return None
            response = requests.get(track_url, timeout=20)
            if response.status_code != 200:
                return None
            return response.text[:50000]
    except Exception as exc:
        logger.warning("yt-dlp caption fetch failed: %s", exc)
        return None


def _fetch_vi_transcript(video_url: str) -> tuple[str | None, list[str]]:
    """Azure Video Indexer fallback for speech + on-screen text."""
    vi = VideoIndexerService()
    arm_token = vi.get_access_token()
    vi_token = vi.get_account_token(arm_token)

    upload_url = (
        f"https://api.videoindexer.ai/{vi.location}/Accounts/{vi.account_id}/Videos"
        f"?accessToken={vi_token}&name=audit-video&videoUrl={video_url}"
    )
    response = requests.post(upload_url, timeout=60)
    if response.status_code not in (200, 202):
        raise RuntimeError(f"Video Indexer upload failed: {response.text}")

    video_vi_id = response.json().get("id")
    if not video_vi_id:
        raise RuntimeError("Video Indexer did not return a video id")

    import time

    index_url = (
        f"https://api.videoindexer.ai/{vi.location}/Accounts/{vi.account_id}/Videos/{video_vi_id}/Index"
        f"?accessToken={vi_token}"
    )
    for _ in range(30):
        poll = requests.get(index_url, timeout=30)
        if poll.status_code != 200:
            time.sleep(5)
            continue
        state = poll.json().get("state")
        if state == "Processed":
            insights = poll.json()
            transcript_lines = []
            for item in insights.get("videos", [{}])[0].get("insights", {}).get("transcript", []):
                transcript_lines.append(item.get("text", ""))
            ocr_lines = []
            for item in insights.get("videos", [{}])[0].get("insights", {}).get("ocr", []):
                ocr_lines.append(item.get("text", ""))
            return " ".join(transcript_lines).strip() or None, [t for t in ocr_lines if t]
        if state == "Failed":
            raise RuntimeError("Video Indexer processing failed")
        time.sleep(5)

    raise RuntimeError("Video Indexer processing timed out")


class HybridIngestionService:
    def enrich(self, video_url: str, base_transcript: str) -> dict:
        video_id = _extract_video_id(video_url)
        caption_text = _fetch_captions_via_timedtext(video_id)
        source = "metadata"

        if caption_text:
            source = "captions"
            combined = f"{base_transcript}\n\nSpoken transcript:\n{caption_text}"
            return {"transcript": combined, "ocr_text": [], "ingestion_source": source}

        caption_text = _fetch_captions_via_ytdlp(video_url)
        if caption_text:
            source = "captions_ytdlp"
            combined = f"{base_transcript}\n\nSpoken transcript:\n{caption_text}"
            return {"transcript": combined, "ocr_text": [], "ingestion_source": source}

        if all([
            VideoIndexerService().account_id,
            VideoIndexerService().location,
        ]):
            try:
                vi_transcript, ocr_lines = _fetch_vi_transcript(video_url)
                if vi_transcript or ocr_lines:
                    source = "video_indexer"
                    combined = base_transcript
                    if vi_transcript:
                        combined = f"{combined}\n\nSpoken transcript:\n{vi_transcript}"
                    return {
                        "transcript": combined,
                        "ocr_text": ocr_lines,
                        "ingestion_source": source,
                    }
            except Exception as exc:
                logger.warning("Video Indexer fallback failed: %s", exc)

        return {
            "transcript": base_transcript,
            "ocr_text": [],
            "ingestion_source": source,
        }
