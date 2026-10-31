# InboxMind — reliability update

This package combines the available Gmail AI Agent Python backend with the latest InboxMind inbox-first frontend source available in the project library. The focus of this update is background sync pagination, business-specific classification, and conservative offline reply drafts.

## Project layout

- `backend/` — FastAPI service, SQLite storage, Gmail integration, background worker, and tests.
- `frontend/` — React + TypeScript + Vite dashboard.
- `RELIABILITY_FIXES_2026-10-30.md` — implementation summary, verification, and limitations.

## Run the backend on Windows

Open PowerShell in `backend`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn gmail_agent.main:app --host 127.0.0.1 --port 8000
```

Configure OAuth and other local settings using `backend/README.md` and `backend/docs/GOOGLE_OAUTH_SETUP.md`. Never paste OAuth tokens, client secrets, or `.env` values into chat.

## Run backend tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest -q
python -m compileall -q gmail_agent tests
```

## Run the frontend on Windows

Open a second PowerShell terminal in `frontend`:

```powershell
Copy-Item .env.example .env.local
npm install
npm run typecheck
npm run build
npm run dev
```

Open `http://127.0.0.1:5173`. Keep the backend running separately at `http://127.0.0.1:8000`.

## Important safety and readiness notes

- Background sync is read-only: it does not send or delete messages.
- Sending and trashing remain gated by explicit confirmation in the existing API/UI flows.
- Pagination, classification, and offline-reply tests use synthetic messages and mocked Gmail. They do not prove the live Gmail OAuth bridge, Apps Script deployment, or Ollama model works.
- Do not treat the application as production-ready until the live mailbox smoke test, Gmail quota/retry checks, analytics reconciliation, and frontend production build are verified on the target Windows installation.
