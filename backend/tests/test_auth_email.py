from __future__ import annotations

import pytest
import httpx

from gmail_agent import auth_email


def test_auth_email_requires_explicit_free_or_paid_provider_configuration(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("INBOXMIND_AUTH_EMAIL_FROM", "InboxMind <auth@example.com>")
    monkeypatch.setenv("FRONTEND_URL", "https://example.com")
    with pytest.raises(auth_email.AuthEmailDeliveryError):
        auth_email._auth_email_config()


def test_auth_email_requires_https_frontend(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("INBOXMIND_AUTH_EMAIL_FROM", "InboxMind <auth@example.com>")
    monkeypatch.setenv("FRONTEND_URL", "http://example.com")
    with pytest.raises(auth_email.AuthEmailDeliveryError):
        auth_email._auth_email_config()


@pytest.mark.asyncio
async def test_account_email_sends_one_time_link_without_logging_token(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("INBOXMIND_AUTH_EMAIL_FROM", "InboxMind <auth@example.com>")
    monkeypatch.setenv("FRONTEND_URL", "https://example.com")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, timeout):
            assert timeout == 15

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, payload=json)
            return FakeResponse()

    monkeypatch.setattr(auth_email.httpx, "AsyncClient", FakeClient)
    await auth_email.send_account_action_email(
        "person@example.com", purpose="verify-email", token="one-time-token-123456789"
    )
    assert captured["url"] == auth_email.RESEND_API_URL
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["to"] == ["person@example.com"]
    assert "one-time-token-123456789" in captured["payload"]["text"]


@pytest.mark.asyncio
async def test_unknown_email_purpose_is_rejected_before_delivery():
    with pytest.raises(ValueError):
        await auth_email.send_account_action_email(
            "person@example.com", purpose="other", token="one-time-token-123456789"
        )
