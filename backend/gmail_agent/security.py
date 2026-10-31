from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class SecretStore:
    """Encrypts OAuth token JSON at rest. The per-install key is stored with restrictive permissions."""

    def __init__(self, data_dir: Path, env_key: str | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.token_path = self.data_dir / "google_token.enc"
        self.key_path = self.data_dir / ".token_encryption_key"
        self._fernet = Fernet(self._resolve_key(env_key))

    def _resolve_key(self, env_key: str | None) -> bytes:
        if env_key:
            candidate = env_key.encode("ascii")
            try:
                Fernet(candidate)
                return candidate
            except Exception as exc:
                raise ValueError("APP_ENCRYPTION_KEY must be a valid Fernet key") from exc
        if self.key_path.exists():
            key = self.key_path.read_bytes().strip()
            Fernet(key)  # validate
            return key
        key = Fernet.generate_key()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(self.key_path, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key + b"\n")
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    def save_json(self, value: dict[str, Any]) -> None:
        import json

        encrypted = self._fernet.encrypt(json.dumps(value, separators=(",", ":")).encode("utf-8"))
        fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encrypted)
        try:
            os.chmod(self.token_path, 0o600)
        except OSError:
            pass

    def load_json(self) -> dict[str, Any] | None:
        import json

        if not self.token_path.exists():
            return None
        try:
            raw = self._fernet.decrypt(self.token_path.read_bytes())
            result = json.loads(raw.decode("utf-8"))
            return result if isinstance(result, dict) else None
        except (InvalidToken, ValueError, OSError, json.JSONDecodeError):
            return None

    def delete(self) -> None:
        try:
            self.token_path.unlink(missing_ok=True)
        finally:
            # Keep the key to avoid invalidating other locally encrypted installation data.
            pass


def constant_time_equals(left: str, right: str) -> bool:
    return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
