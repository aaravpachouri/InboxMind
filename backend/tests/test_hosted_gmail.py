from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from gmail_agent import hosted_gmail


def test_parse_gmail_message_decodes_subject_and_body():
    import base64
    body = base64.urlsafe_b64encode("Hello InboxMind".encode()).decode().rstrip("=")
    parsed = hosted_gmail.parse_gmail_message({
        "id": "m1", "threadId": "t1", "snippet": "Hello",
        "internalDate": "1790000000000", "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Quarterly update"},
                {"name": "From", "value": "sender@example.com"},
            ],
            "body": {"data": body},
        },
    })
    assert parsed["id"] == "m1"
    assert parsed["thread_id"] == "t1"
    assert parsed["subject"] == "Quarterly update"
    assert parsed["body_text"] == "Hello InboxMind"
    assert parsed["is_unread"] is True
    assert parsed["from_address"] == "sender@example.com"


def test_parse_gmail_message_extracts_attachment_metadata():
    parsed = hosted_gmail.parse_gmail_message({
        "id": "m2",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [],
            "parts": [{
                "filename": "invoice.pdf",
                "mimeType": "application/pdf",
                "body": {"attachmentId": "att1", "size": 512},
            }],
        },
    })
    assert parsed["has_attachments"] is True
    assert parsed["attachment_metadata"][0]["attachment_id"] == "att1"
    assert parsed["attachment_metadata"][0]["filename"] == "invoice.pdf"


def test_tenant_account_lookup_is_scoped_to_user_and_account(monkeypatch):
    connection = MagicMock()
    pool = MagicMock()
    pool.connection.return_value.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = None
    monkeypatch.setattr(hosted_gmail.auth, "_pool_or_503", lambda: pool)
    monkeypatch.setattr(hosted_gmail.auth, "_set_user_context", lambda conn, user: None)
    client = hosted_gmail.HostedGmail("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        client._load_credentials()
    assert exc.value.status_code == 409
    sql = connection.execute.call_args.args[0]
    assert "user_id=%s AND id=%s" in sql
    assert connection.execute.call_args.args[1] == (client.user_id, client.account_id)
