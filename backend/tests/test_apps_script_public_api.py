from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

from gmail_agent import public_app


@pytest.mark.parametrize(
    "url",
    [
        "https://script.google.com/macros/s/AKfycbx-example/exec",
        "https://script.google.com/macros/s/deployment_id/exec",
    ],
)
def test_bridge_url_accepts_google_apps_script_web_app_urls(url: str) -> None:
    assert public_app._validate_bridge_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://script.google.com/macros/s/deployment_id/exec",
        "https://evil.example/macros/s/deployment_id/exec",
        "https://script.google.com.evil.example/macros/s/deployment_id/exec",
        "https://script.google.com/macros/s/deployment_id/dev",
        "https://script.google.com/macros/s/deployment_id/exec?secret=leak",
        "https://user:password@script.google.com/macros/s/deployment_id/exec",
        "https://script.google.com/",
    ],
)
def test_bridge_url_rejects_noncanonical_or_unsafe_urls(url: str) -> None:
    with pytest.raises(HTTPException) as error:
        public_app._validate_bridge_url(url)
    assert error.value.status_code == 422


def test_identity_login_requests_no_gmail_scopes() -> None:
    assert public_app.SCOPES == ["openid", "email", "profile"]
    assert not any("gmail" in scope.lower() for scope in public_app.SCOPES)


def test_email_endpoint_uses_apps_script_bridge_not_direct_gmail_api() -> None:
    source = inspect.getsource(public_app.list_emails)
    assert '"list_emails"' in source
    assert "_get_user_bridge(user)" in source
    assert "googleapiclient" not in source
    assert "Credentials(" not in source



def test_per_user_bridge_read_keeps_rls_context_inside_transaction() -> None:
    source = inspect.getsource(public_app._get_user_bridge)
    assert "with pool.connection() as conn, conn.transaction():" in source
    assert source.index("_set_user_context") < source.index("FROM user_apps_script_bridges")


def test_apps_script_backed_email_and_calendar_routes_are_registered() -> None:
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in public_app.app.routes}
    expected = {
        ("/api/v1/emails/{message_id}", ("GET",)),
        ("/api/v1/emails/{message_id}/archive", ("POST",)),
        ("/api/v1/emails/{message_id}/trash", ("POST",)),
        ("/api/v1/emails/{message_id}/mark-read", ("POST",)),
        ("/api/v1/emails/{message_id}/mark-unread", ("POST",)),
        ("/api/v1/labels", ("GET",)),
        ("/api/v1/calendar/events", ("GET",)),
    }
    assert expected.issubset(routes)


def test_email_list_accepts_search_and_pagination_parameters() -> None:
    signature = inspect.signature(public_app.list_emails)
    assert {"query", "page_token", "offset", "live"}.issubset(signature.parameters)



def test_hosted_core_routes_cover_frontend_persistence_operations() -> None:
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in public_app.app.routes}
    expected = {
        ("/api/v1/drafts/{draft_id}/send", ("POST",)),
        ("/api/v1/drafts/{draft_id}", ("DELETE",)),
        ("/api/v1/memory", ("GET",)),
        ("/api/v1/memory", ("POST",)),
        ("/api/v1/memory/{memory_id}", ("DELETE",)),
        ("/api/v1/feedback", ("GET",)),
        ("/api/v1/feedback", ("POST",)),
        ("/api/v1/sync", ("POST",)),
        ("/api/v1/briefing/daily", ("GET",)),
        ("/api/v1/chat", ("POST",)),
        ("/api/v1/emails/{message_id}/draft-reply", ("POST",)),
    }
    assert expected.issubset(routes)


def test_unavailable_ai_endpoints_do_not_claim_fake_results() -> None:
    source = inspect.getsource(public_app.summarize_email_unavailable)
    assert "No summary was fabricated" in source
    assert "HTTPException(503," in source
