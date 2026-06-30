import os
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.src.auth.dependencies import get_current_user
from backend.src.auth.models import UserContext
from backend.src.db.models import UserRole
from backend.src.api.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_debug_routes_removed(client):
    assert client.get("/debug/env").status_code == 404
    assert client.get("/debug/vi-test").status_code == 404


def test_audit_requires_auth_when_enabled(client, monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    response = client.post("/audit", json={"video_url": "https://youtu.be/dT7S75eYhcQ"})
    assert response.status_code == 401


def test_read_only_cannot_submit_audit(client):
    read_only_user = UserContext(
        user_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        entra_oid="read-only-test",
        email="readonly@test.com",
        role=UserRole.read_only,
    )
    app.dependency_overrides[get_current_user] = lambda: read_only_user
    try:
        response = client.post("/audit", json={"video_url": "https://youtu.be/dT7S75eYhcQ"})
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_audit_response_includes_disclaimer(client):
    reviewer = UserContext(
        user_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        entra_oid="reviewer-test",
        email="reviewer@test.com",
        role=UserRole.reviewer,
    )
    app.dependency_overrides[get_current_user] = lambda: reviewer
    try:
        response = client.post("/audit", json={"video_url": "https://youtu.be/dT7S75eYhcQ"})
        if response.status_code == 200:
            body = response.json()
            assert "disclaimer" in body
            assert "legal advice" in body["disclaimer"].lower()
    finally:
        app.dependency_overrides.clear()
