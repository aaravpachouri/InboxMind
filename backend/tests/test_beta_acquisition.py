from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from gmail_agent import public_app


class _Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def transaction(self):
        return self

    def execute(self, query, params=()):
        self.statements.append((query, params))
        if "INSERT INTO beta_signups" in query:
            return _Cursor({"id": "signup-1", "status": "new"})
        if "SELECT id FROM beta_signups" in query:
            return _Cursor({"id": "signup-1"})
        if "INSERT INTO beta_feedback" in query:
            return _Cursor({"id": "feedback-1"})
        if "DELETE FROM beta_signups" in query:
            return _Cursor({"id": "signup-1"})
        raise AssertionError(f"Unexpected SQL: {query}")


class _Pool:
    def __init__(self, connection):
        self.connection_instance = connection

    def connection(self):
        return self.connection_instance


@pytest.fixture
def beta_client(monkeypatch):
    connection = _Connection()
    monkeypatch.setattr(public_app, "_pool_or_503", lambda: _Pool(connection))
    return TestClient(public_app.app), connection


def test_beta_signup_requires_explicit_feedback_and_contact_consent(beta_client):
    client, _ = beta_client
    response = client.post("/api/v1/public/beta-signups", json={
        "email": "test@example.com",
        "audience": "student",
        "role_context": "University student",
        "workflow": "I use Gmail for coursework and project follow-ups every day.",
        "feedback_commitment": False,
        "contact_consent": True,
    })
    assert response.status_code == 422


def test_beta_signup_returns_feedback_token_and_normalizes_email(beta_client):
    client, connection = beta_client
    response = client.post("/api/v1/public/beta-signups", json={
        "email": "  TEST@Example.com ",
        "name": "Test User",
        "audience": "student",
        "role_context": "University student",
        "workflow": "I use Gmail for coursework and project follow-ups every day.",
        "feedback_commitment": True,
        "contact_consent": True,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert len(payload["feedback_token"]) >= 32
    sql, params = connection.statements[0]
    assert "INSERT INTO beta_signups" in sql
    assert params[0] == "test@example.com"
    assert params[1] == "test@example.com"


def test_beta_feedback_requires_valid_token_and_stores_feedback(beta_client):
    client, connection = beta_client
    response = client.post("/api/v1/public/beta-feedback", json={
        "feedback_token": "t" * 40,
        "category": "inbox",
        "rating": 4,
        "details": "The inbox view is useful, but I need clearer follow-up states.",
        "permission_to_quote": False,
    })
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert any("INSERT INTO beta_feedback" in statement for statement, _ in connection.statements)


def test_beta_feedback_rejects_invalid_rating(beta_client):
    client, _ = beta_client
    response = client.post("/api/v1/public/beta-feedback", json={
        "feedback_token": "t" * 40,
        "category": "inbox",
        "rating": 6,
        "details": "This should fail validation.",
    })
    assert response.status_code == 422


def test_beta_data_can_be_deleted_with_feedback_token(beta_client):
    client, connection = beta_client
    response = client.request("DELETE", "/api/v1/public/beta-signups", json={"feedback_token": "t" * 40})
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert any("DELETE FROM beta_signups" in statement for statement, _ in connection.statements)


def test_beta_signup_honeypot_is_not_persisted(beta_client):
    client, connection = beta_client
    response = client.post("/api/v1/public/beta-signups", json={
        "email": "bot@example.com",
        "audience": "student",
        "role_context": "Student",
        "workflow": "I use email to manage project deadlines and follow-ups.",
        "feedback_commitment": True,
        "contact_consent": True,
        "website": "filled-by-bot",
    })
    assert response.status_code == 200
    assert connection.statements == []
