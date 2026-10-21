@echo off
REM ============================================================
REM  RunnerConsole server starter (Windows)
REM  Prereq: config.toml configured; MySQL running; ui/dist built
REM  (if ui/dist is missing run install.bat first - it builds the UI)
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [RunnerConsole] venv not found. Run install.bat first.
    pause
    exit /b 1
)

if not exist "ui\dist\index.html" (
    echo [RunnerConsole] ui\dist not found - frontend not built yet.
    echo   Run install.bat once to build it. Requires Node.js 18+.
    pause
    exit /b 1
)

echo [RunnerConsole] running migrations ...
"%PY%" -m app.db.migrate --config config.toml
if errorlevel 1 (
    echo [RunnerConsole] migrate FAILED - check MySQL settings in config.toml
    pause
    exit /b 1
)

echo [RunnerConsole] starting on http://0.0.0.0:8765 ...
echo   (close this window to stop the server)
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8765
if errorlevel 1 (
    echo.
    echo [RunnerConsole] FAILED to start. Common causes:
    echo   1. Port 8765 already in use - maybe a server is already running,
    echo      open http://127.0.0.1:8765/ directly.
    echo   2. DB connection in config.toml is wrong.
    echo   See the error above; send a screenshot if you need help.
    pause
)
endlocal
