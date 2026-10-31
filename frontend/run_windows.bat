@echo off
setlocal
cd /d "%~dp0"
if not exist "node_modules" (
  npm install
  if errorlevel 1 (
    echo ERROR: Frontend dependency installation failed.
    pause
    exit /b 1
  )
)
if not exist ".env.local" (
  if exist ".env.example" copy ".env.example" ".env.local" >nul
)
npm run dev -- --host 127.0.0.1
pause
