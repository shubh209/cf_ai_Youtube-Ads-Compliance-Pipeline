from src.pipeline.nodes import _attach_citations
from src.services.policy_store import RetrievedChunk


def test_attach_citations_fills_from_chunk_map():
    chunks = [
        RetrievedChunk(chunk_id="abc", source="youtube-ad-specs.pdf", content="No misleading claims allowed."),
    ]
    results = [{"category": "Claims", "severity": "CRITICAL", "description": "Misleading", "chunk_id": "abc"}]
    enriched = _attach_citations(results, chunks)
    assert enriched[0]["citation_source"] == "youtube-ad-specs.pdf"
    assert "misleading" in enriched[0]["citation_excerpt"].lower()


def test_attach_citations_leaves_unknown_chunk_ids():
    results = [{"category": "Claims", "severity": "INFO", "description": "Ok", "chunk_id": "missing"}]
    enriched = _attach_citations(results, [])
    assert enriched[0]["category"] == "Claims"
