@echo off
setlocal
cd /d "%~dp0"
echo Starting InboxMind backend and frontend in separate windows...
start "InboxMind Backend" cmd /k ""%~dp0backend\run_windows.bat""
timeout /t 3 /nobreak >nul
start "InboxMind Frontend" cmd /k ""%~dp0frontend\run_windows.bat""
echo.
echo Once both windows are running, open http://127.0.0.1:5173
echo Backend API docs: http://127.0.0.1:8000/docs
echo.
echo IMPORTANT: Configure backend\.env from your existing local settings first.
pause
