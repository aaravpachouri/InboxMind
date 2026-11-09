# InboxMind hosted Ollama migration — zero-cost plan

## Decision and hard constraint

The target architecture is:

`Vercel frontend -> InboxMind FastAPI API -> authenticated HTTPS Ollama endpoint`

The API already supports this path. Set `AI_BACKEND_MODE=hosted`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and (when the inference host requires it) `OLLAMA_API_KEY`. In hosted mode, `_run_local_ai_job` calls `hosted_ollama.generate()` directly and does not register, heartbeat, or poll a Windows worker. The endpoint must implement the Ollama HTTP API used here: `GET /api/tags` and `POST /api/chat`.

**A strict ₹0 budget cannot currently guarantee an always-on hosted Ollama process.** Free application tiers commonly suspend idle services, and free GPU/CPU inference allocations are limited or subject to sleep, quotas, queueing, or cold starts. The existing InboxMind Render API is itself on Render's Free plan and can also spin down. A free endpoint can remove the laptop dependency, but it cannot honestly promise uninterrupted model availability. Do not describe a sleeping/scale-to-zero service as always-on.

## Safe rollout sequence

1. Keep the current production setting `AI_BACKEND_MODE=private_worker` until a hosted Ollama endpoint has been provisioned and smoke-tested. This avoids silently disabling the currently configured AI path.
2. Select a genuinely free Ollama-compatible host only after verifying its current limits, persistence, cold-start behavior, outbound access, and whether it permits a long-running model server. Do not create paid resources or enable a trial that can convert to paid billing.
3. Deploy Ollama on that host with the smallest practical model. Start with `llama3.2:3b` (the model already used by InboxMind); it is a sensible low-memory baseline, not a claim that it is the strongest model. Compare any alternative using the same InboxMind prompts and latency budget before changing the model.
4. Protect the endpoint with HTTPS and an API key or private network. Never expose an unauthenticated Ollama port publicly. Store the endpoint and key only in Render environment variables; never commit them.
5. Verify `GET /api/tags` lists the configured model and run a real `POST /api/chat` smoke test using synthetic text, not mailbox content.
6. Set Render's `AI_BACKEND_MODE=hosted`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `OLLAMA_API_KEY` only after the endpoint passes the checks. The current backend enforces per-user AI opt-in before hosted inference and returns explicit errors instead of fabricating results.
7. Test sign-in, Gmail bridge isolation, AI opt-in/off, summary, analysis JSON, chat, reply drafting, timeout handling, endpoint outage, and model-not-installed behavior. Confirm that no worker heartbeat is required in hosted mode.
8. Monitor free-tier quotas and cold starts. If the provider suspends the service, the UI must show AI as temporarily unavailable and allow retry; it must not fall back to a different model provider.

## Model selection

- Initial baseline: `llama3.2:3b`, because it is already the configured InboxMind model and is a relatively small Ollama model.
- Do not automatically pull a larger model on a free host. RAM, disk, CPU speed, and host policy must be measured first.
- Do not change to Gemini, OpenAI, or another hosted model provider. The hosted endpoint remains Ollama-compatible.

## Current verified state

- `backend/gmail_agent/hosted_ollama.py` already implements HTTPS validation for non-loopback endpoints, optional bearer authentication, model discovery through `/api/tags`, chat through `/api/chat`, concurrency limiting, timeouts, and fail-closed errors.
- `backend/tests/test_hosted_ollama.py` already tests missing configuration, input validation, TLS enforcement, and that hosted mode bypasses the personal Windows worker.
- The production Render service is currently on the Free plan. Its deployment configuration still selects `private_worker`.
- No production environment variables were changed as part of this plan. No paid resources were created.

## What ₹0 can and cannot deliver

| Requirement | Free-only status |
|---|---|
| No dependency on the user's laptop | Achievable once a hosted Ollama endpoint is configured |
| No manual worker launch | Achievable in hosted mode |
| Ollama-only provider | Supported |
| Always-on model with guaranteed uptime | Not guaranteed on free compute |
| Always-on API | Not guaranteed while the current API remains on Render Free |
| No charges | Preserved by not provisioning paid resources or enabling paid trials |

If uninterrupted availability becomes mandatory, a paid always-on inference host and likely an always-on API plan will be required. Ask for explicit budget approval before provisioning either.
