import logging
import os
import threading

from src.services.policy_store import RetrievedChunk

logger = logging.getLogger("brand-guardian")

_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import CrossEncoder
                model_name = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
                _model = CrossEncoder(model_name)
    return _model


def rerank(query: str, chunks: list[RetrievedChunk], top_n: int = 5) -> list[RetrievedChunk]:
    """Re-rank chunks by cross-encoder relevance. Returns top_n.
    ponytail: falls back to score-sorted truncation if sentence-transformers not installed.
    Ceiling: no semantic re-ranking without the model. Upgrade: install sentence-transformers.
    """
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
        logger.warning("Reranker unavailable (%s) — using vector score order", exc)
        result = sorted(chunks, key=lambda c: -c.score)[:top_n]
        return result
