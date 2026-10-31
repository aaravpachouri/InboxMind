from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import psycopg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Cookie, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
APP_ENCRYPTION_KEY = os.getenv("APP_ENCRYPTION_KEY", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://inboxmind-aaravpachouri.vercel.app").rstrip("/")
ALLOWED_ORIGINS = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", FRONTEND_URL).split(",") if x.strip()]
SESSION_COOKIE = "__Host-inboxmind_session"
SESSION_TTL = timedelta(days=7)
SCOPES = [
    "openid", "email", "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
app = FastAPI(title="InboxMind Secure API", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "X-CSRF-Token"],
)
_pool: ConnectionPool | None = None


def _pool_or_503() -> ConnectionPool:
    global _pool
    if not DATABASE_URL:
        raise HTTPException(503, "DATABASE_URL is not configured.")
    if _pool is None:
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=True)
    return _pool


def _fernet() -> Fernet:
    if not APP_ENCRYPTION_KEY:
        raise HTTPException(503, "APP_ENCRYPTION_KEY is not configured; Gmail credentials are not available.")
    try:
        return Fernet(APP_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError):
        raise HTTPException(503, "APP_ENCRYPTION_KEY must be a valid Fernet key.") from None


def _hash(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def _check_oauth_config() -> None:
    if not all((GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI)):
        raise HTTPException(503, "Google OAuth is not configured on the backend yet.")


def _set_user_context(conn: psycopg.Connection, user_id: str) -> None:
    conn.execute("SELECT set_config('app.current_user_id', %s, true)", (user_id,))


def _current_user(session_cookie: str | None) -> dict[str, Any]:
    if not session_cookie:
        raise HTTPException(401, "Sign in with Google to continue.")
    pool = _pool_or_503()
    with pool.connection() as conn:
        row = conn.execute(
            """SELECT u.id, u.google_sub, u.email, u.display_name, u.picture_url, s.id AS session_id,
                      encode(s.csrf_token_hash, 'hex') AS csrf_hash
               FROM user_sessions s JOIN app_users u ON u.id=s.user_id
               WHERE s.session_token_hash=%s AND s.revoked_at IS NULL AND s.expires_at > now()""",
            (_hash(session_cookie),),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Session expired. Sign in again.")
    return row


def _require_csrf(request: Request, user: dict[str, Any]) -> None:
    token = request.headers.get("X-CSRF-Token", "")
    if not token or not secrets.compare_digest(_hash(token).hex(), user["csrf_hash"]):
        raise HTTPException(403, "CSRF validation failed. Refresh the page and retry.")


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    pool = _pool_or_503()
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "service": "inboxmind-secure-api"}


@app.get("/api/v1/auth/google/login")
def google_login() -> RedirectResponse:
    _check_oauth_config()
    state = secrets.token_urlsafe(32)
    pool = _pool_or_503()
    with pool.connection() as conn, conn.transaction():
        conn.execute(
            """INSERT INTO oauth_transactions(state_hash, purpose, expires_at)
               VALUES (%s, 'login', %s)""",
            (_hash(state), datetime.now(timezone.utc) + timedelta(minutes=10)),
        )
    params = {
        "client_id": GOOGLE_CLIENT_ID, "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code", "scope": " ".join(SCOPES), "state": state,
        "access_type": "offline", "prompt": "select_account consent",
        "include_granted_scopes": "true",
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params), status_code=302)


@app.get("/api/v1/auth/google/callback")
async def google_callback(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    if error:
        return RedirectResponse(FRONTEND_URL + "/?auth_error=google_denied", status_code=302)
    _check_oauth_config()
    if not code or not state:
        raise HTTPException(400, "Missing OAuth callback parameters.")
    pool = _pool_or_503()
    with pool.connection() as conn, conn.transaction():
        tx = conn.execute(
            """UPDATE oauth_transactions SET consumed_at=now()
               WHERE state_hash=%s AND purpose='login' AND consumed_at IS NULL AND expires_at > now()
               RETURNING id""", (_hash(state),),
        ).fetchone()
    if not tx:
        raise HTTPException(400, "OAuth state expired or already used. Start sign-in again.")
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={"code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
                  "redirect_uri": GOOGLE_REDIRECT_URI, "grant_type": "authorization_code"},
        )
    if token_response.status_code != 200:
        raise HTTPException(502, "Google token exchange failed. Check OAuth redirect configuration.")
    tokens = token_response.json()
    try:
        claims = id_token.verify_oauth2_token(tokens["id_token"], GoogleRequest(), GOOGLE_CLIENT_ID)
    except Exception:
        raise HTTPException(401, "Google identity token could not be verified.") from None
    if not claims.get("email") or claims.get("email_verified") is not True or not claims.get("sub"):
        raise HTTPException(403, "A verified Google email is required.")
    if not tokens.get("refresh_token"):
        raise HTTPException(502, "Google did not return a refresh token. Revoke InboxMind access in Google Account settings and sign in again.")
    cipher = _fernet()
    refresh_ciphertext = cipher.encrypt(tokens["refresh_token"].encode())
    access_ciphertext = cipher.encrypt(tokens["access_token"].encode()) if tokens.get("access_token") else None
    csrf = secrets.token_urlsafe(32)
    session_token = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + SESSION_TTL
    with pool.connection() as conn, conn.transaction():
        user = conn.execute(
            """INSERT INTO app_users(google_sub,email,email_verified,display_name,picture_url)
               VALUES (%s,%s,true,%s,%s)
               ON CONFLICT(google_sub) DO UPDATE SET email=EXCLUDED.email,email_verified=true,
                 display_name=EXCLUDED.display_name,picture_url=EXCLUDED.picture_url,updated_at=now()
               RETURNING id""",
            (claims["sub"], claims["email"], claims.get("name", ""), claims.get("picture", "")),
        ).fetchone()
        conn.execute(
            """INSERT INTO user_sessions(user_id,session_token_hash,csrf_token_hash,expires_at)
               VALUES (%s,%s,%s,%s)""", (user["id"], _hash(session_token), _hash(csrf), expires),
        )
        _set_user_context(conn, str(user["id"]))
        conn.execute(
            """INSERT INTO gmail_accounts(user_id,google_account_sub,email,granted_scopes,
                      refresh_token_ciphertext,access_token_ciphertext,access_token_expires_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(user_id,google_account_sub) DO UPDATE SET
                 email=EXCLUDED.email,granted_scopes=EXCLUDED.granted_scopes,
                 refresh_token_ciphertext=EXCLUDED.refresh_token_ciphertext,
                 access_token_ciphertext=EXCLUDED.access_token_ciphertext,
                 access_token_expires_at=EXCLUDED.access_token_expires_at,revoked_at=NULL""",
            (user["id"], claims["sub"], claims["email"], tokens.get("scope", "").split(),
             refresh_ciphertext, access_ciphertext,
             datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600)))),
        )
    response = RedirectResponse(FRONTEND_URL + "/?signed_in=1", status_code=302)
    response.set_cookie(SESSION_COOKIE, session_token, httponly=True, secure=True, samesite="lax",
                        max_age=int(SESSION_TTL.total_seconds()), path="/")
    response.set_cookie("inboxmind_csrf", csrf, httponly=False, secure=True, samesite="lax",
                        max_age=int(SESSION_TTL.total_seconds()), path="/")
    return response


@app.get("/api/v1/auth/me")
def auth_me(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict[str, Any]:
    user = _current_user(session)
    return {"authenticated": True, "email": user["email"], "display_name": user["display_name"],
            "picture_url": user["picture_url"]}


@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response,
           session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict[str, bool]:
    user = _current_user(session)
    _require_csrf(request, user)
    pool = _pool_or_503()
    with pool.connection() as conn, conn.transaction():
        conn.execute("UPDATE user_sessions SET revoked_at=now() WHERE id=%s", (user["session_id"],))
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    response.delete_cookie("inboxmind_csrf", path="/", secure=True, httponly=False, samesite="lax")
    return {"ok": True}


@app.get("/api/v1/gmail/emails")
def list_emails(limit: int = Query(default=25, ge=1, le=100),
                session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict[str, Any]:
    user = _current_user(session)
    pool = _pool_or_503()
    with pool.connection() as conn:
        _set_user_context(conn, str(user["id"]))
        account = conn.execute(
            """SELECT id,email,refresh_token_ciphertext,access_token_ciphertext,access_token_expires_at
               FROM gmail_accounts WHERE user_id=%s AND revoked_at IS NULL ORDER BY connected_at DESC LIMIT 1""",
            (user["id"],),
        ).fetchone()
    if not account:
        raise HTTPException(409, "Connect your Gmail account first.")
    cipher = _fernet()
    try:
        refresh = cipher.decrypt(bytes(account["refresh_token_ciphertext"])).decode()
        access = cipher.decrypt(bytes(account["access_token_ciphertext"])).decode() if account["access_token_ciphertext"] else None
    except (InvalidToken, ValueError):
        raise HTTPException(503, "Stored Gmail credentials could not be decrypted; contact support.") from None
    creds = Credentials(token=access, refresh_token=refresh, token_uri="https://oauth2.googleapis.com/token",
                        client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET, scopes=SCOPES)
    try:
        if not creds.valid:
            creds.refresh(GoogleRequest())
            with pool.connection() as conn, conn.transaction():
                _set_user_context(conn, str(user["id"]))
                conn.execute("""UPDATE gmail_accounts SET access_token_ciphertext=%s,
                              access_token_expires_at=%s WHERE user_id=%s AND id=%s""",
                             (cipher.encrypt(creds.token.encode()), creds.expiry, user["id"], account["id"]))
        gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
        result = gmail.users().messages().list(userId="me", maxResults=limit, labelIds=["INBOX"]).execute()
        messages = []
        for item in result.get("messages", []):
            msg = gmail.users().messages().get(userId="me", id=item["id"], format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"]).execute()
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            messages.append({"id": msg["id"], "thread_id": msg.get("threadId", ""),
                             "from_address": headers.get("from", ""), "to_addresses": headers.get("to", ""),
                             "subject": headers.get("subject", "(no subject)"), "snippet": msg.get("snippet", ""),
                             "internal_date": msg.get("internalDate", ""),
                             "labels": msg.get("labelIds", []), "is_unread": "UNREAD" in msg.get("labelIds", []),
                             "is_sent": "SENT" in msg.get("labelIds", []),
                             "has_attachments": any(p.get("filename") for p in msg.get("payload", {}).get("parts", []))})
        return {"items": messages, "total": len(messages), "account_email": account["email"]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Gmail request failed ({type(exc).__name__}).") from None


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "InboxMind Secure API", "health": "/api/v1/health", "docs": "/docs"}
