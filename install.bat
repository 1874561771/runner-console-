@echo off
chcp 65001 >nul
REM ============================================================
REM  RunnerConsole 一键部署 / 启动（Windows）
REM  首次运行：建 venv → 装依赖 → 交互向导（建库建用户 + 生成配置）→ 迁移 → 启动
REM  日常运行：再次双击即可直接启动服务
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"

if exist "%PY%" goto :ready

echo [1/4] 检查 Python 3.11+ ...
where py >nul 2>nul
if %errorlevel%==0 (set "PYSRC=py") else (set "PYSRC=python")
%PYSRC% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo   未找到 Python 3.11+。请先安装后重跑本脚本：
    echo     winget install Python.Python.3.12
    echo   或 https://www.python.org/downloads/
    pause & exit /b 1
)

echo [2/4] 创建虚拟环境并安装依赖（首次约 1-2 分钟）...
%PYSRC% -m venv .venv
if errorlevel 1 (echo   venv 创建失败 & pause & exit /b 1)
"%PY%" -m pip install --quiet -r requirements.txt
if errorlevel 1 (echo   依赖安装失败，请检查网络 & pause & exit /b 1)

:ready
if exist "config.toml" goto :migrate

echo [3/4] 初始化数据库与配置（交互向导）...
"%PY%" setup_wizard.py
if errorlevel 1 (pause & exit /b 1)
goto :serve

:migrate
echo [3/4] config.toml 已存在，跳过向导；执行数据库迁移（幂等）...
"%PY%" -m app.db.migrate --config config.toml
if errorlevel 1 (pause & exit /b 1)

:serve
echo [4/4] 启动服务：http://127.0.0.1:8765/  （局域网其它电脑用本机 IP 访问）
echo       关闭本窗口 = 停止服务
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8765
pause
