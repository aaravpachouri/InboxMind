from __future__ import annotations

from pathlib import Path
from typing import Any

from gmail_agent.ai_engine import LocalAIEngine
from gmail_agent.background import BackgroundSyncWorker
from gmail_agent.config import Settings
from gmail_agent.db import Database
from gmail_agent.services.email_analysis import EmailAnalysisService


class PagedFakeGmail:
    """Deterministic Gmail stand-in with 10-message pages."""

    def __init__(self, messages: list[dict[str, Any]], page_size: int = 10):
        self.messages = messages
        self.page_size = page_size
        self.calls: list[str | None] = []

    def list_emails(self, query: str, max_results: int, page_token: str | None = None) -> dict[str, Any]:
        self.calls.append(page_token)
        offset = int(page_token or 0)
        size = min(max_results, self.page_size)
        items = self.messages[offset:offset + size]
        next_offset = offset + len(items)
        return {
            "items": items,
            "total_estimate": len(self.messages),
            "next_page_token": str(next_offset) if next_offset < len(self.messages) else None,
        }


def _settings(tmp_path: Path) -> Settings:
    root = tmp_path / "data"
    return Settings(
        ai_enabled=False,
        auto_sync_enabled=False,
        sync_window_days=30,
        sync_batch_size=10,
        data_dir=root,
        database_path=root / "test.sqlite",
        local_files_dir=root / "files",
        downloads_dir=root / "downloads",
    )


def _message(index: int) -> dict[str, Any]:
    return {
        "id": f"message-{index}",
        "thread_id": f"thread-{index}",
        "from_address": f"sender{index}@example.test",
        "to_addresses": "owner@example.test",
        "cc_addresses": "",
        "subject": f"Routine message {index}",
        "snippet": "A routine business message.",
        "body_text": "Hello, this is a routine message.",
        "internal_date": f"2026-10-{(index % 28) + 1:02d}T10:00:00+00:00",
        "labels": ["INBOX", "UNREAD"],
        "is_unread": True,
        "is_sent": False,
        "has_attachments": False,
        "attachment_metadata": [],
        "raw_headers": {},
    }


def test_background_sync_walks_all_pages_and_is_idempotent(tmp_path: Path):
    settings = _settings(tmp_path)
    db = Database(settings.database_path)
    ai = LocalAIEngine(settings)
    analysis = EmailAnalysisService(db, ai)
    gmail = PagedFakeGmail([_message(i) for i in range(200)])
    worker = BackgroundSyncWorker(settings, db, gmail, analysis, ai)

    # Each cycle is deliberately bounded to three pages (30 messages here) so a
    # quota-limited provider is not hammered by a single background run.
    first = worker.run_once()
    assert first["fetched"] == 30
    assert first["pages"] == 3
    assert len(gmail.calls) == 3
    assert gmail.calls[:3] == [None, "10", "20"]
    assert db.fetch_one("SELECT COUNT(*) AS n FROM emails")["n"] == 30

    cycles = 1
    while (db.get_state("background_sync_cursor", {}) or {}).get("page_token") is not None:
        result = worker.run_once()
        assert "error" not in result
        cycles += 1
        assert cycles < 10
    assert db.fetch_one("SELECT COUNT(*) AS n FROM emails")["n"] == 200
    # Every indexed email receives a category automatically, without manual Analyze.
    assert db.fetch_one("SELECT COUNT(*) AS n FROM emails WHERE category='uncategorized'")["n"] == 0
    assert db.fetch_one("SELECT COUNT(*) AS n FROM emails WHERE ai_analysis_json='{}'")["n"] == 0

    # A fresh sweep upserts the same IDs and does not create duplicate rows.
    worker.run_once()
    assert db.fetch_one("SELECT COUNT(*) AS n FROM emails")["n"] == 200



def test_business_specific_heuristic_categories(tmp_path: Path):
    ai = LocalAIEngine(_settings(tmp_path))
    cases = [
        ({"subject": "POSH corporate training proposal", "body_text": "Please share a proposal for POSH awareness training."}, "posh_training"),
        ({"subject": "POCSO school workshop", "body_text": "We need POCSO awareness training for teachers."}, "pocso_training"),
        ({"subject": "Corporate training request", "body_text": "Please send a training proposal for our employees."}, "corporate_training"),
        ({"subject": "Event registration help", "body_text": "I need help with conference registration."}, "event_registration"),
        ({"subject": "Customer support: booking issue", "body_text": "My booking is not working."}, "customer_support"),
        ({"subject": "Vendor invoice", "body_text": "Please process the invoice payment."}, "finance"),
    ]
    for email, expected in cases:
        assert ai._heuristic_analysis(email)["category"] == expected


def test_offline_reply_fallback_is_scenario_aware_and_does_not_invent_terms(tmp_path: Path, monkeypatch):
    ai = LocalAIEngine(_settings(tmp_path))
    monkeypatch.setattr(ai, "_chat", lambda *args, **kwargs: None)
    reply = ai.write_reply({
        "from_address": "Client <client@example.test>",
        "subject": "POSH training proposal",
        "body_text": "We are interested in POSH training. Please share the next steps.",
    })
    assert reply["provider"] == "template"
    assert "POSH training proposal" in reply["body_text"]
    assert "participant count" in reply["body_text"]
    assert "confirming scope, pricing" not in reply["body_text"]


def test_background_sync_stops_on_repeated_page_token_and_reports_error(tmp_path: Path):
    settings = _settings(tmp_path)
    db = Database(settings.database_path)
    ai = LocalAIEngine(settings)
    analysis = EmailAnalysisService(db, ai)

    class RepeatingTokenGmail:
        def list_emails(self, query: str, max_results: int, page_token: str | None = None) -> dict[str, Any]:
            return {"items": [], "next_page_token": "stuck-token"}

    worker = BackgroundSyncWorker(settings, db, RepeatingTokenGmail(), analysis, ai)
    result = worker.run_once()
    assert "error" in result
    assert "repeated page token" in result["error"]
    assert worker.last_error is not None
    assert "repeated page token" in worker.last_error


def test_background_sync_persists_cursor_when_more_than_cycle_limit(tmp_path: Path):
    settings = _settings(tmp_path)
    db = Database(settings.database_path)
    ai = LocalAIEngine(settings)
    analysis = EmailAnalysisService(db, ai)
    gmail = PagedFakeGmail([_message(i) for i in range(260)])
    worker = BackgroundSyncWorker(settings, db, gmail, analysis, ai)

    first = worker.run_once()
    assert first["fetched"] == 30
    cursor = db.get_state("background_sync_cursor", {})
    assert cursor["page_token"] == "30"

    cycles = 1
    while (db.get_state("background_sync_cursor", {}) or {}).get("page_token") is not None:
        result = worker.run_once()
        assert "error" not in result
        cycles += 1
        assert cycles < 12
    assert db.fetch_one("SELECT COUNT(*) AS n FROM emails")["n"] == 260
    assert db.get_state("background_sync_cursor", {})["page_token"] is None


def test_save_email_does_not_erase_a_previously_fetched_full_body(tmp_path: Path):
    settings = _settings(tmp_path)
    db = Database(settings.database_path)
    analysis = EmailAnalysisService(db, LocalAIEngine(settings))
    complete = _message(42)
    complete["body_text"] = "Full body with all original content."
    analysis.save_email(complete)

    incomplete = dict(complete)
    incomplete["body_text"] = ""
    incomplete["cc_addresses"] = ""
    incomplete["attachment_metadata"] = []
    analysis.save_email(incomplete)

    saved = analysis.get_email(complete["id"])
    assert saved["body_text"] == "Full body with all original content."


def test_ensure_analysis_preserves_existing_richer_analysis(tmp_path: Path):
    settings = _settings(tmp_path)
    db = Database(settings.database_path)
    ai = LocalAIEngine(settings)
    analysis = EmailAnalysisService(db, ai)
    email = _message(7)
    analysis.save_email(email)
    richer = {
        "summary": "Previously reviewed by local model.",
        "priority": "high",
        "category": "corporate_training",
        "reason": "Existing saved analysis",
        "action_needed": True,
        "tasks": [],
        "phishing_risk": "low",
        "phishing_reasons": [],
        "suggested_reply": "",
        "provider": "ollama",
    }
    db.execute(
        "UPDATE emails SET priority=?, category=?, ai_summary=?, ai_analysis_json=? WHERE id=?",
        ("high", "corporate_training", richer["summary"], __import__("json").dumps(richer), email["id"]),
    )
    returned = analysis.ensure_analysis(email["id"])
    assert returned == richer
    stored = analysis.get_email(email["id"])
    assert stored["category"] == "corporate_training"
    assert stored["ai_summary"] == "Previously reviewed by local model."


def test_ensure_analysis_preserves_existing_richer_analysis(tmp_path: Path):
    import json

    settings = _settings(tmp_path)
    db = Database(settings.database_path)
    ai = LocalAIEngine(settings)
    analysis = EmailAnalysisService(db, ai)
    email = _message(7)
    analysis.save_email(email)
    richer = {
        "summary": "Previously reviewed by local model.",
        "priority": "high",
        "category": "corporate_training",
        "reason": "Existing saved analysis",
        "action_needed": True,
        "tasks": [],
        "phishing_risk": "low",
        "phishing_reasons": [],
        "suggested_reply": "",
        "provider": "ollama",
    }
    db.execute(
        "UPDATE emails SET priority=?, category=?, ai_summary=?, ai_analysis_json=? WHERE id=?",
        ("high", "corporate_training", richer["summary"], json.dumps(richer), email["id"]),
    )
    returned = analysis.ensure_analysis(email["id"])
    assert returned == richer
    stored = analysis.get_email(email["id"])
    assert stored["category"] == "corporate_training"
    assert stored["ai_summary"] == "Previously reviewed by local model."


def test_gmail_list_reuses_service_for_all_messages_on_a_page(monkeypatch):
    from gmail_agent.gmail_client import GmailClient

    class Request:
        def __init__(self, value):
            self.value = value
        def execute(self):
            return self.value

    class Messages:
        def list(self, **kwargs):
            return Request({"messages": [{"id": "a"}, {"id": "b"}], "resultSizeEstimate": 2})
        def get(self, userId, id, format):
            return Request({"id": id, "threadId": f"thread-{id}", "payload": {"headers": []}})

    class Users:
        def messages(self):
            return Messages()

    class Service:
        def users(self):
            return Users()

    client = GmailClient(oauth=object())
    service = Service()
    service_builds = []
    monkeypatch.setattr(client, "_service", lambda: service_builds.append(True) or service)

    result = client.list_emails(max_results=10)

    assert [item["id"] for item in result["items"]] == ["a", "b"]
    assert len(service_builds) == 1
