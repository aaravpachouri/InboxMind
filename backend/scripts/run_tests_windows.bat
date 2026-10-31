@echo off
setlocal
cd /d "%~dp0.."
if not exist .venv\Scripts\activate.bat (
  echo Run scripts\run_windows.bat once to create the virtual environment and install dependencies.
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pytest -q
