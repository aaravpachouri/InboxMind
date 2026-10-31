from __future__ import annotations

from pathlib import Path

from gmail_agent.ai_engine import LocalAIEngine
from gmail_agent.config import Settings
from gmail_agent.db import Database
from gmail_agent.gmail_client import html_to_text, parse_message
from gmail_agent.security import SecretStore
from gmail_agent.services.email_analysis import EmailAnalysisService
from gmail_agent.services.file_index import LocalFileIndex
from gmail_agent.services.tasks import TaskService


def test_secret_store_encrypts_and_roundtrips(tmp_path: Path):
    store = SecretStore(tmp_path)
    value = {"token": "top-secret-token", "refresh_token": "secret-refresh"}
    store.save_json(value)
    raw = store.token_path.read_bytes()
    assert b"top-secret-token" not in raw
    assert store.load_json() == value
    store.delete()
    assert store.load_json() is None


def test_parse_message_handles_plain_and_html_parts():
    message = {
        "id": "abc", "threadId": "thread-abc", "snippet": "Hello", "internalDate": "1792922400000",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Sender <sender@example.com>"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Test subject"},
                {"name": "Message-ID", "value": "<abc@example.com>"},
            ],
            "parts": [
                {"mimeType": "text/html", "body": {"data": "PGgxPkhlbGxvPC9oMT48cD5Xb3JsZDwvcD4="}},
            ],
        },
    }
    parsed = parse_message(message)
    assert parsed["subject"] == "Test subject"
    assert parsed["is_unread"] is True
    assert "Hello" in parsed["body_text"]
    assert "World" in parsed["body_text"]
    assert parsed["raw_headers"]["message-id"] == "<abc@example.com>"


def test_html_to_text_removes_markup_and_scripts():
    result = html_to_text("<p>Hello <b>there</b></p><script>alert(1)</script><p>Bye</p>")
    assert "Hello there" in result
    assert "Bye" in result
    assert "alert" not in result


def test_heuristic_analysis_finds_action_items():
    settings = Settings(ai_enabled=False, auto_sync_enabled=False, data_dir=Path("/tmp/gmail-agent-test-ai"), database_path=Path("/tmp/gmail-agent-test-ai/db.sqlite"), local_files_dir=Path("/tmp/gmail-agent-test-ai/files"), downloads_dir=Path("/tmp/gmail-agent-test-ai/downloads"))
    ai = LocalAIEngine(settings)
    analysis = ai.analyze_email({"subject": "Action required: Physics assignment", "from_address": "teacher@example.com", "snippet": "Please submit the assignment by tomorrow", "body_text": "Please submit the assignment by tomorrow. This is urgent."})
    assert analysis["priority"] == "urgent"
    assert analysis["category"] == "education"
    assert analysis["tasks"]
    assert analysis["tasks"][0]["due_date"] is not None


def test_file_index_only_indexes_supported_files_inside_root(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "notes.md").write_text("Remember to submit the physics project by Friday.", encoding="utf-8")
    (root / "ignore.bin").write_bytes(b"raw bytes")
    db = Database(tmp_path / "db.sqlite")
    index = LocalFileIndex(db, root)
    result = index.index()
    assert result["indexed"] == 1
    search = index.search("physics project")
    assert search
    assert search[0]["filename"] == "notes.md"


def test_tasks_create_and_update(tmp_path: Path):
    db = Database(tmp_path / "db.sqlite")
    tasks = TaskService(db)
    task = tasks.create("Call back", priority="high")
    assert task["status"] == "open"
    updated = tasks.update(task["id"], {"status": "done"})
    assert updated["status"] == "done"
    assert updated["completed_at"]


def test_remote_ollama_endpoint_is_blocked_for_privacy(tmp_path: Path):
    settings = Settings(
        ai_enabled=True,
        ollama_base_url="https://example.com",
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data.sqlite",
        local_files_dir=tmp_path / "files",
        downloads_dir=tmp_path / "downloads",
    )
    ai = LocalAIEngine(settings)
    status = ai.health()
    assert status["available"] is False
    assert "blocked" in status["detail"].lower()
    assert ai._chat("system", "private email content") is None


def test_file_index_removes_deleted_files_from_search(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    note = root / "todo.txt"
    note.write_text("Remember to pay the electricity bill.", encoding="utf-8")
    index = LocalFileIndex(Database(tmp_path / "db.sqlite"), root)
    assert index.index()["indexed"] == 1
    assert index.search("electricity")
    note.unlink()
    index.index()
    assert index.search("electricity") == []


def test_date_only_task_deadline_is_not_overdue_on_due_day(tmp_path: Path):
    from datetime import datetime, timezone
    db = Database(tmp_path / "db.sqlite")
    tasks = TaskService(db)
    today = datetime.now(timezone.utc).date().isoformat()
    tasks.create("Due today", due_date=today)
    result = tasks.summary()
    assert result["open_count"] == 1
    assert result["overdue_count"] == 0
