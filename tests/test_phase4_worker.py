"""Phase 4 — Worker + upload mode tests."""
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.auth.dependencies import get_current_user
from src.auth.models import UserContext
from src.db.models import UserRole


def _reviewer():
    return UserContext(
        user_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        entra_oid="reviewer-test",
        email="reviewer@test.com",
        role=UserRole.reviewer,
    )


@pytest.fixture
def client():
    return TestClient(app)


def test_upload_endpoint_rejects_invalid_platform(client):
    app.dependency_overrides[get_current_user] = _reviewer
    try:
        response = client.post(
            "/audit/upload",
            data={"platforms": "invalidplatform"},
            files={"file": ("test.mp4", b"fake", "video/mp4")},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422


def test_upload_endpoint_requires_auth(client, monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    response = client.post(
        "/audit/upload",
        files={"file": ("test.mp4", b"fake", "video/mp4")},
    )
    assert response.status_code == 401


def test_update_processing_status_function_exists():
    from src.db.repository import update_processing_status
    assert callable(update_processing_status)


def test_worker_files_exist():
    base = os.path.join(os.path.dirname(__file__), "..", "src", "worker")
    assert os.path.exists(os.path.join(base, "main.py"))
    assert os.path.exists(os.path.join(base, "video_processor.py"))


def test_dockerfile_worker_exists():
    path = os.path.join(os.path.dirname(__file__), "..", "Dockerfile.worker")
    assert os.path.exists(path)
