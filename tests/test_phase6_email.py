"""Phase 6 — Email delivery tests."""
import os
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.auth.dependencies import get_current_user
from src.auth.models import UserContext
from src.db.models import UserRole


def test_send_audit_report_skips_when_no_conn_string(monkeypatch, caplog):
    monkeypatch.delenv("AZURE_COMM_CONNECTION_STRING", raising=False)
    from src.services.email_service import send_audit_report
    import logging
    with caplog.at_level(logging.WARNING, logger="brand-guardian"):
        send_audit_report("test@example.com", "abc123", b"fakepdf")
    assert "skipped" in caplog.text.lower() or "not set" in caplog.text.lower()


def test_email_service_file_exists():
    path = os.path.join(os.path.dirname(__file__), "..", "src", "services", "email_service.py")
    assert os.path.exists(path)


def test_email_endpoint_requires_auth(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    client = TestClient(app)
    audit_id = str(uuid.uuid4())
    response = client.post(f"/audits/{audit_id}/email", json={"email": "x@y.com"})
    assert response.status_code == 401


def test_email_endpoint_requires_reviewer_role():
    read_only = UserContext(
        user_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        entra_oid="ro-test",
        email="ro@test.com",
        role=UserRole.read_only,
    )
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: read_only
    try:
        audit_id = str(uuid.uuid4())
        response = client.post(f"/audits/{audit_id}/email", json={"email": "x@y.com"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
