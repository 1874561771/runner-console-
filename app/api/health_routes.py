"""无需认证的服务健康检查。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.job_manager import get_job_manager
from app.core.scheduler import get_scheduler
from app.core.run_queue import get_run_queue_worker
from app.db import pool
from app.ingest.retry_worker import get_ingest_retry_worker

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> JSONResponse:
    checks = {
        "database": False,
        "scheduler": get_scheduler().running,
        "ingest_retry": get_ingest_retry_worker().running,
        "run_queue": get_run_queue_worker().running,
    }
    try:
        checks["database"] = bool(pool.query_one("SELECT 1 AS ok"))
    except Exception:
        checks["database"] = False

    try:
        active_loops = len(get_job_manager().active())
    except RuntimeError:
        active_loops = 0

    ok = all(checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ok" if ok else "degraded",
            "checks": checks,
            "active_loops": active_loops,
        },
    )
