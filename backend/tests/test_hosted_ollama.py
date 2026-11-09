from __future__ import annotations

import pytest
from fastapi import HTTPException

from gmail_agent import hosted_ollama


@pytest.mark.asyncio
async def test_hosted_mode_fails_closed_when_endpoint_is_not_configured(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "")
    with pytest.raises(HTTPException) as error:
        await hosted_ollama.generate([{"role": "user", "content": "hello"}])
    assert error.value.status_code == 503
    assert "no result was fabricated" in str(error.value.detail)


@pytest.mark.asyncio
async def test_hosted_status_reports_missing_configuration(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "")
    status = await hosted_ollama.model_status()
    assert status["available"] is False
    assert status["provider"] == "ollama"
    assert "OLLAMA_BASE_URL" in status["detail"]


@pytest.mark.asyncio
async def test_generate_rejects_invalid_roles_before_network(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "https://ollama.example")
    with pytest.raises(HTTPException) as error:
        await hosted_ollama.generate([{"role": "tool", "content": "hello"}])
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_generate_rejects_oversized_prompt_before_network(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "https://ollama.example")
    with pytest.raises(HTTPException) as error:
        await hosted_ollama.generate([{"role": "user", "content": "x" * 100001}])
    assert error.value.status_code == 413


def test_hosted_ollama_requires_tls_for_non_loopback_endpoints(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "AI_BACKEND_MODE", "hosted")
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "http://ollama.example")
    with pytest.raises(RuntimeError, match="HTTPS"):
        hosted_ollama.validate_configuration()
