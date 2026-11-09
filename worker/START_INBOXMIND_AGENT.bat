@echo off
setlocal
cd /d "%~dp0"

echo.
echo  InboxMind Private AI Agent
echo  -------------------------
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python Launcher was not found. Install Python 3.12 from python.org.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo ERROR: Could not create the virtual environment.
    pause
    exit /b 1
  )
)

echo Installing/checking worker dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Worker dependencies could not be installed.
  pause
  exit /b 1
)

where ollama >nul 2>nul
if errorlevel 1 (
  echo ERROR: Ollama was not found. Install Ollama and start it first.
  pause
  exit /b 1
)

ollama list >nul 2>nul
if errorlevel 1 (
  echo ERROR: Ollama is not responding. Start Ollama, then run this file again.
  pause
  exit /b 1
)

if /I "%~1"=="install-autostart" (
  echo Registering InboxMind to start at Windows sign-in...
  ".venv\Scripts\python.exe" run_worker.py --install-autostart
  if errorlevel 1 (
    echo ERROR: Could not register the startup task.
    pause
    exit /b 1
  )
)

echo.
echo Starting InboxMind worker.
echo Keep this window open while the agent is running.
echo Press Ctrl+C to stop the worker.
echo.
".venv\Scripts\python.exe" run_worker.py
set EXIT_CODE=%ERRORLEVEL%
echo.
echo InboxMind worker exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
