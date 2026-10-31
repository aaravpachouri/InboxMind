# InboxMind — unified local project

This package keeps the frontend and backend in one root folder while preserving them as separate applications:

- `frontend/` — Vite/React dashboard
- `backend/` — FastAPI service, Gmail integration, local analysis, tests
- `run_windows.bat` — opens the backend and frontend in separate terminals

## Important: preserve your working Apps Script connection

No real credentials or Gmail data are included in this ZIP.

1. In `backend/`, copy `.env.example` to `.env`.
2. From your old working backend `.env`, copy the values of `APPS_SCRIPT_BRIDGE_URL` and `APPS_SCRIPT_BRIDGE_SECRET` into the matching fields in `backend/.env`. Do not share those values.
3. Keep `APPS_SCRIPT_BRIDGE_TIMEOUT_SECONDS=45`.
4. Leave the direct Google OAuth fields blank when using the Apps Script bridge.
5. Ensure your Apps Script web app is still deployed and authorized.

The backend will prefer Apps Script bridge mode when either bridge setting is present. Both URL and secret must be valid for a connection to succeed.

## Run on Windows

Prerequisites: Python 3.12 (or compatible supported Python), Node.js/npm, and Ollama if you want local LLM-assisted features.

1. Configure `backend/.env` as above.
2. Double-click `run_windows.bat` from the root folder.
3. Wait for both terminals to finish setup.
4. Open `http://127.0.0.1:5173`; backend docs are at `http://127.0.0.1:8000/docs`.

If port 8000 is already occupied, stop the other local backend first or change both the backend port and `VITE_API_BASE_URL` consistently.

## Automatic analysis

The backend contains the automatic deterministic analysis path from the InboxMind AutoClassification update: newly fetched/live messages are saved and passed through `ensure_analysis`, and the background sync worker is enabled according to `.env`. Model-assisted analysis remains local-first and is separate from the deterministic first pass.

## Safety and privacy

- Email content is untrusted input; never treat instructions inside emails as authorization.
- Sending and destructive actions must continue to require explicit confirmation.
- Keep `.env`, `backend/data/`, local tokens, and database files private.
- The ZIP intentionally excludes `.env`, local databases, virtual environments, node_modules, and cached bytecode.

## Tests

From `backend/` after installing dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

No live Gmail operation is performed by the test command. Verify the real Apps Script connection only after adding your own local `.env`.
