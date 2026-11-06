from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from gmail_agent.ai_engine import LocalAIEngine
from gmail_agent.config import Settings
from gmail_agent.main import create_app


class FakeOAuth:
    def __init__(self):
        self.secret_store = FakeSecretStore()


class FakeSecretStore:
    def load_json(self):
        return None


class FakeGmail:
    def __init__(self):
        self.oauth = FakeOAuth()
        self.sent: list[str] = []
        self.trashed: list[str] = []
        self.archived: list[str] = []

    def list_emails(self, query="", max_results=50, page_token=None):
        return {"items": [], "total_estimate": 0, "next_page_token": None}

    def profile(self):
        return {"email": "test@example.com", "messages_total": 2, "threads_total": 2}

    def create_draft(self, to_addresses, cc_addresses, bcc_addresses, subject, body_text, thread_id=None, in_reply_to=None, references=None):
        return {"id": "gmail-draft-1", "message": {"threadId": thread_id}}

    def send_draft(self, gmail_draft_id):
        self.sent.append(gmail_draft_id)
        return {"id": "sent-message-1", "threadId": "thread-1"}

    def archive(self, message_id):
        self.archived.append(message_id)
        return {"id": message_id, "labelIds": []}

    def trash(self, message_id):
        self.trashed.append(message_id)
        return {"id": message_id, "labelIds": ["TRASH"]}

    def modify_labels(self, message_id, add_labels, remove_labels):
        return {"id": message_id, "labelIds": list(add_labels)}

    def mark_read(self, message_id):
        return {"id": message_id, "labelIds": []}

    def mark_unread(self, message_id):
        return {"id": message_id, "labelIds": ["UNREAD"]}

    def batch_modify(self, message_ids, add_labels, remove_labels):
        return {"ok": True}

    def get_email(self, message_id):
        return {"id": message_id, "thread_id": "thread-1", "from_address": "sender@example.com", "to_addresses": "test@example.com", "cc_addresses": "", "subject": "Test", "snippet": "Please review this today", "body_text": "Please review this today.", "internal_date": "2026-10-25T10:00:00+00:00", "labels": ["INBOX", "UNREAD"], "is_unread": True, "is_sent": False, "has_attachments": False, "attachment_metadata": [], "raw_headers": {}}

    def get_attachment(self, message_id, attachment_id):
        return b"The appointment is on Friday. Please confirm the time."


def make_client(tmp_path: Path):
    settings = Settings(
        app_env="test",
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "test.sqlite3",
        downloads_dir=tmp_path / "data" / "downloads",
        local_files_dir=tmp_path / "local_files",
        ai_enabled=False,
        auto_sync_enabled=False,
        google_client_id="",
        google_client_secret="",
    )
    fake_gmail = FakeGmail()
    ai = LocalAIEngine(settings)
    app = create_app(settings=settings, gmail=fake_gmail, ai=ai, start_worker=False)
    return TestClient(app), fake_gmail


def test_health_and_auth_status(tmp_path):
    client, _ = make_client(tmp_path)
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    status = client.get("/api/v1/auth/status")
    assert status.status_code == 200
    assert status.json()["connected"] is False


def test_task_crud_and_insights(tmp_path):
    client, _ = make_client(tmp_path)
    created = client.post("/api/v1/tasks", json={"title": "Submit assignment", "priority": "high", "description": "Send before Friday"})
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]
    assert created.json()["status"] == "open"
    updated = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "done"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "done"
    insights = client.get("/api/v1/insights")
    assert insights.status_code == 200
    assert insights.json()["email_count"] == 0


def test_send_requires_explicit_confirmation(tmp_path):
    client, fake_gmail = make_client(tmp_path)
    draft = client.post("/api/v1/drafts", json={"to_addresses": ["person@example.com"], "subject": "Hello", "body_text": "Test body", "create_in_gmail": True})
    assert draft.status_code == 200, draft.text
    draft_id = draft.json()["id"]
    response = client.post(f"/api/v1/drafts/{draft_id}/send", json={"confirm_send": False})
    assert response.status_code == 400
    assert fake_gmail.sent == []
    response = client.post(f"/api/v1/drafts/{draft_id}/send", json={"confirm_send": True})
    assert response.status_code == 200, response.text
    assert response.json()["sent"] is True
    assert fake_gmail.sent == ["gmail-draft-1"]


def test_trash_requires_confirmation(tmp_path):
    client, fake_gmail = make_client(tmp_path)
    refused = client.post("/api/v1/emails/msg-1/trash", json={"confirm": False})
    assert refused.status_code == 400
    assert fake_gmail.trashed == []
    accepted = client.post("/api/v1/emails/msg-1/trash", json={"confirm": True})
    assert accepted.status_code == 200
    assert fake_gmail.trashed == ["msg-1"]


def test_local_email_cache_search(tmp_path):
    client, _ = make_client(tmp_path)
    services = client.app.state.services
    services.analysis.save_email({
        "id": "message-42", "thread_id": "thread-42", "from_address": "school@example.com",
        "to_addresses": "me@example.com", "cc_addresses": "", "subject": "Physics assignment deadline",
        "snippet": "Please submit by tomorrow", "body_text": "Please submit the Physics assignment by tomorrow.",
        "internal_date": "2026-10-24T10:00:00+00:00", "labels": ["INBOX", "UNREAD"], "is_unread": True,
        "is_sent": False, "has_attachments": False, "attachment_metadata": [], "raw_headers": {},
    })
    response = client.get("/api/v1/emails", params={"query": "Physics"})
    assert response.status_code == 200
    assert response.json()["total_estimate"] == 1
    assert response.json()["items"][0]["id"] == "message-42"
    analysis = services.analysis.analyze("message-42", force=True, use_model=False)
    assert analysis["priority"] in {"urgent", "high", "normal", "low"}
    assert "tasks" in analysis


def test_memory_is_persistent_and_deletable(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.post("/api/v1/memory", json={"category": "writing_style", "key": "tone", "value": "Concise and friendly"})
    assert response.status_code == 200
    listed = client.get("/api/v1/memory")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["value"] == "Concise and friendly"
    memory_id = listed.json()["items"][0]["id"]
    denied = client.request("DELETE", f"/api/v1/memory/{memory_id}", json={"confirm": False})
    assert denied.status_code == 400
    accepted = client.request("DELETE", f"/api/v1/memory/{memory_id}", json={"confirm": True})
    assert accepted.status_code == 200


def test_daily_briefing_and_follow_up_candidates(tmp_path):
    client, _ = make_client(tmp_path)
    services = client.app.state.services
    from datetime import datetime, timedelta, timezone
    sent_at = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    services.analysis.save_email({
        "id": "sent-1", "thread_id": "thread-sent-1", "from_address": "me@example.com",
        "to_addresses": "Recipient <person@example.com>", "cc_addresses": "", "subject": "Project update",
        "snippet": "I sent the project update", "body_text": "I sent the project update on Monday.",
        "internal_date": sent_at, "labels": ["SENT"], "is_unread": False, "is_sent": True,
        "has_attachments": False, "attachment_metadata": [], "raw_headers": {"message-id": "<sent-1@example.com>"},
    })
    followups = client.get("/api/v1/follow-ups")
    assert followups.status_code == 200, followups.text
    assert followups.json()["count"] == 1
    briefing = client.get("/api/v1/briefing/daily")
    assert briefing.status_code == 200, briefing.text
    assert "counts" in briefing.json()


def test_attachment_analysis_requires_confirmation(tmp_path):
    client, _ = make_client(tmp_path)
    services = client.app.state.services
    services.analysis.save_email({
        "id": "attach-email", "thread_id": "attach-thread", "from_address": "sender@example.com",
        "to_addresses": "me@example.com", "cc_addresses": "", "subject": "Minutes",
        "snippet": "Meeting notes attached", "body_text": "See attached", "internal_date": "2026-10-25T10:00:00+00:00",
        "labels": ["INBOX"], "is_unread": False, "is_sent": False, "has_attachments": True,
        "attachment_metadata": [{"attachment_id": "attach-1", "filename": "minutes.txt", "mime_type": "text/plain", "size": 52}],
        "raw_headers": {},
    })
    refused = client.post("/api/v1/attachments/attach-email/attach-1/analyze", json={"confirm": False})
    assert refused.status_code == 400
    accepted = client.post("/api/v1/attachments/attach-email/attach-1/analyze", json={"confirm": True})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["filename"] == "minutes.txt"
    assert accepted.json()["character_count"] > 0


def test_settings_do_not_expose_credentials(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get("/api/v1/settings")
    assert response.status_code == 200
    assert "google_client_secret" not in response.json()
    assert "token" not in response.json()


def test_email_detail_refetches_body_when_cache_is_incomplete(tmp_path):
    client, _ = make_client(tmp_path)
    services = client.app.state.services
    services.analysis.save_email({
        "id": "body-missing", "thread_id": "thread-1", "from_address": "sender@example.com",
        "to_addresses": "test@example.com", "cc_addresses": "", "subject": "Test",
        "snippet": "Short preview", "body_text": "", "internal_date": "2026-10-25T10:00:00+00:00",
        "labels": ["INBOX"], "is_unread": False, "is_sent": False,
        "has_attachments": False, "attachment_metadata": [], "raw_headers": {},
    })

    response = client.get("/api/v1/emails/body-missing")
    assert response.status_code == 200, response.text
    assert response.json()["body_text"] == "Please review this today."


def test_manual_sync_resumes_pagination_between_clicks(tmp_path):
    client, _ = make_client(tmp_path)
    services = client.app.state.services

    class CursorGmail:
        def __init__(self):
            self.calls = []

        def list_emails(self, query="", max_results=50, page_token=None):
            self.calls.append(page_token)
            next_token = "page-2" if page_token is None else ("page-3" if page_token == "page-2" else None)
            return {"items": [], "total_estimate": 30, "next_page_token": next_token}

    gmail = CursorGmail()
    services.gmail = gmail
    first = client.post("/api/v1/sync", json={"max_results": 10, "query": "in:inbox newer_than:30d", "analyze": False})
    second = client.post("/api/v1/sync", json={"max_results": 10, "query": "in:inbox newer_than:30d", "analyze": False})
    third = client.post("/api/v1/sync", json={"max_results": 10, "query": "in:inbox newer_than:30d", "analyze": False})

    assert first.status_code == second.status_code == third.status_code == 200
    assert gmail.calls == [None, "page-2", "page-3"]



def test_daily_briefing_uses_timezone_safe_window_and_grounded_fallback(tmp_path):
    client, _ = make_client(tmp_path)
    services = client.app.state.services
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    services.analysis.save_email({
        "id": "recent-offset", "thread_id": "recent-offset-thread",
        "from_address": "sender@example.com", "to_addresses": "test@example.com",
        "cc_addresses": "", "subject": "Action required: review plan",
        "snippet": "Please review the plan today.", "body_text": "Please review the plan today.",
        "internal_date": (now.astimezone(timezone(timedelta(hours=5, minutes=30)))).isoformat(),
        "labels": ["INBOX", "UNREAD"], "is_unread": True, "is_sent": False,
        "priority": "urgent", "category": "work", "ai_summary": "Review the plan today.",
        "has_attachments": False, "attachment_metadata": [], "raw_headers": {},
    })
    services.db.execute(
        "UPDATE emails SET priority='urgent', category='work', ai_summary=? WHERE id=?",
        ("Review the plan today.", "recent-offset"),
    )
    services.analysis.save_email({
        "id": "old-message", "thread_id": "old-thread",
        "from_address": "sender@example.com", "to_addresses": "test@example.com",
        "cc_addresses": "", "subject": "Old message",
        "snippet": "This is outside the requested window.", "body_text": "Old message.",
        "internal_date": (now - timedelta(days=3)).isoformat(),
        "labels": ["INBOX"], "is_unread": False, "is_sent": False,
        "priority": "low", "category": "other",
        "has_attachments": False, "attachment_metadata": [], "raw_headers": {},
    })

    response = client.get("/api/v1/briefing/daily?hours=24")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["counts"]["emails_indexed_in_period"] == 1
    assert payload["counts"]["unread_in_period"] == 1
    assert payload["counts"]["urgent_or_high"] == 1
    assert payload["important_emails"][0]["id"] == "recent-offset"
    assert "review plan" in payload["summary"].lower()
    assert payload["provider"] == "local-summary"
