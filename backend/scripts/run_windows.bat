@echo off
setlocal
cd /d "%~dp0.."

where py >nul 2>&1
if errorlevel 1 (
  echo Python Launcher was not found. Install Python 3.11 or newer from https://www.python.org/downloads/windows/
  echo Enable the Python Launcher option during installation.
  exit /b 1
)

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install Python 3.11 or 3.12 and rerun this script.
  exit /b 1
)

if not exist .venv py -3 -m venv .venv
if errorlevel 1 exit /b 1
call .venv\Scripts\activate.bat
if errorlevel 1 exit /b 1

python -c "import fastapi, pydantic_settings, googleapiclient.discovery, google_auth_oauthlib.flow, cryptography.fernet, httpx, pypdf" >nul 2>&1
if errorlevel 1 (
  python -m pip install --upgrade pip
  if errorlevel 1 exit /b 1
  python -m pip install -r requirements.txt
  if errorlevel 1 exit /b 1
)

if not exist .env (
  copy .env.example .env >nul
  echo Created .env from .env.example. Add Google OAuth credentials to connect Gmail.
)

echo Starting Gmail AI Agent backend at http://127.0.0.1:8000/docs
python -m uvicorn gmail_agent.main:app --host 127.0.0.1 --port 8000
