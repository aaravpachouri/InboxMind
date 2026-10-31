from __future__ import annotations

import json
from typing import Any

from ..ai_engine import LocalAIEngine
from ..db import Database, utc_now


class EmailAnalysisService:
    def __init__(self, db: Database, ai: LocalAIEngine):
        self.db = db
        self.ai = ai

    def save_email(self, email: dict[str, Any]) -> None:
        now = utc_now()
        self.db.execute(
            """INSERT INTO emails(id,thread_id,from_address,to_addresses,cc_addresses,subject,snippet,body_text,
            internal_date,labels_json,is_unread,is_sent,has_attachments,attachment_metadata_json,indexed_at,raw_headers_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET thread_id=COALESCE(NULLIF(excluded.thread_id,''),emails.thread_id),
            from_address=COALESCE(NULLIF(excluded.from_address,''),emails.from_address),
            to_addresses=COALESCE(NULLIF(excluded.to_addresses,''),emails.to_addresses),
            cc_addresses=COALESCE(NULLIF(excluded.cc_addresses,''),emails.cc_addresses),
            subject=COALESCE(NULLIF(excluded.subject,''),emails.subject),
            snippet=COALESCE(NULLIF(excluded.snippet,''),emails.snippet),
            body_text=CASE WHEN TRIM(COALESCE(excluded.body_text,''))<>'' THEN excluded.body_text ELSE emails.body_text END,
            internal_date=COALESCE(NULLIF(excluded.internal_date,''),emails.internal_date),
            labels_json=excluded.labels_json,is_unread=excluded.is_unread,is_sent=excluded.is_sent,
            has_attachments=excluded.has_attachments,
            attachment_metadata_json=CASE WHEN excluded.attachment_metadata_json<>'[]' THEN excluded.attachment_metadata_json ELSE emails.attachment_metadata_json END,
            indexed_at=excluded.indexed_at,
            raw_headers_json=CASE WHEN excluded.raw_headers_json<>'{}' THEN excluded.raw_headers_json ELSE emails.raw_headers_json END
            """,
            (
                email.get("id", ""), email.get("thread_id", ""), email.get("from_address", ""),
                email.get("to_addresses", ""), email.get("cc_addresses", ""), email.get("subject", ""),
                email.get("snippet", ""), email.get("body_text", ""), email.get("internal_date", ""),
                json.dumps(email.get("labels", [])), int(bool(email.get("is_unread"))), int(bool(email.get("is_sent"))),
                int(bool(email.get("has_attachments"))), json.dumps(email.get("attachment_metadata", [])), now,
                json.dumps(email.get("raw_headers", {})),
            ),
        )

    def get_email(self, message_id: str) -> dict[str, Any] | None:
        row = self.db.fetch_one("SELECT * FROM emails WHERE id=?", (message_id,))
        return self._decode_row(row) if row else None

    def list_cached(self, query: str = "", limit: int = 50, offset: int = 0, unread_only: bool = False, category: str | None = None, priority: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if query.strip():
            needle = f"%{query.strip()}%"
            clauses.append("(subject LIKE ? OR from_address LIKE ? OR to_addresses LIKE ? OR snippet LIKE ? OR body_text LIKE ?)")
            params.extend([needle] * 5)
        if unread_only:
            clauses.append("is_unread=1")
        if category:
            clauses.append("category=?")
            params.append(category)
        if priority:
            clauses.append("priority=?")
            params.append(priority)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.extend([max(1, min(limit, 200)), max(0, offset)])
        rows = self.db.fetch_all(f"SELECT * FROM emails{where} ORDER BY internal_date DESC LIMIT ? OFFSET ?", tuple(params))
        return [self._decode_row(row) for row in rows]

    def count_cached(self, query: str = "", unread_only: bool = False) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if query.strip():
            needle = f"%{query.strip()}%"
            clauses.append("(subject LIKE ? OR from_address LIKE ? OR snippet LIKE ? OR body_text LIKE ?)")
            params.extend([needle] * 4)
        if unread_only:
            clauses.append("is_unread=1")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        row = self.db.fetch_one(f"SELECT COUNT(*) AS n FROM emails{where}", tuple(params))
        return int(row["n"] if row else 0)

    @staticmethod
    def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        for key, target in (("labels_json", "labels"), ("attachment_metadata_json", "attachment_metadata"), ("ai_analysis_json", "ai_analysis"), ("raw_headers_json", "raw_headers")):
            try:
                item[target] = json.loads(item.get(key) or ("{}" if target in {"ai_analysis", "raw_headers"} else "[]"))
            except json.JSONDecodeError:
                item[target] = {} if target in {"ai_analysis", "raw_headers"} else []
        item["is_unread"] = bool(item.get("is_unread"))
        item["is_sent"] = bool(item.get("is_sent"))
        item["has_attachments"] = bool(item.get("has_attachments"))
        item["priority"] = item.get("priority") or "normal"
        item["category"] = item.get("category") or "uncategorized"
        return item

    def ensure_analysis(self, message_id: str) -> dict[str, Any]:
        """Return saved analysis, running the fast offline classifier only when needed."""
        email = self.get_email(message_id)
        if not email:
            raise KeyError("Email is not in the local index. Run a sync first.")
        analysis = email.get("ai_analysis")
        if isinstance(analysis, dict) and analysis:
            return analysis
        return self.analyze(message_id, force=True, use_model=False)

    def analyze(self, message_id: str, force: bool = False, use_model: bool = True) -> dict[str, Any]:
        email = self.get_email(message_id)
        if not email:
            raise KeyError("Email is not in the local index. Run a sync first.")
        if email.get("ai_analysis") and not force:
            return email["ai_analysis"]
        memories = self.db.fetch_all("SELECT category,memory_key,memory_value FROM memories ORDER BY updated_at DESC LIMIT 20")
        feedback = self.db.fetch_all("SELECT kind,feedback_text FROM feedback ORDER BY created_at DESC LIMIT 8")
        memories.extend({"category": "feedback", "memory_key": row["kind"], "memory_value": row["feedback_text"]} for row in feedback)
        analysis = self.ai.analyze_email(email, memories) if use_model else self.ai._heuristic_analysis(email)
        self.db.execute(
            "UPDATE emails SET priority=?,category=?,ai_summary=?,ai_analysis_json=?,indexed_at=? WHERE id=?",
            (analysis.get("priority", "normal"), analysis.get("category", "other"), analysis.get("summary", ""), json.dumps(analysis, ensure_ascii=False), utc_now(), message_id),
        )
        return analysis

    def upsert_task_from_analysis(self, message_id: str, task: dict[str, Any]) -> bool:
        title = str(task.get("title", "")).strip()
        if not title:
            return False
        existing = self.db.fetch_one("SELECT id FROM tasks WHERE source_email_id=? AND lower(title)=lower(?) AND status='open'", (message_id, title))
        if existing:
            return False
        now = utc_now()
        self.db.execute(
            "INSERT INTO tasks(title,description,source_email_id,due_date,priority,status,created_at,updated_at,origin) VALUES(?,?,?,?,?,'open',?,?, 'email')",
            (title[:500], "Extracted from an email. Review before relying on it.", message_id, task.get("due_date"), task.get("priority", "medium"), now, now),
        )
        return True

    def search_candidates(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        tokens = [token for token in query.replace('"', " ").split() if len(token) > 2][:8]
        if not tokens:
            return self.list_cached(limit=limit)
        scored: list[tuple[int, dict[str, Any]]] = []
        for token in tokens:
            needle = f"%{token}%"
            rows = self.db.fetch_all(
                "SELECT * FROM emails WHERE subject LIKE ? OR from_address LIKE ? OR snippet LIKE ? OR body_text LIKE ? ORDER BY internal_date DESC LIMIT 50",
                (needle, needle, needle, needle),
            )
            for row in rows:
                item = self._decode_row(row)
                key = item["id"]
                score = sum(3 if token.lower() in str(item.get("subject", "")).lower() else 1 for _ in [0])
                old = next((index for index, pair in enumerate(scored) if pair[1]["id"] == key), None)
                if old is None:
                    scored.append((score, item))
                else:
                    old_score, old_item = scored[old]
                    scored[old] = (old_score + score, old_item)
        scored.sort(key=lambda pair: (pair[0], pair[1].get("internal_date", "")), reverse=True)
        return [item for _, item in scored[:limit]]
