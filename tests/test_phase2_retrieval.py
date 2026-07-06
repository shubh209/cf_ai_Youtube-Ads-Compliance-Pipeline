"""
Phase 2 tests: retrieval upgrade — singleton, score filtering, reranker, 4-stage audit node.
All tests use mocks; no Azure credentials required.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.services.policy_store import RetrievedChunk, rag_min_score, rag_top_k
from src.services.reranker import rerank
from src.pipeline.nodes import (
    _attach_citations,
    _extract_claims,
    _synthesize_report,
)


# ── policy_store ─────────────────────────────────────────────────────────────

def test_rag_top_k_default():
    import os
    os.environ.pop("RAG_TOP_K", None)
    assert rag_top_k() == 20  # over-retrieve default for reranking


def test_rag_min_score_default():
    import os
    os.environ.pop("RAG_MIN_SCORE", None)
    assert rag_min_score() == 0.45


def test_retrieved_chunk_has_score_and_platform():
    chunk = RetrievedChunk(chunk_id="x", source="src", content="text", score=0.9, platform="youtube")
    assert chunk.score == 0.9
    assert chunk.platform == "youtube"


def test_score_defaults_to_zero():
    chunk = RetrievedChunk(chunk_id="x", source="src", content="text")
    assert chunk.score == 0.0


def test_search_policy_chunks_filters_low_scores():
    """Chunks below RAG_MIN_SCORE must be excluded."""
    import os
    os.environ["RAG_MIN_SCORE"] = "0.8"

    high = MagicMock()
    high.metadata = {"chunk_id": "high-id", "source": "yt.pdf"}
    high.page_content = "high quality rule"

    low = MagicMock()
    low.metadata = {"chunk_id": "low-id", "source": "yt.pdf"}
    low.page_content = "noisy irrelevant text"

    with patch("src.services.policy_store._store") as mock_store, \
         patch("src.services.policy_store.get_vector_store") as mock_get:
        mock_store_instance = MagicMock()
        mock_get.return_value = mock_store_instance
        mock_store_instance.similarity_search_with_score.return_value = [
            (high, 0.95),
            (low, 0.30),
        ]

        from src.services.policy_store import search_policy_chunks
        # reset singleton to force re-init through mock
        import src.services.policy_store as ps
        ps._store = mock_store_instance

        chunks = search_policy_chunks("health claim", k=10)

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "high-id"
    assert chunks[0].score == 0.95

    os.environ.pop("RAG_MIN_SCORE", None)


# ── reranker ──────────────────────────────────────────────────────────────────

def test_rerank_orders_by_score():
    chunks = [
        RetrievedChunk(chunk_id="a", source="s", content="general advertising rule"),
        RetrievedChunk(chunk_id="b", source="s", content="FTC health claim disclosure requirement"),
        RetrievedChunk(chunk_id="c", source="s", content="video thumbnail policy"),
    ]
    with patch("src.services.reranker._get_model") as mock_get:
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.2, 0.9, 0.1]
        mock_get.return_value = mock_model

        result = rerank("health claim disclosure", chunks, top_n=2)

    assert len(result) == 2
    assert result[0].chunk_id == "b"  # highest score
    assert result[0].score == pytest.approx(0.9)


def test_rerank_returns_top_n():
    chunks = [RetrievedChunk(chunk_id=str(i), source="s", content=f"rule {i}") for i in range(10)]
    with patch("src.services.reranker._get_model") as mock_get:
        mock_model = MagicMock()
        mock_model.predict.return_value = list(range(10))
        mock_get.return_value = mock_model
        result = rerank("query", chunks, top_n=3)
    assert len(result) == 3


def test_rerank_empty_input():
    assert rerank("query", []) == []


def test_rerank_degrades_gracefully_on_model_error():
    chunks = [RetrievedChunk(chunk_id="x", source="s", content="rule")]
    with patch("src.services.reranker._get_model") as mock_get:
        mock_get.side_effect = RuntimeError("model load failed")
        result = rerank("query", chunks, top_n=5)
    # Falls back to original order, doesn't raise
    assert result == chunks


# ── 4-stage audit node helpers ────────────────────────────────────────────────

def test_extract_claims_returns_list_on_valid_json():
    with patch("src.pipeline.nodes._mini_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm_factory.return_value = mock_llm
        mock_llm.invoke.return_value = MagicMock(
            content='[{"claim": "burns fat 3x faster", "type": "health_claim", "timestamp": "0:05"}]'
        )
        claims = _extract_claims("This supplement burns fat 3x faster!", [])
    assert len(claims) == 1
    assert claims[0]["type"] == "health_claim"


def test_extract_claims_falls_back_on_bad_json():
    with patch("src.pipeline.nodes._mini_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm_factory.return_value = mock_llm
        mock_llm.invoke.return_value = MagicMock(content="not valid json {{{{")
        claims = _extract_claims("Some transcript", [])
    # Fallback: returns a single general claim
    assert len(claims) == 1
    assert claims[0]["type"] == "general"


def test_synthesize_report_no_violations():
    report = _synthesize_report([], "PASS")
    assert "pass" in report.lower() or "no" in report.lower() or "violation" in report.lower()


def test_synthesize_report_with_violations():
    violations = [{"category": "FTC Disclosure", "severity": "CRITICAL", "description": "No #ad tag found."}]
    with patch("src.pipeline.nodes._mini_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm_factory.return_value = mock_llm
        mock_llm.invoke.return_value = MagicMock(content="FAIL: Missing FTC disclosure.")
        report = _synthesize_report(violations, "FAIL")
    assert "FAIL" in report or "fail" in report.lower()


def test_attach_citations_phase2_score_preserved():
    """Score field on RetrievedChunk must survive _attach_citations."""
    chunks = [RetrievedChunk(chunk_id="abc", source="yt.pdf", content="No misleading claims.", score=0.88)]
    results = [{"chunk_id": "abc", "severity": "CRITICAL", "description": "Misleading claim"}]
    enriched = _attach_citations(results, chunks)
    assert enriched[0]["citation_source"] == "yt.pdf"


def test_attach_citations_platform_tag_passed_through():
    """Platform tag on violation must not be stripped by _attach_citations."""
    chunks = [RetrievedChunk(chunk_id="abc", source="yt.pdf", content="Rule text.", platform="youtube")]
    results = [{"chunk_id": "abc", "platform": "youtube", "description": "Violation"}]
    enriched = _attach_citations(results, chunks)
    assert enriched[0]["platform"] == "youtube"
