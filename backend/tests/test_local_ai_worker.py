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
