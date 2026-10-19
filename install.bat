@echo off
REM ============================================================
REM  RunnerConsole one-shot deploy / run (Windows)
REM  First run: venv + deps + interactive wizard (create db/user,
REM  write config.toml) + migrate + serve on 0.0.0.0:8765
REM  Later runs: migrate (idempotent) + serve
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"

if exist "%PY%" goto :ready

echo [1/4] Checking Python 3.11+ ...
where py >nul 2>nul
if %errorlevel%==0 (set "PYSRC=py") else (set "PYSRC=python")
%PYSRC% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo   Python 3.11+ not found. Install it first:
    echo     winget install Python.Python.3.12
    echo   or https://www.python.org/downloads/
    pause & exit /b 1
)

echo [2/4] Creating venv and installing dependencies (1-2 min on first run) ...
%PYSRC% -m venv .venv
if errorlevel 1 (echo   venv creation failed & pause & exit /b 1)
"%PY%" -m pip install --quiet -r requirements.txt
if errorlevel 1 (echo   dependency install failed, check network & pause & exit /b 1)

:ready
if exist "config.toml" goto :migrate

echo [3/4] Initialising database and config (interactive wizard) ...
"%PY%" setup_wizard.py
if errorlevel 1 (pause & exit /b 1)
goto :serve

:migrate
echo [3/4] config.toml exists - running idempotent migrations ...
"%PY%" -m app.db.migrate --config config.toml
if errorlevel 1 (pause & exit /b 1)

:serve
echo [4/4] Serving http://127.0.0.1:8765/  (LAN: use this machine's IP)
echo       Close this window to stop the server.
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8765
pause
