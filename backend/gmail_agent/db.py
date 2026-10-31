from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Small local SQLite repository. Email body and attachment contents are not logged."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(str(self.path), timeout=15, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS emails (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            from_address TEXT NOT NULL DEFAULT '',
            to_addresses TEXT NOT NULL DEFAULT '',
            cc_addresses TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            snippet TEXT NOT NULL DEFAULT '',
            body_text TEXT NOT NULL DEFAULT '',
            internal_date TEXT NOT NULL DEFAULT '',
            labels_json TEXT NOT NULL DEFAULT '[]',
            is_unread INTEGER NOT NULL DEFAULT 0,
            is_sent INTEGER NOT NULL DEFAULT 0,
            has_attachments INTEGER NOT NULL DEFAULT 0,
            attachment_metadata_json TEXT NOT NULL DEFAULT '[]',
            priority TEXT NOT NULL DEFAULT 'normal',
            category TEXT NOT NULL DEFAULT 'uncategorized',
            ai_summary TEXT NOT NULL DEFAULT '',
            ai_analysis_json TEXT NOT NULL DEFAULT '{}',
            indexed_at TEXT NOT NULL,
            raw_headers_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(internal_date DESC);
        CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id);
        CREATE INDEX IF NOT EXISTS idx_emails_priority ON emails(priority);
        CREATE INDEX IF NOT EXISTS idx_emails_category ON emails(category);
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            source_email_id TEXT,
            due_date TEXT,
            priority TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            origin TEXT NOT NULL DEFAULT 'email',
            FOREIGN KEY(source_email_id) REFERENCES emails(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_status_due ON tasks(status, due_date);
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            memory_key TEXT NOT NULL,
            memory_value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(category, memory_key)
        );
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail_draft_id TEXT,
            to_addresses TEXT NOT NULL,
            cc_addresses TEXT NOT NULL DEFAULT '',
            bcc_addresses TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            body_text TEXT NOT NULL DEFAULT '',
            source_email_id TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            sent_at TEXT,
            FOREIGN KEY(source_email_id) REFERENCES emails(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            input_summary TEXT NOT NULL DEFAULT '',
            feedback_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS file_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            relative_path TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            content TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT 'info',
            source_id TEXT,
            created_at TEXT NOT NULL,
            read_at TEXT
        );
        CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            target_id TEXT,
            outcome TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_state (
            state_key TEXT PRIMARY KEY,
            state_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
        with self.connection() as conn:
            conn.executescript(schema)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.connection() as conn:
            cur = conn.execute(sql, params)
            if sql.lstrip().upper().startswith("INSERT"):
                return int(cur.lastrowid or 0)
            return int(cur.rowcount if cur.rowcount is not None else 0)

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def upsert_state(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        now = utc_now()
        self.execute(
            "INSERT INTO app_state(state_key,state_value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=excluded.updated_at",
            (key, payload, now),
        )

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.fetch_one("SELECT state_value FROM app_state WHERE state_key=?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["state_value"])
        except (TypeError, json.JSONDecodeError):
            return default

    def log_action(self, action: str, target_id: str | None, outcome: str, detail: str = "") -> None:
        # Do not pass full message bodies, OAuth tokens, or other secrets in detail.
        self.execute(
            "INSERT INTO action_log(action,target_id,outcome,detail,created_at) VALUES(?,?,?,?,?)",
            (action, target_id, outcome, detail[:500], utc_now()),
        )
