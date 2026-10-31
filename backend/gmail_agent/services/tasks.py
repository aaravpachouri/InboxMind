from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..db import Database, utc_now


class TaskService:
    def __init__(self, db: Database):
        self.db = db

    def list(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if status:
            return self.db.fetch_all("SELECT * FROM tasks WHERE status=? ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, due_date IS NULL, due_date LIMIT ?", (status, min(limit, 500)))
        return self.db.fetch_all("SELECT * FROM tasks ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, due_date IS NULL, due_date LIMIT ?", (min(limit, 500),))

    def create(self, title: str, description: str = "", due_date: str | None = None, priority: str = "medium", source_email_id: str | None = None, origin: str = "manual") -> dict[str, Any]:
        now = utc_now()
        task_id = self.db.execute(
            "INSERT INTO tasks(title,description,source_email_id,due_date,priority,status,created_at,updated_at,origin) VALUES(?,?,?,?,?,'open',?,?,?)",
            (title.strip(), description.strip(), source_email_id, due_date, priority, now, now, origin),
        )
        return self.get(task_id) or {}

    def get(self, task_id: int) -> dict[str, Any] | None:
        return self.db.fetch_one("SELECT * FROM tasks WHERE id=?", (task_id,))

    def update(self, task_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {key: value for key, value in values.items() if key in {"title", "description", "due_date", "priority", "status"} and value is not None}
        if not allowed:
            return self.get(task_id)
        allowed["updated_at"] = utc_now()
        if allowed.get("status") == "done":
            allowed["completed_at"] = utc_now()
        if allowed.get("status") in {"open", "in_progress"}:
            allowed["completed_at"] = None
        assignments = ",".join(f"{key}=?" for key in allowed)
        self.db.execute(f"UPDATE tasks SET {assignments} WHERE id=?", tuple(allowed.values()) + (task_id,))
        return self.get(task_id)

    def delete(self, task_id: int) -> bool:
        return self.db.execute("DELETE FROM tasks WHERE id=?", (task_id,)) > 0

    def summary(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        active = self.db.fetch_all("SELECT due_date FROM tasks WHERE status IN ('open','in_progress')")
        overdue = 0
        for item in active:
            value = item.get("due_date")
            if not value:
                continue
            try:
                if len(str(value)) == 10:
                    due_date = datetime.strptime(str(value), "%Y-%m-%d").date()
                    overdue += int(due_date < now.date())
                else:
                    due = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=timezone.utc)
                    if due < now:
                        overdue += 1
            except ValueError:
                continue
        return {"open_count": len(active), "overdue_count": overdue}
