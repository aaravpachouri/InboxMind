from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

from gmail_agent import public_app


def test_email_auth_and_admin_routes_are_registered():
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in public_app.app.routes}
    expected = {
        ("/api/v1/auth/signup", ("POST",)),
        ("/api/v1/auth/login", ("POST",)),
        ("/api/v1/auth/verify-email", ("POST",)),
        ("/api/v1/auth/verification/resend", ("POST",)),
        ("/api/v1/auth/password-reset/request", ("POST",)),
        ("/api/v1/auth/password-reset/complete", ("POST",)),
        ("/api/v1/admin/overview", ("GET",)),
    }
    assert expected.issubset(routes)


def test_google_identity_signin_does_not_request_gmail_permissions():
    assert public_app.SCOPES == ["openid", "email", "profile"]
    assert not any("gmail" in scope.lower() for scope in public_app.SCOPES)


def test_current_user_query_includes_database_admin_role():
    source = inspect.getsource(public_app._current_user)
    assert "u.is_platform_admin" in source


def test_platform_admin_guard_denies_regular_users(monkeypatch):
    monkeypatch.delenv("PLATFORM_ADMIN_EMAILS", raising=False)
    with pytest.raises(HTTPException) as error:
        public_app._require_platform_admin({
            "email": "regular@example.com",
            "is_platform_admin": False,
        })
    assert error.value.status_code == 403


def test_platform_admin_guard_accepts_explicit_environment_allowlist(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "owner@example.com, ops@example.com")
    public_app._require_platform_admin({
        "email": "OWNER@example.com",
        "is_platform_admin": False,
    })


def test_platform_admin_guard_accepts_database_role(monkeypatch):
    monkeypatch.delenv("PLATFORM_ADMIN_EMAILS", raising=False)
    public_app._require_platform_admin({
        "email": "admin@example.com",
        "is_platform_admin": True,
    })


def test_email_auth_uses_hashed_one_time_tokens_and_verified_login_gate():
    signup = inspect.getsource(public_app.email_signup)
    verify = inspect.getsource(public_app.verify_email)
    login = inspect.getsource(public_app.email_login)
    assert "auth_security.hash_password" in signup
    assert "auth_security.hash_one_time_token" in verify
    assert "email_verified" in login
    assert "auth_security.verify_password" in login


def test_password_reset_revokes_existing_sessions():
    source = inspect.getsource(public_app.complete_password_reset)
    assert "UPDATE user_sessions SET revoked_at=now()" in source
    assert "auth_token_issuance" in source



def test_verification_resend_is_non_enumerating_and_rate_limited():
    source = inspect.getsource(public_app.resend_email_verification)
    limiter = inspect.getsource(public_app._record_auth_email_request)
    assert "password_hash IS NOT NULL AND email_verified=false" in source
    assert "If an unverified password account exists" in source
    assert "limit=3" in source
    assert "pg_advisory_xact_lock" in limiter
    assert "auth_email_events" in limiter


def test_password_reset_request_is_rate_limited():
    source = inspect.getsource(public_app.request_password_reset)
    assert "password_reset_requested" in source
    assert "limit=3" in source

def test_password_login_is_rate_limited_and_does_not_store_raw_emails():
    source = inspect.getsource(public_app.email_login)
    limiter = inspect.getsource(public_app._check_login_rate_limit)
    failed = inspect.getsource(public_app._record_failed_login)
    assert "_check_login_rate_limit(email)" in source
    assert "_record_failed_login(email)" in source
    assert "_clear_failed_logins(email)" in source
    assert "interval '15 minutes'" in limiter
    assert ">= 10" in limiter
    assert "email_hash" in failed
    assert "email_hash" in failed



def test_hosted_release_disables_all_email_password_auth_routes():
    disabled_routes = (
        public_app.email_signup,
        public_app.resend_email_verification,
        public_app.verify_email,
        public_app.email_login,
        public_app.request_password_reset,
        public_app.complete_password_reset,
    )
    for route in disabled_routes:
        assert "_reject_email_password_auth()" in inspect.getsource(route)


def test_email_password_auth_fails_closed_without_email_provider():
    with pytest.raises(HTTPException) as error:
        public_app._reject_email_password_auth()
    assert error.value.status_code == 410
    assert "Sign in with Google instead" in str(error.value.detail)
