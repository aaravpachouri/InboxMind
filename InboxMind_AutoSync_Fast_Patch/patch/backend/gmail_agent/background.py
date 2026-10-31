from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from .ai_engine import LocalAIEngine
from .config import Settings
from .db import Database, utc_now
from .gmail_client import GmailClient
from .services.email_analysis import EmailAnalysisService


class BackgroundSyncWorker:
    """Low-frequency background monitor. It never sends or deletes email."""

    def __init__(self, settings: Settings, db: Database, gmail: GmailClient, analysis: EmailAnalysisService, ai: LocalAIEngine):
        self.settings = settings
        self.db = db
        self.gmail = gmail
        self.analysis = analysis
        self.ai = ai
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sync_lock = threading.Lock()
        self.last_error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gmail-ai-background-sync", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def run_once(self) -> dict[str, Any]:
        if not self._sync_lock.acquire(blocking=False):
            return {"skipped": True, "reason": "A sync is already in progress."}
        try:
            query = f"newer_than:{self.settings.sync_window_days}d"
            # Resume a bounded page sweep between worker cycles. This prevents a
            # large 30-day mailbox from being re-downloaded in full every few minutes.
            # A completed sweep resets to page one so newly arrived mail is discovered.
            cursor_state = self.db.get_state("background_sync_cursor", {}) or {}
            page_token: str | None = cursor_state.get("page_token") if cursor_state.get("query") == query else None
            result_items: list[dict[str, Any]] = []
            seen_tokens: set[str] = set()
            if page_token:
                seen_tokens.add(str(page_token))
            page_count = 0
            max_pages_per_cycle = 3  # Bound Gmail API work per cycle to reduce per-user quota spikes.
            next_token: str | None = page_token
            while page_count < max_pages_per_cycle:
                result = self.gmail.list_emails(
                    query=query,
                    max_results=self.settings.sync_batch_size,
                    page_token=next_token,
                )
                result_items.extend(result.get("items", []))
                page_count += 1
                returned_token = result.get("next_page_token")
                if not returned_token:
                    next_token = None
                    break
                returned_token = str(returned_token)
                if returned_token in seen_tokens or returned_token == next_token:
                    raise RuntimeError("Gmail pagination returned a repeated page token; sync stopped to avoid looping and reported an error.")
                seen_tokens.add(returned_token)
                next_token = returned_token
            if next_token:
                self.db.upsert_state("background_sync_cursor", {"query": query, "page_token": next_token, "updated_at": utc_now()})
            else:
                self.db.upsert_state("background_sync_cursor", {"query": query, "page_token": None, "updated_at": utc_now()})
            # Gmail IDs are unique. De-duplicate defensively in case a provider
            # repeats an item across page boundaries.
            unique_items: dict[str, dict[str, Any]] = {}
            for item in result_items:
                message_id = str(item.get("id") or "")
                if message_id:
                    unique_items[message_id] = item
            result_items = list(unique_items.values())
            stored = analyzed = tasks = 0
            # Only check IDs in this page. Loading the entire email table on every
            # poll made sync latency and memory use grow with mailbox size.
            current_ids = [str(item.get("id")) for item in result_items if item.get("id")]
            old_ids: set[str] = set()
            if current_ids:
                placeholders = ",".join("?" for _ in current_ids)
                old_ids = {
                    str(row["id"])
                    for row in self.db.fetch_all(
                        f"SELECT id FROM emails WHERE id IN ({placeholders})", tuple(current_ids)
                    )
                }
            for email in result_items:
                self.analysis.save_email(email)
                stored += 1
                is_new = email.get("id") not in old_ids
                # Classify only messages that do not already have analysis. This keeps
                # periodic syncs idempotent and avoids overwriting richer saved analysis.
                data = self.analysis.ensure_analysis(str(email.get("id") or ""))
                analyzed += int(bool(data))
                for task in data.get("tasks", []):
                    tasks += int(self.analysis.upsert_task_from_analysis(email.get("id", ""), task))
                if is_new and (data.get("priority") in {"urgent", "high"} or data.get("phishing_risk") == "high"):
                    title = "Important new email" if data.get("priority") in {"urgent", "high"} else "Potentially suspicious email"
                    body = f"{email.get('subject') or '(no subject)'} — {email.get('from_address', '')}"
                    self.db.execute("INSERT INTO notifications(title,body,kind,source_id,created_at) VALUES(?,?,?,?,?)", (title, body, "urgent" if data.get("priority") == "urgent" else "warning", email.get("id"), utc_now()))
            # Upgrade heuristic results with the local model in a bounded queue.
            # Only unread messages without a successful model result are eligible;
            # this avoids spending time repeatedly analyzing the same messages.
            model_available = bool(self.ai.health().get("available"))
            model_analyzed = 0
            model_failures = 0
            if model_available:
                import json

                candidates = self.db.fetch_all(
                    "SELECT id, priority, internal_date, ai_analysis_json FROM emails "
                    "WHERE is_unread=1 ORDER BY CASE priority WHEN 'urgent' THEN 0 "
                    "WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, internal_date DESC LIMIT 30"
                )
                pending_ids: list[str] = []
                for row in candidates:
                    try:
                        saved = json.loads(row.get("ai_analysis_json") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        saved = {}
                    if not isinstance(saved, dict) or saved.get("provider") != "ollama":
                        pending_ids.append(str(row["id"]))
                    if len(pending_ids) >= 3:
                        break
                for message_id in pending_ids:
                    try:
                        data = self.analysis.analyze(message_id, force=True, use_model=True)
                        if data.get("provider") == "ollama":
                            model_analyzed += 1
                            for task in data.get("tasks", []):
                                tasks += int(self.analysis.upsert_task_from_analysis(message_id, task))
                        else:
                            model_failures += 1
                    except Exception as exc:
                        model_failures += 1
                        self.db.upsert_state("last_ai_error", {
                            "message": f"{type(exc).__name__}: {str(exc)[:200]}",
                            "at": utc_now(),
                        })
            now = datetime.now(timezone.utc).isoformat()
            self._notify_due_tasks()
            self.db.upsert_state("last_sync", {
                "completed_at": now, "fetched": len(result_items), "pages": page_count,
                "source": "background", "model_analyzed": model_analyzed,
                "model_failures": model_failures,
            })
            self.db.upsert_state("last_sync_error", None)
            if model_failures:
                self.last_error = f"Local model analysis failed or fell back for {model_failures} message(s)."
                self.db.upsert_state("last_ai_error", {"message": self.last_error, "at": now})
            else:
                self.last_error = None
                self.db.upsert_state("last_ai_error", None)
            return {
                "fetched": len(result_items), "pages": page_count, "stored": stored,
                "analyzed": analyzed, "model_analyzed": model_analyzed,
                "model_failures": model_failures, "tasks_created": tasks, "completed_at": now,
            }
        except Exception as exc:
            # Discard a possibly stale provider cursor after a failed page request;
            # the next cycle restarts from the newest page rather than getting stuck.
            try:
                self.db.upsert_state("background_sync_cursor", {"query": f"newer_than:{self.settings.sync_window_days}d", "page_token": None, "updated_at": utc_now()})
            except Exception:
                pass
            self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            self.db.upsert_state("last_sync_error", {"message": self.last_error, "at": utc_now()})
            return {"error": self.last_error}
        finally:
            self._sync_lock.release()

    def _notify_due_tasks(self) -> int:
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        tasks = self.db.fetch_all("SELECT id,title,due_date,priority FROM tasks WHERE status IN ('open','in_progress') AND due_date IS NOT NULL")
        created = 0
        for task in tasks:
            raw_due = str(task.get("due_date") or "")
            if not raw_due:
                continue
            try:
                if len(raw_due) == 10:
                    due_date = datetime.fromisoformat(raw_due).date()
                    is_overdue = due_date < now.date()
                    is_due_today = due_date == now.date()
                else:
                    due = datetime.fromisoformat(raw_due.replace("Z", "+00:00"))
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=timezone.utc)
                    is_overdue = due < now
                    is_due_today = due.date() == now.date()
            except ValueError:
                continue
            if not (is_overdue or is_due_today):
                continue
            existing = self.db.fetch_one(
                "SELECT id FROM notifications WHERE kind='task_reminder' AND source_id=? AND substr(created_at,1,10)=? LIMIT 1",
                (str(task["id"]), today),
            )
            if existing:
                continue
            title = "Overdue task" if is_overdue else "Task due today"
            self.db.execute(
                "INSERT INTO notifications(title,body,kind,source_id,created_at) VALUES(?,?,?,?,?)",
                (title, str(task["title"]), "task_reminder", str(task["id"]), utc_now()),
            )
            created += 1
        return created

    def _run(self) -> None:
        # Run once shortly after startup so the inbox is classified immediately;
        # subsequent runs follow the configured interval.
        first_run = True
        while not self._stop.is_set():
            if not first_run and self._stop.wait(self.settings.sync_interval_seconds):
                break
            first_run = False
            if not self.settings.auto_sync_enabled:
                continue
            try:
                if getattr(self.gmail, "is_bridge_mode", False):
                    if self.gmail.is_connected():
                        self.run_once()
                else:
                    secret_store = getattr(getattr(self.gmail, "oauth", None), "secret_store", None)
                    if secret_store and secret_store.load_json():
                        self.run_once()
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
