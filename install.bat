@echo off
REM ============================================================
REM  RunnerConsole one-shot deploy / run (Windows)
REM  First run: venv + deps + frontend build (npm) + interactive
REM  wizard (create db/user, write config.toml) + migrate + serve
REM  Later runs: frontend build (if missing) + migrate + serve
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"

if exist "%PY%" goto :venvready

echo [1/5] Checking Python 3.11+ ...
where py >nul 2>nul
if %errorlevel%==0 (set "PYSRC=py") else (set "PYSRC=python")
%PYSRC% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo   Python 3.11+ not found. Install it first:
    echo     winget install Python.Python.3.12
    echo   or https://www.python.org/downloads/
    pause & exit /b 1
)

echo [2/5] Creating venv and installing dependencies (1-2 min on first run) ...
%PYSRC% -m venv .venv
if errorlevel 1 (echo   venv creation failed & pause & exit /b 1)
"%PY%" -m pip install --quiet -r requirements.txt
if errorlevel 1 (echo   dependency install failed, check network & pause & exit /b 1)

:venvready
echo [3/5] Building frontend (Node.js + npm) ...
if exist "ui\dist\index.html" goto :uiready
where node >nul 2>nul
if errorlevel 1 (
    echo   Node.js not found. The web UI needs Node 18+ to build:
    echo     winget install OpenJS.NodeJS.LTS
    echo   Then run install.bat again.
    pause & exit /b 1
)
pushd ui
if not exist node_modules (
    call npm install --no-audit --no-fund
    if errorlevel 1 (echo   npm install failed & popd & pause & exit /b 1)
)
call npm run build
if errorlevel 1 (echo   frontend build failed & popd & pause & exit /b 1)
popd

:uiready
if exist "config.toml" goto :migrate

echo [4/5] Initialising database and config (interactive wizard) ...
"%PY%" setup_wizard.py
if errorlevel 1 (pause & exit /b 1)
goto :serve

:migrate
echo [4/5] config.toml exists - running idempotent migrations ...
"%PY%" -m app.db.migrate --config config.toml
if errorlevel 1 (pause & exit /b 1)

:serve
echo [5/5] Serving http://127.0.0.1:8765/  (LAN: use this machine's IP)
echo       Close this window to stop the server.
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8765
pause
