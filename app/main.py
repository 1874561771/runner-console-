"""RunnerConsole FastAPI 入口。

启动流程（等价原 webui/server.configure()，但改为 lifespan 阶段执行）：
  load config → pool.configure（MySQL 不可用直接抛异常退出，无降级模式）
  → JobManager 初始化 + recover_orphans（回收 DB 中 running 孤儿 loop）
  → 挂 /api 路由 → 挂 / 静态 frontend/ 目录 + /favicon。

运行方式：
  uvicorn app.main:app --host 0.0.0.0 --port 8000
  或  python -m app.main        （host/port 取自 config [server] 段）
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pymysql
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    admin_routes,
    auth_routes,
    cases_routes,
    env_routes,
    files_routes,
    loops_routes,
    runs_routes,
    stats_routes,
    status_routes,
    sse_routes,
    uploads_routes,
)
from app.config import get_settings
from app.core.job_manager import init_job_manager
from app.db import pool

logger = logging.getLogger("runnerconsole")

# uvicorn app.main:app 方式启动时只配置 uvicorn 自己的 logger，
# 这里补一份根配置，保证 lifespan / 请求访问日志可见（python -m app.main 幂等）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg = get_settings()
    # DB 自检失败直接抛异常 → uvicorn 启动失败退出（无降级模式）
    pool.configure(cfg.dsn())
    logger.info(
        "db pool ready: %s@%s:%s/%s",
        cfg.database.user, cfg.database.host, cfg.database.port, cfg.database.database,
    )
    # 执行引擎：JobManager 单例 + 孤儿 loop 回收（T4）
    manager = init_job_manager()
    for warning in manager.recover_orphans():
        logger.warning("orphan loop 需人工介入: %s", warning["message"])
    logger.info("job manager ready: workdir=%s artifacts=%s", manager.workdir, manager.artifacts_root)
    # 保留策略：启动时后台线程执行一次清理（T6）；失败不阻断启动
    threading.Thread(
        target=_startup_retention, daemon=True, name="startup-retention"
    ).start()
    yield


def _startup_retention() -> None:
    """启动时按 settings 保留策略清一次过期产物；任何异常只记日志。"""
    try:
        from app.core.retention import run_retention  # noqa: PLC0415

        result = run_retention()
        logger.info("startup retention done: %s", result)
    except Exception:
        logger.exception("startup retention failed（已忽略，不阻断服务）")


def create_app() -> FastAPI:
    app = FastAPI(title="RunnerConsole", version="2.0", lifespan=lifespan)
    app.include_router(auth_routes.router)
    app.include_router(sse_routes.router)
    # T7 业务路由（files_routes 挂 /runs/<run_id>/<relpath>，须在静态挂载前注册）
    app.include_router(loops_routes.router)
    app.include_router(runs_routes.router)
    app.include_router(cases_routes.router)
    app.include_router(env_routes.router)
    app.include_router(uploads_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(stats_routes.router)
    app.include_router(status_routes.router)
    app.include_router(files_routes.router)

    # 全局 DB 异常 → 500 JSON（不向客户端泄漏 SQL 细节，完整堆栈进日志）
    @app.exception_handler(pymysql.MySQLError)
    async def db_error_handler(_request: Request, exc: pymysql.MySQLError) -> JSONResponse:
        logger.exception("database error: %s", exc)
        return JSONResponse(status_code=500, content={"error": "database error"})

    # HTTPException → {"detail": ..., "error": ...}（前端 api.js 各视图统一
    # 读 data.error 展示错误文案；FastAPI 默认只返回 detail）
    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            text = str(detail.get("error") or detail.get("detail") or detail)
        else:
            text = str(detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": detail, "error": text})

    # 请求访问日志
    @app.middleware("http")
    async def access_log(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        logger.info(
            "%s %s -> %s (%.1f ms)",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        # 浏览器默认请求 /favicon.ico；项目图标是 SVG，直接以 SVG 响应
        path = FRONTEND_DIR / "favicon.svg"
        if path.is_file():
            return FileResponse(path, media_type="image/svg+xml")
        raise HTTPException(status_code=404)

    # 静态前端必须最后挂载："/" 通配，先注册的 /api 路由优先匹配
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    else:
        logger.warning("frontend 目录不存在，仅提供 API: %s", FRONTEND_DIR)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = get_settings()
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port)
