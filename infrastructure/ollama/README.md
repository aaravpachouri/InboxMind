# Hosted Ollama deployment

InboxMind's public backend can use one centrally hosted Ollama instance. The
FastAPI backend is the only component that talks to Ollama; browsers never
receive the Ollama URL or credentials.

## Required backend environment

- `AI_BACKEND_MODE=hosted`
- `OLLAMA_BASE_URL=https://<private-ollama-gateway>` (HTTPS required outside loopback)
- `OLLAMA_MODEL=llama3.2:3b` (must already be pulled on the Ollama host)
- `OLLAMA_API_KEY` (optional bearer token when the gateway validates it)
- `OLLAMA_TIMEOUT_SECONDS=120`
- `OLLAMA_MAX_CONCURRENCY=4`
- `OLLAMA_KEEP_ALIVE=5m`

Keep each value in the backend hosting provider's secret/environment settings.
Never put credentials in Vercel variables, frontend code, Git, or a public URL.
The Ollama endpoint must be reachable only by the backend through a private
network or an authenticated TLS gateway. Do not expose raw port 11434.

## Prepare the Ollama host

Install Docker and the NVIDIA Container Toolkit on a GPU-capable host, then:

```sh
cd infrastructure/ollama
docker compose up -d --build
docker compose exec ollama ollama pull llama3.2:3b
docker compose exec ollama ollama list
```

The compose file binds Ollama to loopback. For a remote backend, place Ollama
and the backend on a private network or configure an authenticated TLS gateway
in front of Ollama. The raw Ollama listener is not an internet-facing API.

## User privacy and rollout

- Each signed-in user's existing `ai_enabled` setting remains the opt-in gate.
- Email content is retrieved through that user's own Apps Script bridge and is
  sent only from the backend to the configured Ollama host.
- The frontend never calls Ollama directly.
- Existing per-user worker queue, hashed worker tokens, encrypted job payloads,
  and Windows worker remain available when `AI_BACKEND_MODE=private_worker`.
- Hosted mode does not fall back to a different provider or invent a response.
- Sending email remains a separate explicit-confirmation operation.

## Rollout checklist

1. Provision a GPU host and private authenticated HTTPS route.
2. Pull the exact model configured in `OLLAMA_MODEL`.
3. Set backend environment variables; keep `AI_BACKEND_MODE=hosted`.
4. Verify `GET /api/v1/system/model` for a signed-in opted-in user.
5. Verify summarization, analysis, chat, draft-reply generation, and daily briefing.
6. Load-test concurrency and latency before inviting public users.

The repository changes do not provision compute or purchase hosting. Model
hosting requires a separately provisioned GPU-capable machine; Render Free is
not a suitable Ollama inference host.
