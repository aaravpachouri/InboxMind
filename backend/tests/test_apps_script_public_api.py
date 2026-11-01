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
