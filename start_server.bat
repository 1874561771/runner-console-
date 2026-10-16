@echo off
REM ============================================================
REM Runner Console 启动脚本（Windows）
REM 用法：双击或命令行执行；依赖 config.toml 已配置好
REM 端口默认 8765；DB 不可用时服务会立即报错退出（无降级模式）
REM ============================================================
setlocal
cd /d "%~dp0"

REM ---- Python 解释器：优先项目 venv ----
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

REM ---- 首次运行：创建 venv 并安装依赖 ----
if not exist ".venv\Scripts\python.exe" (
    echo [RunnerConsole] creating venv ...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

REM ---- 数据库 schema 迁移（幂等） ----
echo [RunnerConsole] running migrations ...
"%PY%" -m app.db.migrate --config config.toml
if errorlevel 1 (
    echo [RunnerConsole] migrate FAILED - check MySQL in config.toml
    pause
    exit /b 1
)

REM ---- 启动服务 ----
echo [RunnerConsole] starting on http://0.0.0.0:8765 ...
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8765
endlocal
