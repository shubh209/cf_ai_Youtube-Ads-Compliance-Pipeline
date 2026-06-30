import json
import logging
import os
import re
from typing import Any, Dict

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from backend.src.graph.state import VideoAuditState
from backend.src.services.ingestion import HybridIngestionService
from backend.src.services.policy_store import format_chunks_for_prompt, search_policy_chunks
from backend.src.services.video_indexer import YouTubeTranscriptService

logger = logging.getLogger("brand-guardian")
logging.basicConfig(level=logging.INFO)

logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.monitor").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise ValueError(f"Missing required environment variable: {var_name}")
    return value


def index_video_node(state: VideoAuditState) -> Dict[str, Any]:
    video_url = state.get("video_url")
    logger.info("--- [Node: Indexer] Processing: %s ---", video_url)

    try:
        if not video_url:
            raise ValueError("No video_url provided in state.")

        yt_service = YouTubeTranscriptService()
        clean_data = yt_service.extract_data(video_url)
        clean_data["ingestion_source"] = "metadata"
        logger.info("--- [Node: Indexer] Metadata extraction complete ---")
        return clean_data

    except Exception as exc:
        logger.error("Video Indexer Failed: %s", exc)
        return {
            "errors": [str(exc)],
            "final_status": "FAIL",
            "final_report": f"Video indexing failed: {exc}",
            "transcript": "",
            "ocr_text": [],
            "compliance_results": [],
        }


def enrich_content_node(state: VideoAuditState) -> Dict[str, Any]:
    video_url = state.get("video_url", "")
    base_transcript = state.get("transcript", "") or ""
    logger.info("--- [Node: Enrich] Hybrid ingestion for %s ---", video_url)

    if not video_url or not base_transcript:
        return {"ingestion_source": "none"}

    try:
        service = HybridIngestionService()
        enriched = service.enrich(video_url, base_transcript)
        logger.info("--- [Node: Enrich] Source=%s ---", enriched.get("ingestion_source"))
        return enriched
    except Exception as exc:
        logger.warning("Enrichment failed, using metadata only: %s", exc)
        return {"ingestion_source": "metadata"}


def _attach_citations(results: list[dict], chunks: list) -> list[dict]:
    chunk_map = {chunk.chunk_id: chunk for chunk in chunks}
    enriched = []
    for item in results:
        row = dict(item)
        chunk_id = row.get("chunk_id")
        if chunk_id and chunk_id in chunk_map:
            chunk = chunk_map[chunk_id]
            row.setdefault("citation_source", chunk.source)
            row.setdefault("citation_excerpt", chunk.content[:500])
        enriched.append(row)
    return enriched


def audit_content_node(state: VideoAuditState) -> Dict[str, Any]:
    logger.info("--- [Node: Auditor] querying Knowledge Base and LLM ---")

    transcript = state.get("transcript", "")
    if not transcript:
        return {
            "final_status": "FAIL",
            "final_report": "Audit skipped because video processing failed (no content).",
            "compliance_results": [],
        }

    try:
        llm = AzureChatOpenAI(
            azure_deployment=_require_env("AZURE_OPENAI_CHAT_DEPLOYMENT"),
            azure_endpoint=_require_env("AZURE_OPENAI_ENDPOINT"),
            api_key=_require_env("AZURE_OPENAI_API_KEY"),
            openai_api_version=_require_env("AZURE_OPENAI_API_VERSION"),
            temperature=0.0,
        )

        ocr_text = state.get("ocr_text", [])
        query_text = f"{transcript} {' '.join(ocr_text)}".strip()
        chunks = search_policy_chunks(query_text)
        retrieved_rules = format_chunks_for_prompt(chunks)

        metadata = state.get("video_metadata", {})
        video_title = metadata.get("title", "Unknown")

        system_prompt = f"""
You are a Senior Brand Compliance Auditor specializing in YouTube advertising policy.

OFFICIAL REGULATORY RULES (each block includes CHUNK_ID and SOURCE):
{retrieved_rules}

INSTRUCTIONS:
1. Analyze the video transcript, description, and metadata below.
2. Identify ANY violations of YouTube Ad Policies or FTC guidelines.
3. For each violation you MUST set chunk_id to the CHUNK_ID of the rule you relied on.
4. Return strictly valid JSON in the following format:

{{
    "compliance_results": [
        {{
            "category": "Claim Validation",
            "severity": "CRITICAL",
            "description": "Explanation of the violation...",
            "chunk_id": "uuid-from-CHUNK_ID",
            "citation_source": "filename.pdf",
            "citation_excerpt": "quoted rule text...",
            "confidence": "high"
        }}
    ],
    "status": "FAIL",
    "final_report": "Summary of findings..."
}}

Severity levels: CRITICAL, WARNING, INFO.
If no violations are found, set "status" to "PASS" and "compliance_results" to [].
Do not include markdown fences or any text outside the JSON.
""".strip()

        user_message = f"""
VIDEO TITLE: {video_title}
VIDEO METADATA: {metadata}
TRANSCRIPT: {transcript}
ON-SCREEN TEXT: {ocr_text}
INGESTION SOURCE: {state.get("ingestion_source", "unknown")}
""".strip()

        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ])

        content = response.content.strip()
        if "```" in content:
            match = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
            if match:
                content = match.group(1).strip()

        audit_data = json.loads(content)
        results = _attach_citations(audit_data.get("compliance_results", []), chunks)

        return {
            "compliance_results": results,
            "final_status": audit_data.get("status", "FAIL"),
            "final_report": audit_data.get("final_report", "No report generated."),
        }

    except Exception as exc:
        logger.error("System Error in Auditor Node: %s", exc)
        return {
            "errors": [str(exc)],
            "final_status": "FAIL",
            "final_report": f"Auditor node failed: {exc}",
            "compliance_results": [],
        }
