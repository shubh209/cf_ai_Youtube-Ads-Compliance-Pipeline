import logging
import os

from backend.src.services.policy_store import RetrievedChunk

logger = logging.getLogger("brand-guardian")

# ponytail: module-level model load (~350MB). Single instance, not thread-safe for
# parallel batches. Upgrade: sentence-transformers server if parallelism needed.
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder
        model_name = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        _model = CrossEncoder(model_name)
    return _model


def rerank(query: str, chunks: list[RetrievedChunk], top_n: int = 5) -> list[RetrievedChunk]:
    """Re-rank chunks by cross-encoder relevance. Returns top_n."""
    if not chunks:
        return chunks
    try:
        model = _get_model()
        pairs = [(query, c.content) for c in chunks]
        scores = model.predict(pairs)
        ranked = sorted(zip(scores, chunks), key=lambda x: -x[0])
        for score, chunk in ranked:
            chunk.score = float(score)
        return [c for _, c in ranked[:top_n]]
    except Exception as exc:
        logger.warning("Reranker failed, returning original order: %s", exc)
        return chunks[:top_n]
