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
    result = app.scrape_url(url, formats=["markdown"])
    content = result.markdown if hasattr(result, "markdown") else (result.get("markdown") or result.get("content") or "")
    if not content:
        raise ValueError(f"Firecrawl returned empty content for {url}")
    return content


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
