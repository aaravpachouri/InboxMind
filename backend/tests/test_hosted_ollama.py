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
    assert "no result was fabricated" in str(error.value.detail).lower()


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



def test_gemini_key_selects_gemini_provider(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "https://ollama.example")
    assert hosted_ollama.active_provider() == "gemini"


def test_missing_gemini_key_keeps_ollama_provider(monkeypatch):
    monkeypatch.setattr(hosted_ollama, "GEMINI_API_KEY", "")
    monkeypatch.setattr(hosted_ollama, "OLLAMA_BASE_URL", "https://ollama.example")
    assert hosted_ollama.active_provider() == "ollama"


def test_generate_routes_to_gemini_when_key_is_configured(monkeypatch):
    calls = {}

    async def fake_gemini(messages, *, temperature, json_output, timeout_seconds):
        calls["messages"] = messages
        calls["json_output"] = json_output
        return {"content": '{"summary":"ok"}', "provider": "gemini", "model": "gemini-test"}

    monkeypatch.setattr(hosted_ollama, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(hosted_ollama, "GEMINI_MODEL", "gemini-test")
    monkeypatch.setattr(hosted_ollama, "_generate_gemini", fake_gemini)

    result = asyncio.run(hosted_ollama.generate(
        [{"role": "system", "content": "Be safe."}, {"role": "user", "content": "Summarize this."}],
        json_output=True,
    ))

    assert result["provider"] == "gemini"
    assert result["model"] == "gemini-test"
    assert calls["json_output"] is True
    assert len(calls["messages"]) == 2


def test_gemini_model_status_is_selected_when_key_exists(monkeypatch):
    async def fake_status():
        return {"available": True, "provider": "gemini", "model": "gemini-test", "detail": "ready"}

    monkeypatch.setattr(hosted_ollama, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(hosted_ollama, "_gemini_model_status", fake_status)
    status = asyncio.run(hosted_ollama.model_status())

    assert status["available"] is True
    assert status["provider"] == "gemini"



def test_gemini_hosted_job_does_not_require_private_worker(monkeypatch):
    from gmail_agent import public_app

    async def fake_generate(messages, *, temperature=0.2, json_output=False, timeout_seconds=None):
        return {"content": "Gemini response", "provider": "gemini", "model": "gemini-test"}

    monkeypatch.setattr(hosted_ollama, "AI_BACKEND_MODE", "private_worker")
    monkeypatch.setattr(hosted_ollama, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(hosted_ollama, "generate", fake_generate)
    monkeypatch.setattr(public_app, "_require_ai_enabled", lambda _user_id: None)

    def fail_if_worker_used(_user_id):
        raise AssertionError("Gemini inference must not require the private Windows worker")

    monkeypatch.setattr(public_app, "_require_online_ai_worker", fail_if_worker_used)
    result = asyncio.run(public_app._run_local_ai_job(
        "tenant-a",
        "summarize_email",
        [{"role": "user", "content": "Summarize this email."}],
    ))

    assert result["content"] == "Gemini response"
    assert result["provider"] == "gemini"



def test_hosted_chat_returns_the_actual_gemini_provider(monkeypatch):
    from gmail_agent import public_app

    async def fake_generate(user_id, job_type, messages, temperature=0.2, timeout_seconds=90):
        return {"content": "Verified Gemini answer", "provider": "gemini", "model": "gemini-test"}

    monkeypatch.setattr(public_app, "_current_user", lambda _session: {"id": "tenant-a"})
    monkeypatch.setattr(public_app, "_require_csrf", lambda _request, _user: None)
    monkeypatch.setattr(public_app, "_run_local_ai_job", fake_generate)
    monkeypatch.setattr(hosted_ollama, "active_provider", lambda: "gemini")

    result = asyncio.run(public_app.chat_unavailable(
        {"message": "What needs attention?", "include_recent_emails": False},
        None,
        None,
    ))

    assert result["answer"] == "Verified Gemini answer"
    assert result["ai_provider"] == "gemini"
