from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from gmail_agent import hosted_ollama


def test_hosted_mode_fails_closed_when_endpoint_is_not_configured(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "")
    with pytest.raises(HTTPException) as error:
        asyncio.run(hosted_ollama.generate([{"role": "user", "content": "hello"}]))
    assert error.value.status_code == 503
    assert "no result was fabricated" in str(error.value.detail)


def test_hosted_status_reports_missing_configuration(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "")
    status = asyncio.run(hosted_ollama.model_status())
    assert status["available"] is False
    assert status["provider"] == "ollama"
    assert "OLLAMA_BASE_URL" in status["detail"]


def test_generate_rejects_invalid_roles_before_network(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "https://ollama.example")
    with pytest.raises(HTTPException) as error:
        asyncio.run(hosted_ollama.generate([{"role": "tool", "content": "hello"}]))
    assert error.value.status_code == 422


def test_generate_rejects_oversized_prompt_before_network(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "https://ollama.example")
    with pytest.raises(HTTPException) as error:
        asyncio.run(hosted_ollama.generate([{"role": "user", "content": "x" * 100001}]))
    assert error.value.status_code == 413


def test_hosted_ollama_requires_tls_for_non_loopback_endpoints(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "AI_BACKEND_MODE", "hosted")
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "http://ollama.example")
    with pytest.raises(RuntimeError, match="HTTPS"):
        hosted_ollama.validate_configuration()



def test_public_ai_job_routes_to_hosted_ollama_without_private_worker(monkeypatch):
    from gmail_agent import public_app

    calls = {}

    async def fake_generate(messages, *, temperature=0.2, json_output=False, timeout_seconds=None):
        calls["messages"] = messages
        calls["temperature"] = temperature
        calls["json_output"] = json_output
        calls["timeout_seconds"] = timeout_seconds
        return {"content": "verified response", "provider": "ollama", "model": "llama3.2:3b"}

    monkeypatch.setattr(hosted_ollama, "AI_BACKEND_MODE", "hosted")
    monkeypatch.setattr(hosted_ollama, "generate", fake_generate)
    monkeypatch.setattr(public_app, "_require_ai_enabled", lambda _user_id: None)

    def fail_if_worker_used(_user_id):
        raise AssertionError("hosted mode must not require a personal Windows worker")

    monkeypatch.setattr(public_app, "_require_online_ai_worker", fail_if_worker_used)
    result = asyncio.run(public_app._run_local_ai_job(
        "tenant-a",
        "analyze_email",
        [{"role": "user", "content": "summarize safely"}],
        timeout_seconds=47,
    ))

    assert result["content"] == "verified response"
    assert result["provider"] == "ollama"
    assert calls["json_output"] is True
    assert calls["timeout_seconds"] == 47
