from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from gmail_agent import public_app


ROOT = Path(__file__).resolve().parents[2]


def test_private_worker_routes_are_registered() -> None:
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in public_app.app.routes}
    expected = {
        ("/api/v1/ai/workers/register", ("POST",)),
        ("/api/v1/ai/workers/revoke", ("POST",)),
        ("/api/v1/ai/worker/heartbeat", ("POST",)),
        ("/api/v1/ai/worker/jobs/claim", ("POST",)),
        ("/api/v1/ai/worker/jobs/{job_id}/complete", ("POST",)),
        ("/api/v1/system/model", ("GET",)),
    }
    assert expected.issubset(routes)


def test_worker_auth_rejects_missing_or_malformed_bearer_before_database_access() -> None:
    for value in (None, "", "token", "Basic " + "x" * 64, "Bearer short"):
        with pytest.raises(HTTPException) as error:
            public_app._current_ai_worker(value)
        assert error.value.status_code == 401


def test_ai_jobs_respect_the_per_user_ai_enabled_setting() -> None:
    source = inspect.getsource(public_app._run_local_ai_job)
    gate = inspect.getsource(public_app._user_ai_enabled)
    enforcement = inspect.getsource(public_app._require_ai_enabled)
    assert "_require_ai_enabled(user_id)" in source
    assert 'settings.get("ai_enabled") is True' in gate
    assert "if not _user_ai_enabled(user_id)" in enforcement
    assert "HTTPException(403" in enforcement


def test_model_status_reports_ai_opt_in_separately_from_worker_health() -> None:
    source = inspect.getsource(public_app.hosted_model_status)
    assert "_user_ai_enabled" in source
    assert '"ai_enabled": ai_enabled' in source
    assert '"worker_registered": False' in source
    assert '"worker_registered": True' in source
    assert "AI analysis is disabled in Settings" in source


def test_ai_fails_closed_when_worker_is_not_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public_app, "_worker_for_user", lambda _user_id: None)
    with pytest.raises(HTTPException) as error:
        public_app._require_online_ai_worker("user-1")
    assert error.value.status_code == 503


def test_ai_fails_closed_when_worker_heartbeat_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public_app, "_worker_for_user", lambda _user_id: {
        "model_available": True,
        "last_seen_at": datetime.now(timezone.utc) - timedelta(minutes=5),
    })
    with pytest.raises(HTTPException) as error:
        public_app._require_online_ai_worker("user-1")
    assert error.value.status_code == 503


def test_worker_claim_and_result_paths_set_tenant_context() -> None:
    claim = inspect.getsource(public_app.claim_ai_worker_job)
    complete = inspect.getsource(public_app.complete_ai_worker_job)
    assert "_current_ai_worker(authorization)" in claim
    assert "_set_user_context(conn, str(worker[\"user_id\"]))" in claim
    assert "_set_user_context(conn, str(worker[\"user_id\"]))" in complete
    assert "worker_id=%s" in complete


def test_worker_tokens_are_random_and_only_hashes_are_persisted() -> None:
    source = inspect.getsource(public_app.register_ai_worker)
    assert "secrets.token_urlsafe(48)" in source
    assert "_hash(token)" in source
    assert "token_hash" in source


def test_worker_queue_migration_has_tenant_isolation_and_lease_fields() -> None:
    migration = (ROOT / "backend" / "migrations" / "0004_local_ai_workers.sql").read_text(encoding="utf-8")
    assert "user_ai_workers" in migration
    assert "user_ai_jobs" in migration
    assert "lease_until" in migration
    assert "payload BYTEA NOT NULL" in migration
    assert "result BYTEA" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "user_ai_jobs_tenant_isolation" in migration


def test_apps_script_body_normalization_uses_plain_text_and_reports_truncation() -> None:
    source = (ROOT / "apps-script" / "InboxMind_Gmail_Bridge_Full_Rewrite.gs").read_text(encoding="utf-8")
    assert "function htmlToPlainText_(html)" in source
    assert "function decodeHtmlEntities_(value)" in source
    assert "parsed.html !== null ? htmlToPlainText_(parsed.html)" in source
    assert "body_truncated: truncated" in source
    assert "MAX_BODY_LENGTH = 500000" in source
    assert "serializeMessage_(full, labelMap, false)" in source
    assert "serializeMessage_(message, getLabelMap_())" in source


def test_ai_job_content_is_encrypted_before_database_storage_and_decrypted_for_worker() -> None:
    submit = inspect.getsource(public_app._run_local_ai_job)
    claim = inspect.getsource(public_app.claim_ai_worker_job)
    complete = inspect.getsource(public_app.complete_ai_worker_job)
    assert "_fernet().encrypt(json.dumps(payload" in submit
    assert "_fernet().decrypt(bytes(updated[\"payload\"]))" in claim
    assert "_fernet().encrypt(json.dumps(body.result" in complete


def test_windows_worker_keeps_ollama_on_loopback_and_uses_credential_manager() -> None:
    source_path = ROOT / "worker" / "run_worker.py"
    source = source_path.read_text(encoding="utf-8")
    ast.parse(source)
    assert "http://127.0.0.1:11434" in source
    assert "keyring.get_password" in source
    assert "Authorization" in source
    assert "/ai/worker/jobs/claim" in source
    assert "/ai/worker/jobs/" in source


def test_worker_requirements_include_http_and_windows_credential_storage() -> None:
    requirements = (ROOT / "worker" / "requirements.txt").read_text(encoding="utf-8")
    assert "httpx" in requirements
    assert "keyring" in requirements


def test_windows_worker_sends_heartbeat_on_a_separate_thread_during_inference() -> None:
    source = (ROOT / "worker" / "run_worker.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "heartbeat_loop" in names
    assert "threading.Thread" in source
    assert 'name="inboxmind-heartbeat"' in source
    assert "stop_event.wait(HEARTBEAT_SECONDS)" in source
    assert "InboxMind heartbeat confirmed" in source

def test_worker_claim_is_limited_to_its_owner_and_uses_safe_leases() -> None:
    source = inspect.getsource(public_app.claim_ai_worker_job)
    assert "WHERE user_id=%s AND attempts < 3" in source
    assert "status='queued' OR (status='leased' AND lease_until < now())" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "WHERE id=%s AND user_id=%s" in source
    assert "worker[\\"user_id\\"]" in source


def test_worker_completion_requires_job_owner_worker_and_active_lease() -> None:
    source = inspect.getsource(public_app.complete_ai_worker_job)
    assert "WHERE id=%s AND user_id=%s AND worker_id=%s AND status='leased'" in source
    assert 'worker["user_id"]' in source
    assert 'worker["id"]' in source
    assert "if not row" in source
    assert "HTTPException(409" in source


def test_worker_heartbeat_cannot_update_another_or_revoked_worker() -> None:
    source = inspect.getsource(public_app.ai_worker_heartbeat)
    assert "WHERE id=%s AND user_id=%s AND revoked_at IS NULL" in source
    assert '_set_user_context(conn, str(worker["user_id"]))' in source


def test_worker_registration_and_revocation_require_signed_in_csrf_session() -> None:
    register = inspect.getsource(public_app.register_ai_worker)
    revoke = inspect.getsource(public_app.revoke_ai_worker)
    for source in (register, revoke):
        assert "_current_user(session)" in source
        assert "_require_csrf(request, user)" in source
        assert '_set_user_context(conn, str(user["id"]))' in source
    assert "UPDATE user_ai_workers SET revoked_at=now()" in revoke
    assert "WHERE user_id=%s AND status IN ('queued','leased')" in revoke


def test_worker_token_lookup_uses_only_hash_and_rejects_revoked_tokens() -> None:
    source = inspect.getsource(public_app._current_ai_worker)
    assert "token_hash=%s AND revoked_at IS NULL" in source
    assert "_hash(token)" in source
    assert "token_hash" not in source.split("SELECT", 1)[-1].split("FROM", 1)[0]
