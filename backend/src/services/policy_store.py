import os
import uuid
from dataclasses import dataclass

from langchain_openai import AzureOpenAIEmbeddings
from langchain_community.vectorstores import AzureSearch
from sqlalchemy.orm import Session

from backend.src.db.models import PolicyVersion
from backend.src.db.repository import get_current_policy_version


@dataclass
class RetrievedChunk:
    chunk_id: str
    source: str
    content: str
    page: int | None = None


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def get_vector_store() -> AzureSearch:
    embeddings = AzureOpenAIEmbeddings(
        azure_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
        azure_endpoint=_require_env("AZURE_OPENAI_ENDPOINT"),
        api_key=_require_env("AZURE_OPENAI_API_KEY"),
        openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
    )
    return AzureSearch(
        azure_search_endpoint=_require_env("AZURE_SEARCH_ENDPOINT"),
        azure_search_key=_require_env("AZURE_SEARCH_API_KEY"),
        index_name=_require_env("AZURE_SEARCH_INDEX_NAME"),
        embedding_function=embeddings.embed_query,
    )


def rag_top_k() -> int:
    return int(os.getenv("RAG_TOP_K", "8"))


def search_policy_chunks(query_text: str, k: int | None = None) -> list[RetrievedChunk]:
    store = get_vector_store()
    top_k = k or rag_top_k()
    docs = store.similarity_search(query_text, k=top_k)
    chunks: list[RetrievedChunk] = []
    for doc in docs:
        meta = doc.metadata or {}
        chunk_id = str(meta.get("chunk_id") or meta.get("id") or uuid.uuid4())
        chunks.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                source=str(meta.get("source", "unknown")),
                content=doc.page_content,
                page=meta.get("page"),
            )
        )
    return chunks


def format_chunks_for_prompt(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for chunk in chunks:
        parts.append(
            f"[CHUNK_ID: {chunk.chunk_id} | SOURCE: {chunk.source}]\n{chunk.content}"
        )
    return "\n\n".join(parts)


def resolve_current_policy_version(db: Session | None) -> PolicyVersion | None:
    if db is None:
        return None
    return get_current_policy_version(db)
