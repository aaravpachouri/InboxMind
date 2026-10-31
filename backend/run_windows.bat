@echo off
setlocal
cd /d "%~dp0"
if not exist ".env" (
  echo ERROR: backend\.env is missing.
  echo Copy .env.example to .env, then copy your existing APPS_SCRIPT_BRIDGE_URL and APPS_SCRIPT_BRIDGE_SECRET from your old working backend.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 py -m venv .venv
  if errorlevel 1 (
    echo ERROR: Python venv could not be created.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Backend dependency installation failed.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m uvicorn gmail_agent.main:app --host 127.0.0.1 --port 8000
pause
