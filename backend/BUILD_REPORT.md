# Backend build and verification report

## Portability and OAuth follow-up

- Added Windows launch and test scripts alongside the macOS launcher. The same source tree is intended for both platforms; each machine should generate its own local `.env`, token, encryption key, and database.
- Added the Gmail `gmail.send` OAuth scope because sending drafts requires it in addition to the `gmail.modify` scope.

## Implemented

- FastAPI API with 46 paths and 56 generated operations in OpenAPI.
- Gmail OAuth callback flow and encrypted local token persistence, refresh support, and disconnect/revocation attempt.
- Gmail message/thread search, local cache, paginated sync, labels, archive, read-state, move-to-trash, and Gmail drafts.
- Confirm-before-send boundary for drafts; preview-before-confirm bulk actions; permanent deletion is intentionally unavailable.
- Local Ollama reasoning plus offline heuristic fallbacks, inbox categories/priorities, summaries, phishing cues, task extraction, reply drafting, feedback context, daily briefing, and follow-up candidates.
- SQLite task/memory/feedback/notification/audit persistence.
- Optional Google Calendar event operations, attachment download/analysis, and a constrained local document index/search.
- Loopback-only host guard, origin checks on mutations, encrypted OAuth token file, local-only Ollama endpoint enforcement, and request-size limits for attachments.

## Checks run in this build environment

- `python -m compileall -q gmail_agent tests` — passed.
- `pytest -q` — **18 passed**.
- Uvicorn startup smoke test — `GET /api/v1/health` returned HTTP 200.
- OpenAPI smoke test — `GET /openapi.json` returned HTTP 200; schema generated successfully.
- Local APIs were tested using a temporary SQLite database and mocked Gmail methods; the tests do not send real messages.

## Not verified live in this environment

- Real Google OAuth, Gmail calls, Calendar calls, and refresh-token behavior were not tested against a real account because no Google credentials were supplied. Google client packages are declared in `requirements.txt`, but this environment could not resolve the package index during installation. Install requirements on the Mac and follow `docs/GOOGLE_OAUTH_SETUP.md` to validate the real account connection.
- Ollama model inference was not required for the passing test suite; the deterministic fallback path was exercised. Install Ollama and pull a local model to test model-backed reasoning on the Mac.
- The final web frontend is intentionally deferred to the next phase.
