from __future__ import annotations

import pytest

from gmail_agent.config import Settings
from gmail_agent.main import create_app


def test_production_app_fails_closed_until_multi_tenant_isolation_is_enabled() -> None:
    """Never allow the current shared single-user backend to start as a public service."""
    with pytest.raises(RuntimeError, match="multi-tenant authentication and data-isolation"):
        create_app(Settings(app_env="production"), start_worker=False)
