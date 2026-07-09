"""Phase 3 — Live policy fetching tests. All mocked, no real API calls."""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.auth.dependencies import get_current_user
from src.auth.models import UserContext
from src.db.models import UserRole
from src.services.policy_sources import POLICY_SOURCES
from src.services.policy_store import _ALLOWED_PLATFORMS


# ── policy_fetcher tests ──────────────────────────────────────────────────────

def test_fetch_policy_source_uses_firecrawl():
    # FirecrawlApp is imported lazily inside _fetch_via_firecrawl; patch at the firecrawl module.
    source = {"id": "test-src", "url": "https://example.com", "name": "Test"}
    mock_result = {"markdown": "# Policy content"}

    mock_app = MagicMock()
    mock_app.scrape_url.return_value = mock_result

    with patch("src.services.policy_fetcher._save_to_blob") as mock_save, \
         patch("src.services.policy_fetcher._fetch_via_firecrawl", return_value="# Policy content"):
        from src.services.policy_fetcher import fetch_policy_source
        content = fetch_policy_source(source)

    assert content == "# Policy content"
    mock_save.assert_called_once()


def test_fetch_policy_source_falls_back_to_blob():
    source = {"id": "test-src", "url": "https://example.com", "name": "Test"}

    with patch("src.services.policy_fetcher._fetch_via_firecrawl", side_effect=RuntimeError("down")), \
         patch("src.services.policy_fetcher._load_from_blob", return_value="cached content"):
        from src.services.policy_fetcher import fetch_policy_source
        content = fetch_policy_source(source)

    assert content == "cached content"


def test_fetch_policy_source_raises_when_both_fail():
    source = {"id": "test-src", "url": "https://example.com", "name": "Test"}

    with patch("src.services.policy_fetcher._fetch_via_firecrawl", side_effect=RuntimeError("down")), \
         patch("src.services.policy_fetcher._load_from_blob", return_value=None):
        from src.services.policy_fetcher import fetch_policy_source
        with pytest.raises(RuntimeError):
            fetch_policy_source(source)


# ── policy_sources registry tests ────────────────────────────────────────────

def test_policy_sources_have_required_fields():
    for source in POLICY_SOURCES:
        for field in ("id", "platform", "url", "name"):
            assert field in source, f"Source {source.get('id')} missing field {field!r}"


def test_policy_sources_platforms_are_allowed():
    for source in POLICY_SOURCES:
        assert source["platform"] in _ALLOWED_PLATFORMS, (
            f"Source {source['id']} has disallowed platform {source['platform']!r}"
        )


# ── run_policy_index with platform filter ────────────────────────────────────

def test_run_policy_index_accepts_platform_filter():
    with patch("src.services.policy_indexing.fetch_policy_source") as mock_fetch, \
         patch("src.services.policy_indexing.get_vector_store") as mock_store:
        mock_fetch.return_value = "policy text"
        mock_vs = MagicMock()
        mock_store.return_value = mock_vs

        from src.services.policy_indexing import run_policy_index
        run_policy_index(db=None, platforms=["youtube"])

    fetched_ids = [call.args[0]["id"] for call in mock_fetch.call_args_list]
    fetched_platforms = [call.args[0]["platform"] for call in mock_fetch.call_args_list]
    assert all(p == "youtube" for p in fetched_platforms), (
        f"Non-youtube sources were fetched: {fetched_ids}"
    )
    non_youtube = [s for s in POLICY_SOURCES if s["platform"] != "youtube"]
    for source in non_youtube:
        assert source["id"] not in fetched_ids, f"Unexpected fetch: {source['id']}"


# ── admin reindex endpoint with platforms param ───────────────────────────────

def test_admin_reindex_accepts_platforms_param():
    admin_user = UserContext(
        user_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        entra_oid="admin-test",
        email="admin@test.com",
        role=UserRole.admin,
    )
    client = TestClient(app)

    with patch("src.api.routes.admin.run_policy_index") as mock_index:
        mock_index.return_value = {
            "version_label": "v20240101-120000",
            "chunk_count": 10,
            "policy_version_id": str(uuid.uuid4()),
        }
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            response = client.post(
                "/admin/policies/reindex?platforms=youtube",
                headers={"Authorization": "Bearer test"},
            )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_index.assert_called_once()
    call_kwargs = mock_index.call_args
    # platforms should be passed through
    assert call_kwargs.kwargs.get("platforms") == ["youtube"] or (
        call_kwargs.args and "youtube" in str(call_kwargs.args)
    )
