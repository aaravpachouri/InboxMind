from __future__ import annotations

import os
import time
import httpx

API_BASE = "https://inboxmind-aaravpachouri.vercel.app/api/v1"
OLLAMA_BASE = "http://127.0.0.1:11434"
MODEL = "llama3.2:3b"


def main() -> None:
    credential = os.environ.get("INBOXMIND_WORKER_TOKEN", "")
    if len(credential) < 40:
        raise RuntimeError("Set INBOXMIND_WORKER_TOKEN to the one-time token from InboxMind Settings.")
    headers = {"Authorization": "Bearer " + credential}
    with httpx.Client(timeout=15.0) as client:
        while True:
            try:
                tags = client.get(OLLAMA_BASE + "/api/tags").json().get("models", [])
                names = [str(item.get("name", "")) for item in tags]
                ready = any(name == MODEL or name.startswith(MODEL + ":") for name in names)
                heartbeat = client.post(API_BASE + "/ai/worker/heartbeat", headers=headers, json={
                    "device_name": os.environ.get("COMPUTERNAME", "Windows PC"),
                    "worker_version": "1.0.0", "model_name": MODEL,
                    "installed_models": names, "model_available": ready,
                })
                heartbeat.raise_for_status()
                if ready:
                    response = client.post(API_BASE + "/ai/worker/jobs/claim", headers=headers, json={})
                    response.raise_for_status()
                    job = response.json().get("job")
                    if job:
                        body = job.get("payload", {})
                        inference = client.post(OLLAMA_BASE + "/api/chat", json={
                            "model": MODEL, "stream": False, "messages": body.get("messages", []),
                            "format": body.get("format") or None,
                            "options": {"temperature": body.get("temperature", 0.2), "num_ctx": 8192},
                        }, timeout=80.0)
                        inference.raise_for_status()
                        answer = inference.json().get("message", {}).get("content", "")
                        done = client.post(API_BASE + "/ai/worker/jobs/" + job["id"] + "/complete",
                            headers=headers, json={"success": bool(answer), "result": {
                                "content": answer, "provider": "ollama", "model": MODEL},
                                "error": "" if answer else "Ollama returned an empty response."})
                        done.raise_for_status()
                time.sleep(2)
            except (httpx.HTTPError, ValueError, KeyError) as error:
                print("InboxMind worker connection/inference error:", str(error)[:200])
                time.sleep(5)


if __name__ == "__main__":
    main()
