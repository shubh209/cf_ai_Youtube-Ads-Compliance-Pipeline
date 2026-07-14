"""
Video processing helpers: transcription (Azure OpenAI Whisper) and OCR (Azure AI Vision).
ponytail: graceful fallbacks if optional deps not installed or env vars not set.
"""
import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("brand-guardian.worker")


def transcribe(blob_url: str, audit_id: str) -> dict:
    """Download blob and transcribe via Azure OpenAI Whisper. Returns {text, segments}."""
    from azure.storage.blob import BlobClient
    from openai import AzureOpenAI

    client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
    )

    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    try:
        tmp.close()
        # ponytail: download via connection string, not public URL (public access disabled)
        conn_str = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
        container = os.getenv("AZURE_STORAGE_CONTAINER", "uploads")
        # blob_url is like https://account.blob.../container/uploads/uuid.mp4 — extract blob name
        blob_name = "/".join(blob_url.split("/")[4:])  # everything after container
        blob = BlobClient.from_connection_string(conn_str, container, blob_name)
        with open(tmp.name, "wb") as f:
            f.write(blob.download_blob().readall())
        with open(tmp.name, "rb") as f:
            result = client.audio.transcriptions.create(model=os.getenv("AZURE_OPENAI_WHISPER_DEPLOYMENT", "whisper"), file=f)
        return {"text": result.text, "segments": getattr(result, "segments", [])}
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _extract_every_n_seconds(video_path: str, interval: float = 5.0) -> list[float]:
    """Fallback: generate timestamps every `interval` seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True,
    )
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        duration = 0.0
    ts = 0.0
    timestamps = []
    while ts < duration:
        timestamps.append(ts)
        ts += interval
    return timestamps


def extract_ocr(video_path: str) -> list[dict]:
    """
    Extract text from video frames using Azure AI Vision.
    Uses PySceneDetect for scene timestamps; falls back to every-5-seconds if not installed.
    Skips entirely if AZURE_AI_VISION_ENDPOINT / KEY not configured.
    Returns [{"timestamp": float, "texts": [str]}].
    """
    vision_endpoint = os.getenv("AZURE_AI_VISION_ENDPOINT", "")
    vision_key = os.getenv("AZURE_AI_VISION_KEY", "")
    if not vision_endpoint or not vision_key:
        logger.warning("Azure AI Vision not configured — OCR skipped")
        return []

    # Get scene timestamps
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector
        video = open_video(video_path)
        manager = SceneManager()
        manager.add_detector(ContentDetector())
        manager.detect_scenes(video)
        timestamps = [scene[0].get_seconds() for scene in manager.get_scene_list()]
    except Exception:
        # ponytail: scenedetect unavailable or failed → fall back to fixed interval
        timestamps = _extract_every_n_seconds(video_path)

    if not timestamps:
        return []

    try:
        from azure.ai.vision.imageanalysis import ImageAnalysisClient
        from azure.ai.vision.imageanalysis.models import VisualFeatures
        from azure.core.credentials import AzureKeyCredential
        vision_client = ImageAnalysisClient(
            endpoint=vision_endpoint,
            credential=AzureKeyCredential(vision_key),
        )
    except ImportError:
        logger.warning("azure-ai-vision not installed — OCR skipped")
        return []

    results = []
    frame_dir = tempfile.mkdtemp()
    try:
        for t in timestamps:
            frame_path = os.path.join(frame_dir, f"frame_{t:.2f}.jpg")
            subprocess.run(
                ["ffmpeg", "-ss", str(t), "-i", video_path,
                 "-frames:v", "1", "-q:v", "2", frame_path, "-y"],
                capture_output=True,
            )
            if not os.path.exists(frame_path):
                continue
            try:
                with open(frame_path, "rb") as img:
                    analysis = vision_client.analyze(
                        image_data=img.read(),
                        visual_features=[VisualFeatures.READ],
                    )
                texts = [
                    line.text
                    for block in (analysis.read.blocks if analysis.read else [])
                    for line in block.lines
                ]
                if texts:
                    results.append({"timestamp": t, "texts": texts})
            except Exception as exc:
                logger.warning("OCR failed at t=%.2f: %s", t, exc)
            finally:
                Path(frame_path).unlink(missing_ok=True)
    finally:
        Path(frame_dir).rmdir() if not os.listdir(frame_dir) else None

    return results
