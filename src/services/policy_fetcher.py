"""
Fetch live policy pages via Firecrawl, cache to Azure Blob Storage.
Falls back to last successful blob cache if fetch fails.
"""
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("brand-guardian")


def _blob_client(source_id: str):
    from azure.storage.blob import BlobClient
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    container = os.getenv("POLICY_CACHE_CONTAINER", "policy-cache")
    return BlobClient.from_connection_string(conn_str, container, f"{source_id}.json")


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "policy_name": {"type": "string"},
        "category": {"type": "string", "description": "health_claim|misleading|disclosure|financial|prohibited|restricted|editorial|copyright|general"},
        "platform": {"type": "string"},
        "what_is_prohibited": {"type": "array", "items": {"type": "string"}},
        "what_is_allowed": {"type": "array", "items": {"type": "string"}},
        "enforcement_note": {"type": "string"}
    }
}

_EXTRACT_PROMPT = (
    "Extract the advertising compliance rules from this policy page. "
    "List every specific prohibited item in what_is_prohibited as separate strings. "
    "List permitted items in what_is_allowed. Be specific and exhaustive."
)


def _fetch_via_firecrawl(url: str) -> str:
    api_key = os.getenv("FIRECRAWL_API_KEY", "")
    if not api_key:
        raise ValueError("FIRECRAWL_API_KEY not set")
    try:
        from firecrawl.v1.client import V1FirecrawlApp
        app = V1FirecrawlApp(api_key=api_key)
    except ImportError:
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=api_key)

    # ponytail: extract costs ~30 credits/URL vs 1 for scrape.
    # Ceiling: 35 URLs x 30 = 1,050 credits per reindex.
    # Upgrade: batch_scrape + GPT-4o-mini extraction if credit cost is prohibitive.
    # extract is deprecated in firecrawl-py v4 but still synchronous and functional.
    result = app.extract(urls=[url], schema=EXTRACTION_SCHEMA, prompt=_EXTRACT_PROMPT, timeout=90)
    data = result.data if hasattr(result, "data") else (result.get("data") if isinstance(result, dict) else None)
    if not data or not isinstance(data, dict):
        raise ValueError(f"Firecrawl extract returned no structured data for {url}")
    return json.dumps(data)


def _save_to_blob(source_id: str, url: str, content: str) -> None:
    try:
        client = _blob_client(source_id)
        payload = json.dumps({
            "source_id": source_id,
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "content": content,
        })
        client.upload_blob(payload, overwrite=True)
    except Exception as exc:
        logger.warning("Failed to save policy cache for %s: %s", source_id, exc)


def _load_from_blob(source_id: str) -> str | None:
    try:
        client = _blob_client(source_id)
        data = json.loads(client.download_blob().readall())
        return data.get("content")
    except Exception:
        return None


def fetch_policy_source(source: dict) -> str:
    """
    Fetch policy text for a source entry from POLICY_SOURCES.
    Tries Firecrawl first; falls back to blob cache on failure.
    Raises if both fail.
    """
    source_id = source["id"]
    url = source["url"]

    try:
        content = _fetch_via_firecrawl(url)
        logger.info("Fetched policy source %s (%d chars)", source_id, len(content))
        _save_to_blob(source_id, url, content)
        return content
    except Exception as exc:
        logger.warning("Firecrawl fetch failed for %s: %s — trying blob cache", source_id, exc)

    cached = _load_from_blob(source_id)
    if cached:
        logger.info("Using blob cache for %s", source_id)
        return cached

    raise RuntimeError(f"Failed to fetch policy source {source_id!r}: no live fetch and no cache")
