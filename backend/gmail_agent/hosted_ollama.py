from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip()
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "").strip()
OLLAMA_TIMEOUT_SECONDS = max(10, min(int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")), 600))
OLLAMA_MAX_CONCURRENCY = max(1, min(int(os.getenv("OLLAMA_MAX_CONCURRENCY", "4")), 32))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
# Match InboxMind's original working setup: each user runs Ollama on their own PC.
# Hosted inference remains an explicit opt-in mode, not the production default.
AI_BACKEND_MODE = os.getenv("AI_BACKEND_MODE", "private_worker").strip().lower()
_semaphore = asyncio.Semaphore(OLLAMA_MAX_CONCURRENCY)


def configured() -> bool:
    return bool(OLLAMA_BASE_URL and OLLAMA_MODEL)


def validate_configuration() -> None:
    if AI_BACKEND_MODE not in {"hosted", "private_worker"}:
        raise RuntimeError("AI_BACKEND_MODE must be 'hosted' or 'private_worker'.")
    if AI_BACKEND_MODE == "hosted" and not configured():
        # Allow the service to start while hosted inference is being provisioned;
        # requests fail closed with a clear 503 until the endpoint is configured.
        return
    if AI_BACKEND_MODE != "hosted" or not configured():
        return
    parsed = urlparse(OLLAMA_BASE_URL)
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Hosted Ollama must use HTTPS. Only loopback Ollama may use HTTP.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("OLLAMA_BASE_URL must not contain credentials, query parameters, or fragments.")


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    return headers


async def model_status() -> dict[str, Any]:
    if not configured():
        return {
            "available": False,
            "provider": "ollama",
            "model": OLLAMA_MODEL or None,
            "detail": "Hosted Ollama is not configured. Set OLLAMA_BASE_URL and OLLAMA_MODEL on the backend.",
        }
    try:
        timeout = httpx.Timeout(8.0, connect=4.0)
        async with httpx.AsyncClient(timeout=timeout, headers=_headers()) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
        names = [str(item.get("name", "")) for item in models if isinstance(item, dict)]
        available = any(name == OLLAMA_MODEL or name.startswith(OLLAMA_MODEL + ":") for name in names)
        return {
            "available": available,
            "provider": "ollama",
            "model": OLLAMA_MODEL,
            "installed_models": names[:100],
            "detail": "Hosted Ollama is ready." if available else "Hosted Ollama is reachable, but the configured model is not installed.",
        }
    except (httpx.HTTPError, ValueError):
        return {
            "available": False,
            "provider": "ollama",
            "model": OLLAMA_MODEL,
            "detail": "Hosted Ollama could not be reached. Check the private endpoint, TLS, and server status.",
        }


async def generate(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    json_output: bool = False,
    timeout_seconds: int | None = None,
) -> dict[str, str]:
    if not configured():
        raise HTTPException(503, "Hosted Ollama is not configured. AI is unavailable; no result was fabricated.")
    if not isinstance(messages, list) or not messages or len(messages) > 40:
        raise HTTPException(422, "AI request contains an invalid message list.")
    normalized: list[dict[str, str]] = []
    total_chars = 0
    for item in messages:
        if not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant"}:
            raise HTTPException(422, "AI request contains an invalid message.")
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(422, "AI request contains an empty message.")
        total_chars += len(content)
        normalized.append({"role": item["role"], "content": content})
    if total_chars > 100_000:
        raise HTTPException(413, "AI request is too large.")
    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "messages": normalized,
        "options": {"temperature": max(0.0, min(float(temperature), 1.0)), "num_ctx": 8192},
    }
    if json_output:
        payload["format"] = "json"
    request_timeout = OLLAMA_TIMEOUT_SECONDS if timeout_seconds is None else max(10, min(int(timeout_seconds), 600))
    timeout = httpx.Timeout(float(request_timeout), connect=8.0)
    try:
        async with _semaphore:
            async with httpx.AsyncClient(timeout=timeout, headers=_headers()) as client:
                response = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        content = data.get("message", {}).get("content", "") if isinstance(data, dict) else ""
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(502, "Ollama returned an empty response. No AI result was saved.")
        return {"content": content.strip(), "provider": "ollama", "model": OLLAMA_MODEL}
    except httpx.TimeoutException:
        raise HTTPException(504, "Hosted Ollama timed out. No AI result was fabricated; please retry.") from None
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {401, 403}:
            raise HTTPException(503, "Hosted Ollama authentication failed. Check the server-side API key.") from None
        if status == 429:
            raise HTTPException(503, "Hosted Ollama is at its concurrency or rate limit. Please retry shortly.") from None
        raise HTTPException(502, f"Hosted Ollama returned HTTP {status}. No AI result was saved.") from None
    except httpx.HTTPError:
        raise HTTPException(503, "Hosted Ollama is temporarily unreachable. No AI result was fabricated.") from None
    except ValueError:
        raise HTTPException(502, "Hosted Ollama returned invalid JSON. No AI result was saved.") from None
