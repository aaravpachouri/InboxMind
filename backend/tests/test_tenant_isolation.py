from __future__ import annotations

import inspect
from pathlib import Path

from gmail_agent import public_app


ROOT = Path(__file__).resolve().parents[1]


def test_all_user_owned_persistent_tables_have_forced_rls_policies():
    migrations = "\n".join(
        (ROOT / "migrations" / name).read_text(encoding="utf-8")
        for name in (
            "0001_multi_tenant_schema.sql",
            "0002_apps_script_per_user_bridge.sql",
            "0003_user_memory_and_feedback.sql",
            "0004_local_ai_workers.sql",
            "0007_unique_active_apps_script_deployments.sql",
        )
    )
    protected_tables = (
        "gmail_accounts",
        "user_settings",
        "user_emails",
        "user_tasks",
        "user_drafts",
        "user_sync_state",
        "user_apps_script_bridges",
        "user_memories",
        "user_feedback",
        "user_ai_jobs",
    )
    for table in protected_tables:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in migrations
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in migrations
        assert f"CREATE POLICY {table}_tenant_isolation" in migrations
        assert "current_setting('app.current_user_id', true)" in migrations


def test_private_database_routes_set_transaction_local_tenant_context():
    route_names = (
        "list_drafts", "create_draft", "send_draft", "delete_draft",
        "list_memory", "create_memory", "delete_memory",
        "list_feedback", "create_feedback", "user_insights", "daily_briefing",
    )
    insert_routes = {
        "create_draft": "INSERT INTO user_drafts(user_id",
        "create_memory": "INSERT INTO user_memories(user_id",
        "create_feedback": "INSERT INTO user_feedback(user_id",
    }
    for name in route_names:
        source = inspect.getsource(getattr(public_app, name))
        expected_context = (
            "_set_user_context(conn, user_id)"
            if name == "daily_briefing"
            else '_set_user_context(conn, str(user["id"]))'
        )
        assert expected_context in source, name
        if name in insert_routes:
            assert insert_routes[name] in source, name
            assert 'user["id"]' in source, name
        else:
            assert "user_id=%s" in source, name


def test_admin_overview_is_server_guarded_and_only_returns_aggregates():
    source = inspect.getsource(public_app.platform_admin_overview)
    assert "_require_platform_admin(user)" in source
    assert "count(*) FROM app_users" in source
    assert "email" not in source.lower().split("return", 1)[-1]
    assert "user_id" not in source.lower().split("return", 1)[-1]


def test_current_user_is_derived_only_from_hashed_unrevoked_session():
    source = inspect.getsource(public_app._current_user)
    assert "session_token_hash=%s" in source
    assert "_hash(session_cookie)" in source
    assert "s.revoked_at IS NULL" in source
    assert "s.expires_at > now()" in source



def test_draft_send_is_atomically_claimed_and_delete_requires_confirmation():
    send_source = inspect.getsource(public_app.send_draft)
    delete_source = inspect.getsource(public_app.delete_draft)

    assert "status='sending'" in send_source
    assert "AND status='draft' AND gmail_draft_id IS NOT NULL" in send_source
    assert "WHERE user_id=%s AND id=%s AND status='sending'" in send_source
    assert "Explicitly confirm sending this email." in send_source

    assert "body: EmailActionRequest" in delete_source
    assert "if not body.confirm" in delete_source
    assert "Confirm deleting this draft" in delete_source
    assert "status <> 'sending'" in delete_source
    assert "_require_csrf(request, user)" in delete_source

def test_active_apps_script_deployment_url_cannot_be_shared_between_tenants():
    source = (ROOT / "migrations" / "0007_unique_active_apps_script_deployments.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE UNIQUE INDEX IF NOT EXISTS user_apps_script_bridges_active_url_unique" in source
    assert "ON user_apps_script_bridges (bridge_url)" in source
    assert "WHERE revoked_at IS NULL" in source

    connect_source = inspect.getsource(public_app.connect_apps_script_bridge)
    assert "_current_user(session)" in connect_source
    assert "_require_csrf(request, user)" in connect_source
    assert "_set_user_context(conn, str(user[\"id\"]))" in connect_source
    assert "bridge_url, encrypted_secret" in connect_source


def test_every_gmail_action_uses_the_authenticated_users_bridge():
    source = inspect.getsource(public_app._get_user_bridge)
    assert "WHERE user_id=%s AND revoked_at IS NULL" in source
    assert "(user[\"id\"],)" in source
    assert "_set_user_context(conn, str(user[\"id\"]))" in source
    assert "_fernet().decrypt" in source

    for route_name in ("list_emails", "get_email", "archive_email", "trash_email"):
        route = getattr(public_app, route_name, None)
        if route is None:
            continue
        route_source = inspect.getsource(route)
        assert "_get_user_bridge(user)" in route_source, route_name



def test_apps_script_bridge_url_and_secret_validation_reject_unsafe_values():
    from fastapi import HTTPException

    valid_url = "https://script.google.com/macros/s/AKfycbx12345678901234567890/exec"
    assert public_app._validate_bridge_url(valid_url) == valid_url
    assert public_app._validate_bridge_secret("a" * 43) == "a" * 43

    invalid_urls = (
        "http://script.google.com/macros/s/AKfycbx12345678901234567890/exec",
        "https://example.com/macros/s/AKfycbx12345678901234567890/exec",
        "https://script.google.com.evil.test/macros/s/AKfycbx12345678901234567890/exec",
        "https://script.google.com/macros/s//exec",
        "https://script.google.com/macros/s/AKfycbx12345678901234567890/exec?x=1",
    )
    for url in invalid_urls:
        try:
            public_app._validate_bridge_url(url)
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError(f"Unsafe bridge URL was accepted: {url}")

    for secret in ("short", "a" * 257, "a" * 32 + " "):
        try:
            public_app._validate_bridge_secret(secret)
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("Invalid bridge secret was accepted")


def test_bridge_status_response_does_not_expose_deployment_or_secret():
    source = inspect.getsource(public_app.apps_script_status)
    returned = source.split("return {\"connected\": True", 1)[-1]
    assert "bridge_url" not in returned
    assert "bridge_secret" not in returned
    assert '"email": email' in returned


def test_bridge_connect_performs_profile_handshake_before_persisting():
    source = inspect.getsource(public_app.connect_apps_script_bridge)
    assert "_require_csrf(request, user)" in source
    assert "_validate_bridge_url" in source
    assert "_validate_bridge_secret" in source
    assert '"profile"' in source
    assert "await _bridge_request" in source
    assert "UniqueViolation" in source
    assert "already connected to another InboxMind account" in source
