from __future__ import annotations

import base64
import email.utils
import re
from email.header import decode_header, make_header
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from .oauth import GoogleOAuthService


def _decode_base64(data: str | None) -> bytes:
    if not data:
        return b""
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except Exception:
        return b""


def _header_map(headers: list[dict[str, str]] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in headers or []:
        name = item.get("name", "")
        value = item.get("value", "")
        if name:
            # Decode RFC 2047 encoded words so internationalized subjects/names are readable.
            try:
                value = str(make_header(decode_header(value)))
            except (LookupError, UnicodeError, ValueError):
                pass
            # Last value wins for duplicate fields; raw values are still available from Gmail.
            result[name.lower()] = value
    return result


def _collect_parts(payload: dict[str, Any], plain_parts: list[str], html_parts: list[str], attachments: list[dict[str, Any]], message_id: str) -> None:
    filename = payload.get("filename") or ""
    body = payload.get("body") or {}
    if filename:
        attachments.append({
            "attachment_id": body.get("attachmentId", ""),
            "filename": filename,
            "mime_type": payload.get("mimeType", "application/octet-stream"),
            "size": int(body.get("size") or 0),
            "part_id": payload.get("partId", ""),
        })
    elif body.get("data"):
        raw = _decode_base64(body.get("data"))
        charset = "utf-8"
        for header in payload.get("headers", []) or []:
            if str(header.get("name", "")).lower() == "content-type":
                match = re.search(r"charset\s*=\s*[\"']?([^;\"' ]+)", str(header.get("value", "")), re.I)
                if match:
                    charset = match.group(1)
                break
        try:
            text = raw.decode(charset, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        mime = payload.get("mimeType", "")
        if mime == "text/plain":
            plain_parts.append(text)
        elif mime == "text/html":
            html_parts.append(text)
    for part in payload.get("parts") or []:
        _collect_parts(part, plain_parts, html_parts, attachments, message_id)


def html_to_text(html: str) -> str:
    from html import unescape

    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>|</h[1-6]>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def parse_message(message: dict[str, Any]) -> dict[str, Any]:
    payload = message.get("payload") or {}
    headers = _header_map(payload.get("headers"))
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []
    _collect_parts(payload, plain_parts, html_parts, attachments, message.get("id", ""))
    body = "\n\n".join(part.strip() for part in plain_parts if part.strip())
    if not body and html_parts:
        body = "\n\n".join(html_to_text(item) for item in html_parts)
    labels = message.get("labelIds") or []
    try:
        ms = int(message.get("internalDate") or 0)
        date_value = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat() if ms else headers.get("date", "")
    except (OverflowError, OSError, ValueError):
        date_value = headers.get("date", "")
    return {
        "id": message.get("id", ""),
        "thread_id": message.get("threadId", ""),
        "from_address": headers.get("from", ""),
        "to_addresses": headers.get("to", ""),
        "cc_addresses": headers.get("cc", ""),
        "subject": headers.get("subject", "(no subject)"),
        "snippet": message.get("snippet", ""),
        "body_text": body,
        "internal_date": date_value,
        "labels": labels,
        "is_unread": "UNREAD" in labels,
        "is_sent": "SENT" in labels,
        "has_attachments": bool(attachments),
        "attachment_metadata": attachments,
        "raw_headers": headers,
    }


class GmailClient:
    def __init__(self, oauth: GoogleOAuthService):
        self.oauth = oauth

    def _service(self):
        creds = self.oauth.credentials()
        if not creds:
            raise RuntimeError("Gmail is not connected. Complete Google OAuth first.")
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Google API dependencies are missing. Install requirements.txt first.") from exc
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def profile(self) -> dict[str, Any]:
        profile = self._service().users().getProfile(userId="me").execute()
        return {"email": profile.get("emailAddress", ""), "messages_total": profile.get("messagesTotal", 0), "threads_total": profile.get("threadsTotal", 0), "history_id": profile.get("historyId", "")}

    def list_emails(self, query: str = "", max_results: int = 50, page_token: str | None = None) -> dict[str, Any]:
        include_spam_trash = "in:anywhere" in query.lower()
        kwargs: dict[str, Any] = {"userId": "me", "maxResults": max(1, min(max_results, 100)), "includeSpamTrash": include_spam_trash}
        if query.strip():
            kwargs["q"] = query.strip()
        if page_token:
            kwargs["pageToken"] = page_token
        # Build the Google API discovery client once per page, not once per email.
        # Rebuilding it for every message adds noticeable overhead on larger syncs.
        service = self._service()
        result = service.users().messages().list(**kwargs).execute()
        ids = result.get("messages", []) or []
        items = [self._get_email_with_service(service, item["id"]) for item in ids if item.get("id")]
        return {"items": items, "total_estimate": result.get("resultSizeEstimate", len(items)), "next_page_token": result.get("nextPageToken")}

    @staticmethod
    def _get_email_with_service(service, message_id: str) -> dict[str, Any]:
        message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        return parse_message(message)

    def get_email(self, message_id: str) -> dict[str, Any]:
        return self._get_email_with_service(self._service(), message_id)

    def get_thread(self, thread_id: str) -> list[dict[str, Any]]:
        thread = self._service().users().threads().get(userId="me", id=thread_id, format="full").execute()
        return [parse_message(item) for item in thread.get("messages", []) or []]

    def list_labels(self) -> list[dict[str, Any]]:
        result = self._service().users().labels().list(userId="me").execute()
        return result.get("labels", []) or []

    def create_label(self, name: str) -> dict[str, Any]:
        clean = name.strip()
        if not clean or len(clean) > 225:
            raise ValueError("Label name must be 1–225 characters")
        return self._service().users().labels().create(userId="me", body={"name": clean, "labelListVisibility": "labelShow", "messageListVisibility": "show"}).execute()

    def modify_labels(self, message_id: str, add_labels: list[str], remove_labels: list[str]) -> dict[str, Any]:
        return self._service().users().messages().modify(
            userId="me", id=message_id, body={"addLabelIds": add_labels, "removeLabelIds": remove_labels}
        ).execute()

    def archive(self, message_id: str) -> dict[str, Any]:
        return self.modify_labels(message_id, [], ["INBOX"])

    def trash(self, message_id: str) -> dict[str, Any]:
        return self._service().users().messages().trash(userId="me", id=message_id).execute()

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        result = self._service().users().messages().attachments().get(userId="me", messageId=message_id, id=attachment_id).execute()
        return _decode_base64(result.get("data"))

    def create_draft(self, to_addresses: list[str], cc_addresses: list[str], bcc_addresses: list[str], subject: str, body_text: str, thread_id: str | None = None, in_reply_to: str | None = None, references: str | None = None) -> dict[str, Any]:
        import base64 as b64

        message = EmailMessage()
        message["To"] = ", ".join(to_addresses)
        if cc_addresses:
            message["Cc"] = ", ".join(cc_addresses)
        if bcc_addresses:
            message["Bcc"] = ", ".join(bcc_addresses)
        message["Subject"] = subject
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
        if references:
            message["References"] = references
        message.set_content(body_text)
        encoded = b64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        body: dict[str, Any] = {"message": {"raw": encoded}}
        if thread_id:
            body["message"]["threadId"] = thread_id
        return self._service().users().drafts().create(userId="me", body=body).execute()

    def send_draft(self, gmail_draft_id: str) -> dict[str, Any]:
        return self._service().users().drafts().send(userId="me", body={"id": gmail_draft_id}).execute()

    def send_message(self, to_addresses: list[str], cc_addresses: list[str], bcc_addresses: list[str], subject: str, body_text: str, thread_id: str | None = None) -> dict[str, Any]:
        draft = self.create_draft(to_addresses, cc_addresses, bcc_addresses, subject, body_text, thread_id)
        return self.send_draft(draft["id"])

    def mark_read(self, message_id: str) -> dict[str, Any]:
        return self.modify_labels(message_id, [], ["UNREAD"])

    def mark_unread(self, message_id: str) -> dict[str, Any]:
        return self.modify_labels(message_id, ["UNREAD"], [])

    def batch_modify(self, message_ids: list[str], add_labels: list[str], remove_labels: list[str]) -> dict[str, Any]:
        return self._service().users().messages().batchModify(
            userId="me", body={"ids": message_ids, "addLabelIds": add_labels, "removeLabelIds": remove_labels}
        ).execute()

    def create_calendar_event(self, summary: str, description: str, start: str, end: str, timezone_name: str, attendees: list[str]) -> dict[str, Any]:
        creds = self.oauth.credentials()
        if not creds:
            raise RuntimeError("Google is not connected.")
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Google API dependencies are missing.") from exc
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        body: dict[str, Any] = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start, "timeZone": timezone_name},
            "end": {"dateTime": end, "timeZone": timezone_name},
        }
        if attendees:
            body["attendees"] = [{"email": address} for address in attendees]
        return service.events().insert(calendarId="primary", body=body, sendUpdates="none").execute()

    def list_calendar_events(self, time_min: str, time_max: str, max_results: int = 20) -> list[dict[str, Any]]:
        creds = self.oauth.credentials()
        if not creds:
            raise RuntimeError("Google is not connected.")
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Google API dependencies are missing.") from exc
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        data = service.events().list(calendarId="primary", timeMin=time_min, timeMax=time_max, maxResults=max(1, min(max_results, 100)), singleEvents=True, orderBy="startTime").execute()
        return data.get("items", []) or []
