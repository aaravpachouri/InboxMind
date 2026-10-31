# Gmail AI Agent Backend

A standalone, local-first backend for a personal Gmail AI secretary. It is cross-platform: you can develop/test it on Windows and run the same source on your target Mac. It leaves the frontend for a later phase. It is not a mock API: Gmail operations call the real Gmail API after OAuth is configured, and local AI uses Ollama when available with deterministic offline fallbacks.

## What is included

- FastAPI backend with browsable API docs at `http://127.0.0.1:8000/docs`.
- Google OAuth web flow, offline refresh, and encrypted local token storage.
- Gmail search/sync, local inbox index, threads, labels, archive, mark read/unread, move-to-trash, and Gmail drafts.
- Explicit send approval: a draft is not sent unless `/drafts/{id}/send` receives `{"confirm_send": true}`.
- Inbox analysis: priority, category, summary, action-needed signal, task extraction, and basic suspicious-message cues.
- Local AI via Ollama; the default `qwen2.5:3b` is a starting point only. If it does not fit the Mac or is too slow, use a smaller installed Ollama model via Settings or `.env`.
- Local chat/search, persistent tasks, inspectable/deletable memory, explicit feedback storage, notifications, and audit events.
- Optional Google Calendar event listing/creation, local document index/search, attachment metadata and explicit downloads.
- Background polling (default every 5 minutes); it only syncs and analyzes. It will never send or delete messages in the background.
- Tests with mocked Gmail calls, so basic checks do not need Google credentials.

## Requirements

- Windows 10/11 or macOS with Python 3.11 or 3.12 recommended (the backend may work with other versions supported by dependencies).
- Google account and a Google Cloud project with Gmail API enabled. Calendar API is needed only if you use calendar routes.
- Ollama is optional; the backend still runs without it using heuristic analysis.

## Quick start on Windows

1. Extract the ZIP to a normal folder (for example, `C:\Users\you\Projects\Gmail_AI_Agent_Backend`). Avoid placing the project inside a protected system directory.
2. Install Python 3.11 or 3.12 from [python.org](https://www.python.org/downloads/windows/) and enable the Python launcher during installation.
3. Double-click `scripts\run_windows.bat`, or open Command Prompt in the project folder and run:

   ```bat
   scripts\run_windows.bat
   ```

   The script creates `.venv`, installs requirements when needed, creates `.env` from `.env.example` on first run, and starts the local server.
4. Open `http://127.0.0.1:8000/docs`.

## Quick start on macOS

1. Extract the ZIP and open Terminal in the extracted `Gmail_AI_Agent_Backend` folder.
2. Run the included launcher:

   ```bash
   chmod +x scripts/run_mac.sh
   ./scripts/run_mac.sh
   ```

   It checks for Python 3.11+, creates `.venv`, installs requirements when needed, creates `.env` from `.env.example` on first run, and starts the local server. If `python3` is not available, install Python 3.11 or 3.12 from [python.org](https://www.python.org/downloads/macos/).
3. Open `http://127.0.0.1:8000/docs`.

## First-time setup on either system

1. Edit `.env` and follow `docs/GOOGLE_OAUTH_SETUP.md` to set up Google OAuth. Leave credentials blank if you only want to test local APIs without connecting Gmail.
2. To connect Gmail, call `GET /api/v1/auth/google/login`, open the returned `authorization_url` in a browser, grant access, and let Google redirect to the local callback. The future frontend will wrap this in a Connect Gmail button.
3. Call `POST /api/v1/sync` with `{"max_results": 50, "analyze": true}` to index recent mail. The background monitor subsequently syncs at the configured interval.

### Run tests on either system

Windows Command Prompt:

```bat
scripts\run_tests_windows.bat
```

macOS Terminal (with the virtual environment activated):

```bash
pytest -q
```

Tests use temporary SQLite databases and fake Gmail clients. They do not send mail and do not need OAuth credentials.

## Free local AI (optional)

Install Ollama from [ollama.com](https://ollama.com) and pull a model suitable for your Mac:

```bash
ollama pull qwen2.5:3b
```

The `.env` default is `qwen2.5:3b`; on an older Intel Mac you may prefer a smaller model. On Windows, Ollama is also optional and the same local-only endpoint setting applies. The project does not download model weights automatically. Check availability at `GET /api/v1/system/model` and available local models at `GET /api/v1/system/ollama-models`. For privacy, the backend blocks Ollama URLs that do not point to localhost. All AI inference stays on your own machine by default.

The model is used for optional reasoning, summarization, and reply drafting. API fallback behavior remains available if Ollama is offline. No cloud LLM API is called.

## Safety defaults and boundaries

- The server binds to loopback (`127.0.0.1`) and rejects non-local Host headers in non-test mode. Do not expose or port-forward it to the public internet.
- OAuth tokens are encrypted under `data/google_token.enc`; the local encryption key is stored in `data/.token_encryption_key` with restrictive permissions. Anyone who can access both files under the same OS account could still recover the token; protect your Mac account and backups.
- OAuth client credentials belong in `.env`, never in source files or frontend code.
- The app requests `gmail.modify`, `gmail.send`, and `calendar.events` (Calendar is only needed for calendar routes). Gmail scopes can trigger Google OAuth warnings or verification requirements depending on the app's testing/publishing state. Review the scopes before consent.
- Email bodies are untrusted input. The model is instructed not to treat them as commands. AI analysis never directly sends, deletes, archives, or labels an email.
- Send, trash, archive, bulk operations, local memory deletion, and attachment download have explicit API confirmation gates. Permanent deletion is not implemented; Trash is used.
- Bulk actions support a preview by sending `confirm=false` (the default), then a second confirmed request after the matched messages have been reviewed.
- A local document index only scans `LOCAL_FILES_DIR`, not arbitrary paths. Supported files are TXT, Markdown, CSV, JSON, PDF, and LOG. Indexing stores document text in SQLite.
- Email body content and OAuth secrets are not written to audit logs. Local database and indexed email content are stored unencrypted; use FileVault and protect device backups. OAuth tokens are separately encrypted.

## Current scope

The source ZIP is portable, but each computer should have its own `.env`, local database, OAuth token, and encryption key; do not copy token/key files between Windows and Mac. This ZIP is the **backend phase**. It deliberately does not include the final polished web UI yet. The API is structured so a React or other frontend can consume it later. There are no paid API dependencies or hosted services required for local operation.

For route details, start the app and open `/docs`; the frontend integration overview is in `docs/API_GUIDE.md`. For OAuth setup and troubleshooting, see `docs/GOOGLE_OAUTH_SETUP.md`.
