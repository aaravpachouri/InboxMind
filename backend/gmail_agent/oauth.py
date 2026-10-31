from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .security import SecretStore


@dataclass
class PendingOAuthState:
    value: str
    created_at: float


class GoogleOAuthService:
    def __init__(self, settings: Settings, secret_store: SecretStore):
        self.settings = settings
        self.secret_store = secret_store
        self._pending: dict[str, PendingOAuthState] = {}

    def configured(self) -> bool:
        return bool(self.settings.google_client_id and self.settings.google_client_secret)

    def _client_config(self) -> dict[str, Any]:
        return {
            "web": {
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.settings.google_redirect_uri],
            }
        }

    def authorization_url(self) -> str:
        if not self.configured():
            raise RuntimeError("Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env.")
        try:
            from google_auth_oauthlib.flow import Flow
        except ImportError as exc:
            raise RuntimeError("Google OAuth dependencies are missing. Install requirements.txt first.") from exc
        flow = Flow.from_client_config(self._client_config(), scopes=self.settings.google_scopes)
        flow.redirect_uri = self.settings.google_redirect_uri
        state = secrets.token_urlsafe(32)
        url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        self._pending[state] = PendingOAuthState(state, time.time())
        self._prune_pending()
        return url

    def _prune_pending(self) -> None:
        now = time.time()
        self._pending = {key: val for key, val in self._pending.items() if now - val.created_at < 600}

    def exchange_code(self, code: str, state: str) -> dict[str, Any]:
        pending = self._pending.pop(state, None)
        if pending is None or time.time() - pending.created_at >= 600:
            raise ValueError("OAuth state is missing, expired, or already used. Start the connection flow again.")
        try:
            from google_auth_oauthlib.flow import Flow
        except ImportError as exc:
            raise RuntimeError("Google OAuth dependencies are missing. Install requirements.txt first.") from exc
        flow = Flow.from_client_config(self._client_config(), scopes=self.settings.google_scopes, state=state)
        flow.redirect_uri = self.settings.google_redirect_uri
        flow.fetch_token(code=code)
        credentials = flow.credentials
        payload = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": list(credentials.scopes or self.settings.google_scopes),
        }
        if not payload.get("refresh_token"):
            # Do not replace a working refresh token with an access-only token.
            existing = self.secret_store.load_json() or {}
            payload["refresh_token"] = existing.get("refresh_token")
        self.secret_store.save_json(payload)
        return payload

    def credentials(self):
        payload = self.secret_store.load_json()
        if not payload:
            return None
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
        except ImportError:
            return None
        creds = Credentials.from_authorized_user_info(payload, scopes=self.settings.google_scopes)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            updated = {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes or self.settings.google_scopes),
            }
            self.secret_store.save_json(updated)
        return creds

    def disconnect(self) -> None:
        payload = self.secret_store.load_json()
        if payload and payload.get("token"):
            try:
                import httpx

                httpx.post(
                    "https://oauth2.googleapis.com/revoke",
                    data={"token": payload.get("refresh_token") or payload["token"]},
                    timeout=8,
                )
            except Exception:
                pass
        self.secret_store.delete()
