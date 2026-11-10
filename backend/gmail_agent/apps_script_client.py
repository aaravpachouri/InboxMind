from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import Settings


class AppsScriptGmailClient:
    """Gmail/Calendar adapter that delegates operations to a secret-protected Apps Script web app.

    This mode keeps Google OAuth tokens inside Apps Script. The Python process stores only
    the Apps Script URL and a high-entropy shared secret in its local .env file.
    """

    def __init__(self, settings: Settings):
        self.url = str(settings.apps_script_bridge_url or "").strip()
        self.secret = str(settings.apps_script_bridge_secret or "").strip()
        self.timeout = float(settings.apps_script_bridge_timeout_seconds)
        self._validate_configuration_if_present()

    def _validate_configuration_if_present(self) -> None:
        if not self.url:
            return
        parsed = urlparse(self.url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "script.google.com"
            or not parsed.path.startswith("/macros/s/")
            or not parsed.path.endswith("/exec")
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError(
                "APPS_SCRIPT_BRIDGE_URL must be the HTTPS Google Apps Script Web app URL ending in /exec."
            )

    @property
    def is_bridge_mode(self) -> bool:
        return bool(self.url or self.secret)

    def is_ready(self) -> bool:
        return bool(self.url and self.secret)

    def is_connected(self) -> bool:
        if not self.is_ready():
            return False
        try:
            profile = self.profile()
            return bool(profile.get("email"))
        except Exception:
            return False

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Apps Script ContentService may redirect its JSON response to googleusercontent.
        # Redirects are followed, while the shared secret remains in the POST body, not URL.
        with httpx.Client(follow_redirects=True, timeout=self.timeout) as client:
            response = client.post(self.url, json=payload)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Apps Script bridge returned an invalid response.")
        return data

    def _call(self, action: str, params: dict[str, Any] | None = None) -> Any:
        if not self.url:
            raise RuntimeError("Apps Script bridge is not configured: APPS_SCRIPT_BRIDGE_URL is missing.")
        if len(self.secret) < 32:
            raise RuntimeError("Apps Script bridge is not configured with a valid BRIDGE_SECRET.")
        try:
            data = self._request({"secret": self.secret, "action": action, "params": params or {}})
        except httpx.TimeoutException as exc:
            raise RuntimeError("Apps Script bridge timed out. Check the Apps Script execution log.") from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Apps Script bridge returned HTTP {exc.response.status_code}.") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Could not reach Apps Script bridge ({type(exc).__name__}).") from exc
        except ValueError as exc:
            raise RuntimeError("Apps Script bridge returned invalid JSON.") from exc

        if not data.get("ok"):
            message = str(data.get("error") or "Apps Script bridge operation failed")
            # Avoid returning any request values or secret in diagnostic text.
            raise RuntimeError(message[:300])
        if "result" not in data:
            raise RuntimeError("Apps Script bridge response did not contain a result.")
        return data["result"]

    def profile(self) -> dict[str, Any]:
        result = self._call("profile")
        return {
            "email": result.get("email", ""),
            "messages_total": result.get("messages_total", 0),
            "threads_total": result.get("threads_total", 0),
            "history_id": result.get("history_id", ""),
        }

    def list_emails(self, query: str = "", max_results: int = 50, page_token: str | None = None) -> dict[str, Any]:
        return self._call("list_emails", {
            "query": query,
            "max_results": max(1, min(int(max_results), 10)),
            "page_token": page_token or "0",
        })

    def get_email(self, message_id: str) -> dict[str, Any]:
        return self._call("get_email", {"message_id": message_id})

    def get_thread(self, thread_id: str) -> list[dict[str, Any]]:
        result = self._call("get_thread", {"thread_id": thread_id})
        return result if isinstance(result, list) else []

    def list_labels(self) -> list[dict[str, Any]]:
        result = self._call("list_labels")
        return result if isinstance(result, list) else []

    def create_label(self, name: str) -> dict[str, Any]:
        return self._call("create_label", {"name": name})

    def modify_labels(self, message_id: str, add_labels: list[str], remove_labels: list[str]) -> dict[str, Any]:
        dangerous = {str(value).upper() for value in add_labels} & {"TRASH", "SPAM"}
        if dangerous:
            raise RuntimeError("Use the explicit confirm-protected Trash action; system labels cannot be changed through label editing.")
        return self._call("modify_labels", {
            "message_id": message_id,
            "add_labels": add_labels,
            "remove_labels": remove_labels,
        })

    def archive(self, message_id: str) -> dict[str, Any]:
        return self._call("archive", {"message_id": message_id})

    def trash(self, message_id: str) -> dict[str, Any]:
        # The FastAPI route checks explicit confirmation before this method is called.
        return self._call("trash", {"message_id": message_id, "confirmed": True})

    def mark_read(self, message_id: str) -> dict[str, Any]:
        return self._call("mark_read", {"message_id": message_id})

    def mark_unread(self, message_id: str) -> dict[str, Any]:
        return self._call("mark_unread", {"message_id": message_id})

    def batch_modify(self, message_ids: list[str], add_labels: list[str], remove_labels: list[str]) -> dict[str, Any]:
        if len(message_ids) > 50:
            raise ValueError("Apps Script bridge supports at most 50 messages per batch.")
        if {str(value).upper() for value in add_labels} & {"TRASH", "SPAM"}:
            raise RuntimeError("Bulk Trash/Spam must use the explicit confirmation-protected action.")
        return self._call("batch_modify", {
            "message_ids": message_ids,
            "add_labels": add_labels,
            "remove_labels": remove_labels,
        })

    def create_draft(
        self,
        to_addresses: list[str],
        cc_addresses: list[str],
        bcc_addresses: list[str],
        subject: str,
        body_text: str,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> dict[str, Any]:
        # Apps Script retrieves the prior thread message to establish reply headers.
        params: dict[str, Any] = {
            "to_addresses": to_addresses,
            "cc_addresses": cc_addresses,
            "bcc_addresses": bcc_addresses,
            "subject": subject,
            "body_text": body_text,
        }
        if thread_id:
            params["thread_id"] = thread_id
        result = self._call("create_draft", params)
        return {
            "id": result.get("id", ""),
            "message": {
                "id": result.get("message_id", ""),
                "threadId": result.get("thread_id", thread_id or ""),
            },
        }

    def send_draft(self, gmail_draft_id: str) -> dict[str, Any]:
        # The FastAPI send-draft route requires explicit confirmation first.
        result = self._call("send_draft", {"draft_id": gmail_draft_id, "confirmed": True})
        return {"id": result.get("id", ""), "threadId": result.get("threadId", "")}

    def delete_draft(self, gmail_draft_id: str) -> dict[str, Any]:
        return self._call("delete_draft", {"draft_id": gmail_draft_id, "confirmed": True})

    def send_message(
        self,
        to_addresses: list[str],
        cc_addresses: list[str],
        bcc_addresses: list[str],
        subject: str,
        body_text: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        result = self._call("send_message", {
            "to_addresses": to_addresses,
            "cc_addresses": cc_addresses,
            "bcc_addresses": bcc_addresses,
            "subject": subject,
            "body_text": body_text,
            "thread_id": thread_id,
            "confirmed": True,
        })
        return {"id": result.get("id", ""), "threadId": result.get("threadId", "")}

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        result = self._call("get_attachment", {"message_id": message_id, "attachment_id": attachment_id})
        encoded = result.get("data_base64", "")
        return base64.b64decode(encoded) if encoded else b""

    def list_calendar_events(self, time_min: str, time_max: str, max_results: int = 20) -> list[dict[str, Any]]:
        result = self._call("list_calendar_events", {
            "time_min": time_min,
            "time_max": time_max,
            "max_results": max(1, min(int(max_results), 50)),
        })
        return result if isinstance(result, list) else []

    def create_calendar_event(
        self,
        summary: str,
        description: str,
        start: str,
        end: str,
        timezone_name: str,
        attendees: list[str],
    ) -> dict[str, Any]:
        # Calendar invitations are suppressed in Apps Script. The local API request is the user action.
        return self._call("create_calendar_event", {
            "summary": summary,
            "description": description,
            "start": start,
            "end": end,
            "attendees": attendees,
            "confirmed": True,
        })
