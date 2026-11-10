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
    for name in route_names:
        source = inspect.getsource(getattr(public_app, name))
        assert "_set_user_context(conn, str(user[\"id\"]))" in source, name
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
