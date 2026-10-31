from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class AuthStatus(APIModel):
    connected: bool
    email: str | None = None
    scopes: list[str] = Field(default_factory=list)
    message: str = ""


class EmailSummary(APIModel):
    id: str
    thread_id: str
    from_address: str
    to_addresses: str = ""
    subject: str
    snippet: str = ""
    internal_date: str = ""
    labels: list[str] = Field(default_factory=list)
    is_unread: bool = False
    is_sent: bool = False
    has_attachments: bool = False
    priority: str = "normal"
    category: str = "uncategorized"
    ai_summary: str = ""


class EmailDetail(EmailSummary):
    cc_addresses: str = ""
    body_text: str = ""
    attachment_metadata: list[dict[str, Any]] = Field(default_factory=list)
    ai_analysis: dict[str, Any] = Field(default_factory=dict)
    raw_headers: dict[str, str] = Field(default_factory=dict)


class EmailList(APIModel):
    items: list[EmailSummary]
    total_estimate: int = 0
    next_page_token: str | None = None
    source: Literal["cache", "gmail"] = "cache"


class SyncRequest(APIModel):
    max_results: int = Field(default=50, ge=1, le=100)
    query: str = ""
    page_token: str | None = None
    analyze: bool = True


class SyncResult(APIModel):
    fetched: int
    stored: int
    analyzed: int
    tasks_created: int
    errors: list[str] = Field(default_factory=list)
    completed_at: str
    next_page_token: str | None = None


class AnalyzeRequest(APIModel):
    force: bool = False


class ChatRequest(APIModel):
    message: str = Field(min_length=1, max_length=6000)
    include_recent_emails: bool = True


class ChatResponse(APIModel):
    answer: str
    intent: str = "general"
    related_emails: list[EmailSummary] = Field(default_factory=list)
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list)
    ai_provider: str = "heuristic"


class DraftCreate(APIModel):
    to_addresses: list[str] = Field(min_length=1, max_length=20)
    cc_addresses: list[str] = Field(default_factory=list, max_length=20)
    bcc_addresses: list[str] = Field(default_factory=list, max_length=20)
    subject: str = Field(default="", max_length=998)
    body_text: str = Field(min_length=1, max_length=100000)
    source_email_id: str | None = None
    create_in_gmail: bool = True

    @field_validator("to_addresses", "cc_addresses", "bcc_addresses")
    @classmethod
    def validate_addresses(cls, values: list[str]) -> list[str]:
        import re

        address = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
        cleaned = list(dict.fromkeys(v.strip() for v in values if v.strip()))
        if any(not address.match(v) for v in cleaned):
            raise ValueError("Every recipient must be a valid email address")
        return cleaned


class DraftUpdate(APIModel):
    to_addresses: list[str] | None = None
    cc_addresses: list[str] | None = None
    bcc_addresses: list[str] | None = None
    subject: str | None = Field(default=None, max_length=998)
    body_text: str | None = Field(default=None, max_length=100000)


class ReplyDraftRequest(APIModel):
    instruction: str = Field(default="", max_length=3000)
    create_in_gmail: bool = True


class SendApproval(APIModel):
    confirm_send: bool


class ActionConfirmation(APIModel):
    confirm: bool


class LabelUpdate(APIModel):
    add_labels: list[str] = Field(default_factory=list, max_length=50)
    remove_labels: list[str] = Field(default_factory=list, max_length=50)


class BulkActionRequest(APIModel):
    query: str = Field(min_length=1, max_length=500)
    action: Literal["archive", "mark_read", "mark_unread", "trash"]
    max_items: int = Field(default=25, ge=1, le=500)
    confirm: bool = False


class TaskCreate(APIModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    due_date: datetime | None = None
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    source_email_id: str | None = None


class TaskUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    due_date: datetime | None = None
    priority: Literal["low", "medium", "high", "urgent"] | None = None
    status: Literal["open", "in_progress", "done", "dismissed"] | None = None


class MemoryCreate(APIModel):
    category: str = Field(min_length=1, max_length=80)
    key: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=5000)


class FeedbackCreate(APIModel):
    kind: Literal["summary", "priority", "draft", "classification", "general"]
    feedback_text: str = Field(min_length=1, max_length=5000)
    input_summary: str = Field(default="", max_length=2000)


class SettingsUpdate(APIModel):
    ai_enabled: bool | None = None
    ollama_model: str | None = Field(default=None, min_length=1, max_length=120)
    auto_sync_enabled: bool | None = None
    sync_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    sync_window_days: int | None = Field(default=None, ge=1, le=365)


class FileIndexResult(APIModel):
    indexed: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class FileSearchResult(APIModel):
    relative_path: str
    filename: str
    excerpt: str
    modified_at: str


class CalendarEventCreate(APIModel):
    summary: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    start: datetime
    end: datetime
    timezone: str = "Asia/Kolkata"
    attendees: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("end")
    @classmethod
    def end_is_after_start(cls, end: datetime, info: Any) -> datetime:
        start = info.data.get("start")
        if start:
            comparable_start = start.replace(tzinfo=None)
            comparable_end = end.replace(tzinfo=None)
            if comparable_end <= comparable_start:
                raise ValueError("Event end must be after its start")
        return end


class NotificationRead(APIModel):
    read: bool = True


class InsightsResponse(APIModel):
    connected: bool
    last_sync: str | None = None
    email_count: int
    unread_count: int
    high_priority_count: int
    open_tasks_count: int
    overdue_tasks_count: int
    category_counts: dict[str, int]
    recent_activity: list[dict[str, Any]]
    model_available: bool
