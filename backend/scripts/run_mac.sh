#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11 or newer is required. Install Python 3.11/3.12, then rerun this script." >&2
  exit 1
fi
if [ ! -d .venv ]; then "$PYTHON_BIN" -m venv .venv; fi
source .venv/bin/activate
if ! python -c 'import fastapi, pydantic_settings, googleapiclient.discovery, google_auth_oauthlib.flow, cryptography.fernet, httpx, pypdf' >/dev/null 2>&1; then
  python -m pip install -r requirements.txt
fi
if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example. Add Google OAuth credentials to connect Gmail."; fi
exec uvicorn gmail_agent.main:app --host 127.0.0.1 --port 8000
