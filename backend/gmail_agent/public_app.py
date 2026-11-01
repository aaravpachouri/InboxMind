from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from urllib.parse import urlencode

import httpx
import psycopg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Cookie, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
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
        raise HTTPException(503, "APP_ENCRYPTION_KEY is not configured; Apps Script bridge secrets cannot be stored safely.")
    try:
        return Fernet(APP_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError):
        raise HTTPException(503, "APP_ENCRYPTION_KEY must be a valid Fernet key to encrypt Apps Script bridge secrets.") from None


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


@app.get("/health")
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
    response = RedirectResponse(FRONTEND_URL + "/?signed_in=1", status_code=302)
    response.set_cookie(SESSION_COOKIE, session_token, httponly=True, secure=True, samesite="lax",
                        max_age=int(SESSION_TTL.total_seconds()), path="/")
    response.set_cookie("inboxmind_csrf", csrf, httponly=False, secure=True, samesite="lax",
                        max_age=int(SESSION_TTL.total_seconds()), path="/")
    return response


@app.get("/api/v1/auth/status")
async def auth_status(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict[str, Any]:
    if not session:
        return {"connected": False, "email": None, "message": "Sign in to connect your personal Apps Script bridge."}
    try:
        user = _current_user(session)
    except HTTPException as exc:
        if exc.status_code == 401:
            return {"connected": False, "email": None, "message": "Session expired. Sign in again."}
        raise
    try:
        bridge = _get_user_bridge(user)
    except HTTPException as exc:
        if exc.status_code == 409:
            return {"connected": False, "email": None, "message": "Signed in. Connect your personal Apps Script bridge to access Gmail."}
        raise
    profile = await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], "profile")
    email = str(profile.get("email", "")).strip().lower() if isinstance(profile, dict) else ""
    if email != str(bridge["google_account_email"]).lower():
        raise HTTPException(502, "Apps Script mailbox identity changed. Reconnect the bridge.")
    return {"connected": True, "email": email, "message": "Gmail connected through your personal Apps Script deployment."}


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


class BridgeConnectRequest(BaseModel):
    bridge_url: str = Field(min_length=1, max_length=500)
    bridge_secret: str = Field(min_length=32, max_length=500)


def _validate_bridge_url(value: str) -> str:
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.hostname != "script.google.com"
            or not parsed.path.startswith("/macros/s/") or not parsed.path.endswith("/exec")
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise HTTPException(422, "Use the HTTPS Apps Script web-app /exec URL from your own deployment.")
    return value


async def _bridge_request(url: str, secret: str, action: str, params: dict[str, Any] | None = None) -> Any:
    try:
        async with httpx.AsyncClient(timeout=35, follow_redirects=True) as client:
            response = await client.post(url, json={"secret": secret, "action": action, "params": params or {}})
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Apps Script bridge could not be reached. Check the deployment URL and access settings.") from None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        error = payload.get("error", "Bridge returned an invalid response.") if isinstance(payload, dict) else "Bridge returned an invalid response."
        raise HTTPException(502, str(error)[:250])
    return payload.get("result")


def _get_user_bridge(user: dict[str, Any]) -> dict[str, Any]:
    pool = _pool_or_503()
    # RLS context is transaction-local (set_config(..., true)); keep it and
    # the protected query inside the same transaction.
    with pool.connection() as conn, conn.transaction():
        _set_user_context(conn, str(user["id"]))
        row = conn.execute(
            """SELECT id, google_account_email, bridge_url, bridge_secret_ciphertext
               FROM user_apps_script_bridges
               WHERE user_id=%s AND revoked_at IS NULL
               ORDER BY updated_at DESC LIMIT 1""",
            (user["id"],),
        ).fetchone()
    if not row:
        raise HTTPException(409, "Connect your personal Apps Script bridge first.")
    try:
        secret = _fernet().decrypt(bytes(row["bridge_secret_ciphertext"])).decode()
    except (InvalidToken, ValueError):
        raise HTTPException(503, "Saved Apps Script bridge credentials could not be decrypted.") from None
    return {**row, "bridge_secret": secret}


@app.post("/api/v1/apps-script/connect")
async def connect_apps_script_bridge(
    body: BridgeConnectRequest,
    request: Request,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    _require_csrf(request, user)
    bridge_url = _validate_bridge_url(body.bridge_url.strip())
    profile = await _bridge_request(bridge_url, body.bridge_secret, "profile")
    email = str(profile.get("email", "")).strip().lower() if isinstance(profile, dict) else ""
    if not email:
        raise HTTPException(502, "Bridge did not return a verified Gmail profile.")
    pool = _pool_or_503()
    encrypted_secret = _fernet().encrypt(body.bridge_secret.encode())
    with pool.connection() as conn, conn.transaction():
        _set_user_context(conn, str(user["id"]))
        conn.execute(
            """INSERT INTO user_apps_script_bridges
                 (user_id, google_account_email, bridge_url, bridge_secret_ciphertext, updated_at, revoked_at)
               VALUES (%s,%s,%s,%s,now(),NULL)
               ON CONFLICT(user_id, google_account_email) DO UPDATE SET
                 bridge_url=EXCLUDED.bridge_url,
                 bridge_secret_ciphertext=EXCLUDED.bridge_secret_ciphertext,
                 updated_at=now(), revoked_at=NULL""",
            (user["id"], email, bridge_url, encrypted_secret),
        )
    return {"connected": True, "email": email, "message": "Personal Apps Script bridge connected."}


@app.get("/api/v1/apps-script/status")
async def apps_script_status(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    try:
        bridge = _get_user_bridge(user)
    except HTTPException as exc:
        if exc.status_code == 409:
            return {"connected": False, "email": None, "message": str(exc.detail)}
        raise
    profile = await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], "profile")
    email = str(profile.get("email", "")).strip().lower() if isinstance(profile, dict) else ""
    if email != str(bridge["google_account_email"]).lower():
        raise HTTPException(502, "Apps Script mailbox identity changed. Reconnect the bridge.")
    return {"connected": True, "email": email, "message": "Gmail connected through your Apps Script deployment."}


@app.post("/api/v1/apps-script/revoke")
def revoke_apps_script_bridge(
    request: Request,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, bool]:
    user = _current_user(session)
    _require_csrf(request, user)
    pool = _pool_or_503()
    with pool.connection() as conn, conn.transaction():
        _set_user_context(conn, str(user["id"]))
        conn.execute(
            "UPDATE user_apps_script_bridges SET revoked_at=now(), updated_at=now() WHERE user_id=%s AND revoked_at IS NULL",
            (user["id"],),
        )
    return {"ok": True}


@app.get("/api/v1/emails")
@app.get("/api/v1/gmail/emails")
async def list_emails(
    limit: int = Query(default=25, ge=1, le=100),
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    bridge = _get_user_bridge(user)
    result = await _bridge_request(
        bridge["bridge_url"], bridge["bridge_secret"], "list_emails",
        {"max_results": min(limit, 10), "query": "in:inbox", "page_token": "0"},
    )
    if not isinstance(result, dict) or not isinstance(result.get("items", []), list):
        raise HTTPException(502, "Apps Script bridge returned an invalid email page.")
    return {
        "items": result.get("items", []),
        "total": result.get("total_estimate", len(result.get("items", []))),
        "total_estimate": result.get("total_estimate", len(result.get("items", []))),
        "next_page_token": result.get("next_page_token"),
        "source": "apps_script",
        "account_email": bridge["google_account_email"],
    }


class EmailActionRequest(BaseModel):
    confirmed: bool = False


class LabelModifyRequest(BaseModel):
    add_labels: list[str] = Field(default_factory=list)
    remove_labels: list[str] = Field(default_factory=list)


class CreateLabelRequest(BaseModel):
    name: str = Field(min_length=1, max_length=225)


@app.get("/api/v1/emails/{message_id}")
async def get_email(
    message_id: str,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    bridge = _get_user_bridge(user)
    result = await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], "get_email", {"message_id": message_id})
    if not isinstance(result, dict):
        raise HTTPException(502, "Apps Script bridge returned an invalid email.")
    return result


@app.get("/api/v1/emails/{message_id}/thread")
async def get_email_thread(
    message_id: str,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    bridge = _get_user_bridge(user)
    email = await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], "get_email", {"message_id": message_id})
    thread_id = email.get("thread_id") or email.get("threadId") if isinstance(email, dict) else None
    if not thread_id:
        raise HTTPException(502, "Email did not contain a thread identifier.")
    result = await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], "get_thread", {"thread_id": thread_id})
    return {"items": result if isinstance(result, list) else []}


@app.get("/api/v1/labels")
async def list_labels(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict[str, Any]:
    user = _current_user(session)
    bridge = _get_user_bridge(user)
    result = await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], "list_labels")
    return {"items": result if isinstance(result, list) else []}


@app.post("/api/v1/labels")
async def create_label(
    body: CreateLabelRequest,
    request: Request,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    _require_csrf(request, user)
    bridge = _get_user_bridge(user)
    return await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], "create_label", {"name": body.name.strip()})


@app.post("/api/v1/emails/{message_id}/labels")
async def modify_email_labels(
    message_id: str,
    body: LabelModifyRequest,
    request: Request,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    _require_csrf(request, user)
    bridge = _get_user_bridge(user)
    return await _bridge_request(
        bridge["bridge_url"], bridge["bridge_secret"], "modify_labels",
        {"message_id": message_id, "add_labels": body.add_labels, "remove_labels": body.remove_labels},
    )


async def _email_action(
    message_id: str, action: str, confirmed: bool = False,
    session: str | None = None,
) -> dict[str, Any]:
    user = _current_user(session)
    bridge = _get_user_bridge(user)
    params: dict[str, Any] = {"message_id": message_id}
    if action == "trash":
        if not confirmed:
            raise HTTPException(400, "Confirm moving this email to Trash before continuing.")
        params["confirmed"] = True
    result = await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], action, params)
    return result if isinstance(result, dict) else {"ok": True, "result": result}


@app.post("/api/v1/emails/{message_id}/archive")
async def archive_email(
    message_id: str, request: Request,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    _require_csrf(request, user)
    bridge = _get_user_bridge(user)
    result = await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], "archive", {"message_id": message_id})
    return result if isinstance(result, dict) else {"ok": True}


@app.post("/api/v1/emails/{message_id}/trash")
async def trash_email(
    message_id: str, body: EmailActionRequest, request: Request,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    _require_csrf(request, user)
    if not body.confirmed:
        raise HTTPException(400, "Confirm moving this email to Trash before continuing.")
    bridge = _get_user_bridge(user)
    result = await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], "trash", {"message_id": message_id, "confirmed": True})
    return result if isinstance(result, dict) else {"ok": True}


@app.post("/api/v1/emails/{message_id}/mark-read")
async def mark_email_read(
    message_id: str, request: Request,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    _require_csrf(request, user)
    bridge = _get_user_bridge(user)
    result = await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], "mark_read", {"message_id": message_id})
    return result if isinstance(result, dict) else {"ok": True}


@app.post("/api/v1/emails/{message_id}/mark-unread")
async def mark_email_unread(
    message_id: str, request: Request,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    _require_csrf(request, user)
    bridge = _get_user_bridge(user)
    result = await _bridge_request(bridge["bridge_url"], bridge["bridge_secret"], "mark_unread", {"message_id": message_id})
    return result if isinstance(result, dict) else {"ok": True}


@app.get("/api/v1/calendar/events")
async def list_calendar_events(
    days: int = Query(default=14, ge=1, le=90),
    limit: int = Query(default=30, ge=1, le=50),
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    bridge = _get_user_bridge(user)
    now = datetime.now(timezone.utc)
    result = await _bridge_request(
        bridge["bridge_url"], bridge["bridge_secret"], "list_calendar_events",
        {"time_min": now.isoformat(), "time_max": (now + timedelta(days=days)).isoformat(), "max_results": limit},
    )
    return {"items": result if isinstance(result, list) else []}


@app.post("/api/v1/calendar/events")
async def create_calendar_event(
    body: dict[str, Any], request: Request,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    user = _current_user(session)
    _require_csrf(request, user)
    if not body.get("summary") or not body.get("start") or not body.get("end"):
        raise HTTPException(422, "Event summary, start and end are required.")
    bridge = _get_user_bridge(user)
    result = await _bridge_request(
        bridge["bridge_url"], bridge["bridge_secret"], "create_calendar_event",
        {"summary": str(body["summary"])[:250], "description": str(body.get("description", ""))[:5000],
         "start": body["start"], "end": body["end"], "attendees": body.get("attendees", []), "confirmed": True},
    )
    return result if isinstance(result, dict) else {"ok": True, "result": result}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "InboxMind Secure API", "health": "/api/v1/health", "docs": "/docs"}
