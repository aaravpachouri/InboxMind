"""Transactional email delivery for InboxMind account verification and recovery.

Uses Resend's HTTP API only when explicitly configured. No credentials are embedded,
and callers must fail closed when delivery is unavailable.
"""
from __future__ import annotations

import html
import os
from urllib.parse import urlencode

import httpx

RESEND_API_URL = "https://api.resend.com/emails"


class AuthEmailDeliveryError(RuntimeError):
    """Raised when an account-security email cannot be delivered."""


def _auth_email_config() -> tuple[str, str, str]:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("INBOXMIND_AUTH_EMAIL_FROM", "").strip()
    frontend_url = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
    if not api_key or not sender or not frontend_url:
        raise AuthEmailDeliveryError(
            "Account email delivery is not configured. Set RESEND_API_KEY, "
            "INBOXMIND_AUTH_EMAIL_FROM and FRONTEND_URL."
        )
    if not frontend_url.startswith("https://"):
        raise AuthEmailDeliveryError("FRONTEND_URL must use HTTPS for account-security links.")
    return api_key, sender, frontend_url


async def send_account_action_email(
    recipient: str,
    *,
    purpose: str,
    token: str,
) -> None:
    """Send a verification or password-reset link; never log or persist the raw token."""
    if purpose not in {"verify-email", "reset-password"}:
        raise ValueError("Unsupported account email purpose.")
    if not recipient or len(recipient) > 320 or "@" not in recipient:
        raise ValueError("A valid recipient email address is required.")
    if not token or len(token) > 256:
        raise ValueError("A valid one-time token is required.")

    api_key, sender, frontend_url = _auth_email_config()
    action = "verify" if purpose == "verify-email" else "reset"
    subject = "Verify your InboxMind email" if action == "verify" else "Reset your InboxMind password"
    path = "/auth/verify-email" if action == "verify" else "/auth/reset-password"
    link = frontend_url + path + "?" + urlencode({"token": token})
    safe_link = html.escape(link, quote=True)
    safe_purpose = "verify your email address" if action == "verify" else "choose a new password"
    text_body = (
        f"Use this one-time link to {safe_purpose}:\n{link}\n\n"
        "If you did not request this, you can ignore this email. "
        "The link expires automatically and can only be used once."
    )
    html_body = (
        "<p>Use the link below to " + safe_purpose + " for InboxMind.</p>"
        '<p><a href="' + safe_link + '">Continue to InboxMind</a></p>'
        "<p>If you did not request this, ignore this email. The link expires automatically "
        "and can only be used once.</p>"
    )
    payload = {
        "from": sender,
        "to": [recipient],
        "subject": subject,
        "text": text_body,
        "html": html_body,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                RESEND_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        raise AuthEmailDeliveryError("InboxMind could not deliver the account-security email.") from None
