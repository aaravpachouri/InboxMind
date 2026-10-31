# Gmail AI Agent Dashboard

A local-first React + TypeScript + Vite dashboard for the Gmail AI Agent backend. The dashboard calls the existing Python API at `http://127.0.0.1:8000/api/v1` by default. It does not contain OAuth credentials, Google tokens, bridge secrets, or cloud AI API keys.

## Included views

- Overview: unread count, priority count, local AI status, daily briefing, recent mail, near-term tasks.
- Inbox and Priority: search, live Gmail listing, conversation detail, local AI analysis/summarization, mark read/unread, archive, Trash with confirmation, and draft reply.
- Tasks: review extracted tasks, complete/dismiss, and add tasks.
- Daily briefing: local AI narrative, important messages, task counts and due items.
- AI assistant: natural-language chat backed by the local API.
- Drafts: create/edit drafts and confirm before sending.
- Calendar: list upcoming events and create events explicitly.
- Local files: index the configured local folder and search indexed content.
- Memory & feedback: inspect/delete saved memory, add preferences, and save explicit feedback locally.
- Settings: runtime health, account status, local model selection, background sync controls, and local storage paths.

## Prerequisites

- Node.js 20 or newer (Node 22 is fine)
- npm
- The Python backend running at `http://127.0.0.1:8000`
- Gmail bridge already connected in the backend
- Ollama installed if you want local model inference; the UI also reports heuristic fallback status

## Run on Windows (PowerShell)

1. Extract this folder somewhere convenient, for example `C:\Users\<you>\Downloads\Gmail_AI_Agent_Dashboard`.
2. Open a terminal in the extracted folder.
3. Create the local environment file:

   ```powershell
   Copy-Item .env.example .env.local
   ```

   The default API URL already points to localhost. Do not add secrets to `.env.local`.

4. Install packages and launch:

   ```powershell
   npm install
   npm run dev
   ```

5. Open `http://127.0.0.1:5173` while the backend remains running in a separate terminal.

## Run on macOS

From Terminal, in this folder:

```bash
cp .env.example .env.local
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Keep the Python backend and Ollama running in separate Terminal windows.

## Build and typecheck

```bash
npm run typecheck
npm run build
```

The `dist/` folder is a static build of the dashboard. For this project, keep it local; do not deploy it publicly unless you deliberately design authentication and remote access controls for the API.

## Backend compatibility

The dashboard expects the API paths under `/api/v1`, including `/health`, `/auth/status`, `/emails`, `/insights`, `/tasks`, `/briefing/daily`, `/chat`, `/drafts`, `/calendar/events`, `/files`, `/memory`, `/feedback`, `/settings`, and `/system/model`. Set `VITE_API_BASE_URL` in `.env.local` if the backend runs at a different local URL.

## Privacy and safety

- Browser requests are sent only to the configured local backend by default.
- Do not place `APPS_SCRIPT_BRIDGE_SECRET`, Google client secrets, OAuth tokens, or API keys in Vite environment variables; `VITE_*` values are public to browser code.
- Send and Trash actions use a confirmation dialog. Permanent Gmail deletion is not exposed in this dashboard.
- AI analysis and summaries use the local backend configuration. The dashboard itself does not call a cloud AI API.
- Email and memory content should be treated as private. Don't share screenshots that reveal message content or credentials when asking for help.

## Current limitations

- Frontend tests require installation of the dependencies with `npm install`; runtime behavior still needs a smoke test against the user's live backend.
- The local model may be slower on an older Mac. The dashboard displays the backend's current model/provider status rather than assuming availability.
- The backend's automated task extraction is advisory; review suggested tasks and deadlines before relying on them.
