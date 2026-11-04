from __future__ import annotations

import getpass
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import keyring

DEFAULT_API_BASE = "https://inboxmind-aaravpachouri.vercel.app/api/v1"
OLLAMA_BASE = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.2:3b"
CREDENTIAL_SERVICE = "InboxMindLocalAIWorker"
CREDENTIAL_USER = "worker-token"
HEARTBEAT_SECONDS = 20
POLL_SECONDS = 2


def api_base() -> str:
    value = os.environ.get("INBOXMIND_API_BASE", DEFAULT_API_BASE).strip().rstrip("/")
    parsed = urlparse(value)
    allowed_hosts = {"inboxmind-aaravpachouri.vercel.app", "inboxmind-api-skqr.onrender.com"}
    if (parsed.scheme != "https" or parsed.hostname not in allowed_hosts or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path.rstrip("/") != "/api/v1"):
        raise RuntimeError("InboxMind API base must be the trusted InboxMind HTTPS /api/v1 endpoint.")
    return value


def get_worker_token() -> str:
    token = keyring.get_password(CREDENTIAL_SERVICE, CREDENTIAL_USER)
    if not token:
        print("Register this PC in InboxMind Settings, then paste the one-time token below.")
        token = getpass.getpass("Worker token (input hidden): ").strip()
        if len(token) < 40:
            raise RuntimeError("Worker token is invalid. Register this PC again in InboxMind Settings.")
        keyring.set_password(CREDENTIAL_SERVICE, CREDENTIAL_USER, token)
        print("Worker token saved in Windows Credential Manager for this Windows account.")
    return token


def ollama_status(client: httpx.Client, model: str) -> tuple[bool, list[str]]:
    response = client.get(OLLAMA_BASE + "/api/tags", timeout=3.0)
    response.raise_for_status()
    items = response.json().get("models", [])
    names = [str(item.get("name", "")) for item in items if isinstance(item, dict)]
    ready = any(name == model or name.startswith(model + ":") for name in names)
    return ready, names


def post(client: httpx.Client, base: str, headers: dict[str, str], path: str, data: dict) -> dict:
    response = client.post(base + path, headers=headers, json=data)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("InboxMind returned an invalid worker response.")
    return body


def complete_job(client: httpx.Client, base: str, headers: dict[str, str],
                 model: str, job: dict) -> None:
    job_id = str(job.get("id", ""))
    payload = job.get("payload") or {}
    messages = payload.get("messages")
    if not job_id or not isinstance(messages, list) or not messages:
        raise ValueError("AI job is missing its ID or messages.")
    request_data = {
        "model": model, "stream": False, "messages": messages,
        "options": {"temperature": float(payload.get("temperature", 0.2)), "num_ctx": 8192},
    }
    if payload.get("format") == "json":
        request_data["format"] = "json"
    try:
        response = client.post(OLLAMA_BASE + "/api/chat", json=request_data,
                               timeout=httpx.Timeout(80.0, connect=3.0))
        response.raise_for_status()
        answer = response.json().get("message", {}).get("content", "")
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Ollama returned an empty response.")
        post(client, base, headers, f"/ai/worker/jobs/{job_id}/complete", {
            "success": True,
            "result": {"content": answer.strip(), "provider": "ollama", "model": model},
            "error": "",
        })
        print("Completed local AI job:", str(job.get("type", "job")))
    except Exception as exc:
        try:
            post(client, base, headers, f"/ai/worker/jobs/{job_id}/complete", {
                "success": False, "result": {}, "error": str(exc)[:900],
            })
        except Exception:
            print("Could not report job failure; the server lease will expire.")
        print("Local inference failed:", str(exc)[:250])


def install_autostart() -> None:
    if os.name != "nt":
        print("Automatic Windows startup is available only on Windows.")
        return
    task = f'"{Path(sys.executable).resolve()}" "{Path(__file__).resolve()}" --run'
    result = subprocess.run(
        ["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", "InboxMindLocalAIWorker",
         "/TR", task, "/RL", "LIMITED"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError("Could not register Windows startup task: " + (result.stderr or result.stdout)[:400])
    print("InboxMind worker is registered to start at Windows sign-in.")


def main() -> None:
    base = api_base()
    model = os.environ.get("INBOXMIND_OLLAMA_MODEL", DEFAULT_MODEL).strip()
    token = get_worker_token()
    headers = {"Authorization": "Bearer " + token}
    if "--install-autostart" in sys.argv:
        install_autostart()
    print("InboxMind private AI worker running. Ollama remains local; this worker connects outward only.")
    last_heartbeat = 0.0
    ready = False
    model_names: list[str] = []
    with httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        while True:
            now = time.monotonic()
            if now - last_heartbeat >= HEARTBEAT_SECONDS:
                try:
                    ready, model_names = ollama_status(client, model)
                except (httpx.HTTPError, ValueError):
                    ready, model_names = False, []
                try:
                    post(client, base, headers, "/ai/worker/heartbeat", {
                        "device_name": os.environ.get("COMPUTERNAME", "Windows PC")[:120],
                        "worker_version": "1.0.0", "model_name": model,
                        "installed_models": model_names, "model_available": ready,
                    })
                except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                    print("InboxMind heartbeat failed:", str(exc)[:220])
                print("Ollama model:", "ready" if ready else "offline or selected model not installed")
                last_heartbeat = now
            if not ready:
                time.sleep(POLL_SECONDS)
                continue
            try:
                claimed = post(client, base, headers, "/ai/worker/jobs/claim", {})
                job = claimed.get("job")
                if job:
                    complete_job(client, base, headers, model, job)
                else:
                    time.sleep(POLL_SECONDS)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    print("Worker token was rejected. Revoke and register this PC again in InboxMind Settings.")
                    time.sleep(10)
                else:
                    print("InboxMind API error:", str(exc)[:220])
                    time.sleep(5)
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                print("Worker connection error:", str(exc)[:220])
                time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInboxMind worker stopped.")
    except Exception as exc:
        print("InboxMind worker error:", str(exc)[:500])
        raise
