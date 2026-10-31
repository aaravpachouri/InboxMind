from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration. Values may be supplied through the environment or .env."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Gmail AI Agent"
    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"

    data_dir: Path = PROJECT_ROOT / "data"
    database_path: Path = PROJECT_ROOT / "data" / "gmail_agent.sqlite3"
    downloads_dir: Path = PROJECT_ROOT / "data" / "downloads"
    local_files_dir: Path = PROJECT_ROOT / "local_files"

    # Optional Apps Script bridge. When configured, it takes precedence over direct OAuth.
    apps_script_bridge_url: str = ""
    apps_script_bridge_secret: str = ""
    apps_script_bridge_timeout_seconds: float = Field(default=45.0, ge=5.0, le=120.0)

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://127.0.0.1:8000/api/v1/auth/google/callback"
    google_oauth_scopes: str = (
        "https://www.googleapis.com/auth/gmail.modify "
        "https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/calendar.events"
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout_seconds: float = 75.0
    ai_enabled: bool = True
    ai_use_cloud: bool = False  # Cloud models are intentionally not enabled by default.

    auto_sync_enabled: bool = True
    sync_interval_seconds: int = Field(default=300, ge=60, le=86400)
    sync_window_days: int = Field(default=30, ge=1, le=365)
    sync_batch_size: int = Field(default=10, ge=1, le=100)
    max_bulk_action_count: int = Field(default=100, ge=1, le=500)
    max_attachment_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000"

    @field_validator("data_dir", "database_path", "downloads_dir", "local_files_dir", mode="before")
    @classmethod
    def expand_paths(cls, value: object) -> object:
        if isinstance(value, (str, Path)):
            return Path(value).expanduser()
        return value

    @property
    def google_scopes(self) -> list[str]:
        return [scope for scope in self.google_oauth_scopes.split() if scope]

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
