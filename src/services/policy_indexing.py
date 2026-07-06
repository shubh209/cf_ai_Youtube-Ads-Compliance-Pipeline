"""
Policy indexing: fetch live policy pages, chunk, and upload to Azure AI Search.
Falls back to local PDFs if all live fetches fail (offline/dev mode).
"""
import glob
import logging
import os
import uuid
from datetime import datetime, timezone

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from src.db.models import PolicyVersion
from src.services.policy_fetcher import fetch_policy_source
from src.services.policy_sources import POLICY_SOURCES
from src.services.policy_store import get_vector_store

logger = logging.getLogger("brand-guardian")


def _load_fallback_pdfs() -> list[Document]:
    """Load local PDFs as fallback when live fetch fails entirely."""
    from langchain_community.document_loaders import PyPDFLoader
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_folder = os.path.join(current_dir, "..", "..", "data")
    pdf_files = glob.glob(os.path.join(data_folder, "*.pdf"))
    docs = []
    for pdf_path in pdf_files:
        raw = PyPDFLoader(pdf_path).load()
        for doc in raw:
            doc.metadata["platform"] = "youtube"  # legacy PDFs are YouTube policy
            doc.metadata["source"] = os.path.basename(pdf_path)
        docs.extend(raw)
    return docs


def run_policy_index(
    db: Session | None = None,
    platforms: list[str] | None = None,
) -> dict:
    """
    Fetch policy sources, chunk, and upload to Azure AI Search.

    Args:
        db: SQLAlchemy session for recording PolicyVersion. Optional.
        platforms: Optional list to limit re-indexing to specific platforms.
                   If None, indexes all sources.
    """
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    all_splits: list[Document] = []
    failed_sources: list[str] = []

    sources = POLICY_SOURCES
    if platforms:
        sources = [s for s in POLICY_SOURCES if s["platform"] in platforms]

    for source in sources:
        try:
            content = fetch_policy_source(source)
            doc = Document(
                page_content=content,
                metadata={
                    "source": source["name"],
                    "source_id": source["id"],
                    "platform": source["platform"],
                    "url": source["url"],
                },
            )
            splits = splitter.split_documents([doc])
            for split in splits:
                split.metadata["chunk_id"] = str(uuid.uuid4())
            all_splits.extend(splits)
            logger.info("Indexed %s: %d chunks", source["id"], len(splits))
        except Exception as exc:
            logger.error("Failed to index %s: %s", source["id"], exc)
            failed_sources.append(source["id"])

    if not all_splits:
        # ponytail: full fallback to local PDFs when all live fetches fail
        logger.warning("All live fetches failed — falling back to local PDFs")
        fallback_docs = _load_fallback_pdfs()
        if not fallback_docs:
            raise RuntimeError("No policy content available: live fetch failed and no local PDFs found")
        splits = splitter.split_documents(fallback_docs)
        for split in splits:
            split.metadata.setdefault("chunk_id", str(uuid.uuid4()))
        all_splits = splits
        logger.info("Fallback PDF indexing: %d chunks", len(all_splits))

    store = get_vector_store()
    store.add_documents(documents=all_splits)

    version_label = datetime.now(timezone.utc).strftime("v%Y%m%d-%H%M%S")
    result = {
        "version_label": version_label,
        "chunk_count": len(all_splits),
        "policy_version_id": None,
        "failed_sources": failed_sources,
    }

    if db is not None:
        db.query(PolicyVersion).filter(PolicyVersion.is_current.is_(True)).update({"is_current": False})
        policy_version = PolicyVersion(
            version_label=version_label,
            chunk_count=len(all_splits),
            is_current=True,
        )
        db.add(policy_version)
        db.commit()
        db.refresh(policy_version)
        result["policy_version_id"] = str(policy_version.id)

    return result
