from __future__ import annotations

from typing import Any
from uuid import UUID

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Imported lazily by public_app endpoints after public_app has finished loading.
from . import public_app as auth


class HostedGmail:
    """A Gmail API client bound to one authenticated InboxMind user and Gmail account."""

    def __init__(self, user_id: str, account_id: str):
        self.user_id = str(UUID(str(user_id)))
        self.account_id = str(UUID(str(account_id)))
        self._credentials: Credentials | None = None

    def _load_credentials(self) -> Credentials:
        with auth._pool_or_503().connection() as conn, conn.transaction():
            auth._set_user_context(conn, self.user_id)
            row = conn.execute(
                """SELECT granted_scopes, refresh_token_ciphertext, access_token_ciphertext
                   FROM gmail_accounts
                   WHERE user_id=%s AND id=%s AND revoked_at IS NULL""",
                (self.user_id, self.account_id),
            ).fetchone()
        if not row:
            raise HTTPException(409, "Connect a Gmail account before using the inbox.")
        try:
            refresh_token = auth._fernet().decrypt(bytes(row["refresh_token_ciphertext"])).decode()
            access_token = (
                auth._fernet().decrypt(bytes(row["access_token_ciphertext"])).decode()
                if row.get("access_token_ciphertext") else None
            )
        except (InvalidToken, ValueError, TypeError):
            raise HTTPException(503, "Gmail credentials could not be decrypted safely. Reconnect the account.") from None
        if not auth.GOOGLE_CLIENT_ID or not auth.GOOGLE_CLIENT_SECRET:
            raise HTTPException(503, "Google OAuth client configuration is incomplete.")
        return Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=auth.GOOGLE_CLIENT_ID,
            client_secret=auth.GOOGLE_CLIENT_SECRET,
            scopes=list(row["granted_scopes"] or []),
        )

    def credentials(self) -> Credentials:
        if self._credentials is not None and self._credentials.valid:
            return self._credentials
        creds = self._load_credentials()
        if not creds.valid:
            if not creds.refresh_token:
                raise HTTPException(409, "Gmail authorization expired. Reconnect the account.")
            try:
                creds.refresh(GoogleRequest())
            except Exception:
                raise HTTPException(409, "Google rejected Gmail authorization. Reconnect the account.") from None
            encrypted_access = auth._fernet().encrypt((creds.token or "").encode())
            with auth._pool_or_503().connection() as conn, conn.transaction():
                auth._set_user_context(conn, self.user_id)
                conn.execute(
                    """UPDATE gmail_accounts
                       SET access_token_ciphertext=%s, access_token_expires_at=%s
                       WHERE user_id=%s AND id=%s AND revoked_at IS NULL""",
                    (encrypted_access, creds.expiry, self.user_id, self.account_id),
                )
        self._credentials = creds
        return creds

    def service(self, api: str = "gmail", version: str = "v1"):
        try:
            return build(api, version, credentials=self.credentials(), cache_discovery=False)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, "Google API service could not be initialized.") from None

    def profile(self) -> dict[str, Any]:
        data = self.service().users().getProfile(userId="me").execute()
        return {"email": data.get("emailAddress", ""), "messages_total": data.get("messagesTotal", 0),
                "threads_total": data.get("threadsTotal", 0), "history_id": data.get("historyId", "")}

    def list_emails(self, query: str = "in:inbox", limit: int = 25, page_token: str | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"userId": "me", "maxResults": max(1, min(limit, 100))}
        if query.strip():
            kwargs["q"] = query.strip()
        if page_token:
            kwargs["pageToken"] = page_token
        service = self.service()
        result = service.users().messages().list(**kwargs).execute()
        items = []
        for item in result.get("messages", []) or []:
            message = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
            items.append(parse_gmail_message(message))
        return {"items": items, "total_estimate": result.get("resultSizeEstimate", len(items)),
                "next_page_token": result.get("nextPageToken"), "source": "gmail"}

    def get_email(self, message_id: str) -> dict[str, Any]:
        data = self.service().users().messages().get(userId="me", id=message_id, format="full").execute()
        return parse_gmail_message(data)

    def get_thread(self, thread_id: str) -> list[dict[str, Any]]:
        data = self.service().users().threads().get(userId="me", id=thread_id, format="full").execute()
        return [parse_gmail_message(item) for item in data.get("messages", [])]

    def list_labels(self) -> list[dict[str, Any]]:
        return self.service().users().labels().list(userId="me").execute().get("labels", [])

    def modify_labels(self, message_id: str, add: list[str], remove: list[str]) -> dict[str, Any]:
        return self.service().users().messages().modify(
            userId="me", id=message_id, body={"addLabelIds": add, "removeLabelIds": remove}
        ).execute()

    def archive(self, message_id: str) -> dict[str, Any]:
        return self.modify_labels(message_id, [], ["INBOX"])

    def mark_read(self, message_id: str) -> dict[str, Any]:
        return self.modify_labels(message_id, [], ["UNREAD"])

    def mark_unread(self, message_id: str) -> dict[str, Any]:
        return self.modify_labels(message_id, ["UNREAD"], [])

    def trash(self, message_id: str) -> dict[str, Any]:
        return self.service().users().messages().trash(userId="me", id=message_id).execute()

    def create_label(self, name: str) -> dict[str, Any]:
        return self.service().users().labels().create(userId="me", body={"name": name.strip()}).execute()


def parse_gmail_message(message: dict[str, Any]) -> dict[str, Any]:
    import base64
    import re
    from datetime import datetime, timezone
    from email.header import decode_header, make_header
    from html import unescape

    payload = message.get("payload") or {}
    headers: dict[str, str] = {}
    for item in payload.get("headers", []) or []:
        name = str(item.get("name", "")).lower()
        value = str(item.get("value", ""))
        if name:
            try:
                value = str(make_header(decode_header(value)))
            except (LookupError, UnicodeError, ValueError):
                pass
            headers[name] = value

    plain: list[str] = []
    html: list[str] = []
    attachments: list[dict[str, Any]] = []

    def walk(part: dict[str, Any]) -> None:
        body = part.get("body") or {}
        filename = part.get("filename") or ""
        if filename:
            attachments.append({"attachment_id": body.get("attachmentId", ""), "filename": filename,
                                "mime_type": part.get("mimeType", "application/octet-stream"),
                                "size": int(body.get("size") or 0)})
        elif body.get("data"):
            raw = str(body["data"])
            decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="replace")
            if part.get("mimeType") == "text/plain":
                plain.append(decoded)
            elif part.get("mimeType") == "text/html":
                html.append(decoded)
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    body_text = "\\n\\n".join(x.strip() for x in plain if x.strip())
    if not body_text and html:
        markup = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", "\\n".join(html))
        markup = re.sub(r"(?i)<br\\s*/?>|</p>|</div>|</li>|</tr>", "\\n", markup)
        body_text = re.sub(r"\\s+", " ", unescape(re.sub(r"<[^>]+>", " ", markup))).strip()
    labels = message.get("labelIds") or []
    stamp = int(message.get("internalDate") or 0)
    date_value = datetime.fromtimestamp(stamp / 1000, tz=timezone.utc).isoformat() if stamp else headers.get("date", "")
    return {"id": message.get("id", ""), "thread_id": message.get("threadId", ""),
            "from_address": headers.get("from", ""), "to_addresses": headers.get("to", ""),
            "cc_addresses": headers.get("cc", ""), "subject": headers.get("subject", "(no subject)"),
            "snippet": message.get("snippet", ""), "body_text": body_text, "internal_date": date_value,
            "labels": labels, "is_unread": "UNREAD" in labels, "is_sent": "SENT" in labels,
            "has_attachments": bool(attachments), "attachment_metadata": attachments, "raw_headers": headers}
