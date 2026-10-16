"""业务路由：run 的 case 明细与产物清单（文件浏览 / 下载用）。

契约权威 = frontend/js/api.js mockRoutes：
* GET /api/runs/{run_id}/cases           → dao.list_cases
* GET /api/runs/{run_id}/artifacts?kind= → dao.list_artifacts
权限与 run 详情一致（owner / admin，经 runs_routes.get_run_or_404）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.runs_routes import get_run_or_404
from app.db.dao import runs as runs_dao

router = APIRouter(prefix="/api")


@router.get("/runs/{run_id}/cases")
def list_run_cases(run_id: str, user: dict = Depends(get_current_user)) -> list[dict]:
    get_run_or_404(run_id, user)
    return runs_dao.list_cases(run_id)


@router.get("/runs/{run_id}/artifacts")
def list_run_artifacts(
    run_id: str,
    kind: str = "",
    user: dict = Depends(get_current_user),
) -> list[dict]:
    get_run_or_404(run_id, user)
    return runs_dao.list_artifacts(run_id, kind or None)
