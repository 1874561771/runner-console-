"""业务路由：loops 列表/详情/轻量状态、启动（POST /api/run）、停止。

契约权威 = frontend/js/api.js mockRoutes + mock-data.js：
* GET  /api/loops?days=today|7|14|30|all&env_id=&status=running|failed&offset&limit
* GET  /api/loops/{loop_id}                      详情（同列表项 + jobs 全量）
* GET  /api/loops/{loop_id}/status               轻量视图 {loop: {...}|null}
* POST /api/run                                  → 201 {loop_id}
* POST /api/loops/{loop_id}/stop                 → {ok, message}

说明：
* 列表过滤（days/env_id/status/分页）是 T7 扩展，dao.list_loops 不支持，
  在本模块用 pool 补充查询（JOIN 口径与 dao._LOOP_JOIN 一致）。
* status=failed 口径 = loop 终态 failed，或存在 fail/setup_fail 轮次。
* jobs 的 passed/total/has_summary 从 runs 表 JOIN（不扫盘）。
* dut_model 取该 loop 最新 run 的 dut_version（无 runs 行则 null）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.api.common import (
    env_lock_view,
    fmt_dt,
    parse_days,
    parse_int,
    upload_abs_path,
)
from app.api.deps import get_current_user
from app.auth import perms
from app.core.job_manager import (
    PRODUCTS,
    LoopStartError,
    LoopStopError,
    get_job_manager,
)
from app.db import pool
from app.schemas import RunIn

router = APIRouter(prefix="/api")

# 与 dao._LOOP_JOIN 相同的 JOIN 口径，另带 env relpath（锁目录定位用）
_LOOP_SELECT = (
    "SELECT l.*, u.username AS owner_name, e.name AS env_name, "
    "e.relpath AS env_relpath "
    "FROM loops l "
    "JOIN users u ON u.id = l.owner_id "
    "LEFT JOIN environments e ON e.id = l.env_id "
)

_LOOP_STATUSES = ("running", "done", "stopped", "failed")


# ------------------------------------------------------------------ query

def _list_loop_rows(
    user: dict,
    days: str | None,
    env_id: str,
    status: str,
    offset: int,
    limit: int,
) -> list[dict]:
    where: list[str] = []
    params: list = []
    if not perms.is_admin(user):
        where.append("l.owner_id = %s")
        params.append(user["id"])
    d = parse_days(days)
    if d == "today":
        where.append("l.created_at >= CURDATE()")
    elif d is not None:
        where.append("l.created_at >= NOW() - INTERVAL %s DAY")
        params.append(int(d))
    if env_id:
        where.append("l.env_id = %s")
        params.append(env_id)
    if status == "failed":
        # failed 口径：终态 failed，或存在 fail/setup_fail 轮次
        where.append(
            "(l.status = 'failed' OR EXISTS ("
            "  SELECT 1 FROM jobs fj WHERE fj.loop_id = l.id "
            "  AND fj.status IN ('fail', 'setup_fail')))"
        )
    elif status in _LOOP_STATUSES:
        where.append("l.status = %s")
        params.append(status)
    sql = _LOOP_SELECT
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY l.created_at DESC, l.id DESC LIMIT %s OFFSET %s"
    params += [int(limit), int(offset)]
    return pool.query(sql, tuple(params))


def _jobs_for_loops(loop_ids: list[str]) -> dict[str, list[dict]]:
    """批量取 loop 的 jobs 并 LEFT JOIN runs（passed/total/has 依据/dut_version）。"""
    if not loop_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(loop_ids))
    rows = pool.query(
        f"SELECT j.*, r.outcome, r.passed, r.total, r.dut_version "
        f"FROM jobs j LEFT JOIN runs r ON r.run_id = j.run_id "
        f"WHERE j.loop_id IN ({placeholders}) "
        f"ORDER BY j.iteration, j.id",
        tuple(loop_ids),
    )
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["loop_id"], []).append(row)
    return grouped


def _get_loop_row(loop_id: str) -> dict | None:
    return pool.query_one(_LOOP_SELECT + "WHERE l.id = %s", (loop_id,))


# ------------------------------------------------------------------ views

def _job_view(job: dict) -> dict:
    has_run = job.get("outcome") is not None  # runs 行存在（已 ingest）
    return {
        "iteration": job.get("iteration"),
        "loop_id": job.get("loop_id"),
        "run_id": job.get("run_id"),
        "status": job.get("status"),
        "passed": job.get("passed") if has_run and job.get("total") else None,
        "total": job.get("total") if has_run and job.get("total") else None,
        "started_at": fmt_dt(job.get("started_at")),
        "ended_at": fmt_dt(job.get("ended_at")),
        "job_duration_s": job.get("job_duration_s"),
        "exit_code": job.get("exit_code"),
        "failed_reason": job.get("failed_reason") or "",
        "has_artifacts": has_run,
        "has_summary": has_run,
    }


def _loop_view(row: dict, jobs: list[dict], *, include_lock: bool = True) -> dict:
    passed = sum(1 for j in jobs if j["status"] == "pass")
    failed = sum(1 for j in jobs if j["status"] in ("fail", "setup_fail"))
    dut_model = next(
        (j.get("dut_version") for j in reversed(jobs) if j.get("dut_version")), None
    )
    failed_reason = next(
        (
            j.get("failed_reason")
            for j in reversed(jobs)
            if j["status"] in ("fail", "setup_fail") and j.get("failed_reason")
        ),
        None,
    )
    out = {
        "id": row["id"],
        "loop_id": row["id"],
        "owner_name": row.get("owner_name"),
        "env_id": row.get("env_id"),
        "env_name": row.get("env_name"),
        "product": row.get("product"),
        "suite": row.get("suite"),
        "test": row.get("test"),
        "git_ref": row.get("git_ref"),
        "source": row.get("source"),
        "firmware_branch": row.get("firmware_branch"),
        "firmware_build": row.get("firmware_build"),
        "headless": bool(row.get("headless")),
        "pause_on_fail": bool(row.get("pause_on_fail")),
        "repeat_total": row.get("repeat_total"),
        "iterations": len(jobs),
        "passed_iters": passed,
        "fail_iters": failed,
        "status": row.get("status"),
        "created_at": fmt_dt(row.get("created_at")),
        "ended_at": fmt_dt(row.get("ended_at")),
        "stop_reason": row.get("stop_reason") or "",
        "failed_reason": failed_reason or "",
        "dut_model": dut_model,
        "iteration_statuses": [
            {"iteration": j["iteration"], "status": j["status"]} for j in jobs
        ],
        "jobs": [_job_view(j) for j in jobs],
    }
    if include_lock:
        out["env_lock"] = env_lock_view(row.get("env_relpath"))
    return out


def _loop_or_404(loop_id: str, user: dict) -> dict:
    """取 loop 并校验 owner/admin；404 / 403。"""
    row = _get_loop_row(loop_id)
    if row is None:
        raise HTTPException(status_code=404, detail="loop not found")
    if not perms.can_access_owner(user, row.get("owner_id")):
        raise HTTPException(status_code=403, detail="forbidden")
    return row


# ----------------------------------------------------------------- routes

@router.get("/loops")
def list_loops(
    days: str = "all",
    env_id: str = "",
    status: str = "",
    offset: int = 0,
    limit: int = 200,
    user: dict = Depends(get_current_user),
) -> list[dict]:
    offset = max(parse_int(offset, 0) or 0, 0)
    limit = min(max(parse_int(limit, 200) or 200, 1), 500)
    rows = _list_loop_rows(user, days, env_id, status, offset, limit)
    jobs_map = _jobs_for_loops([r["id"] for r in rows])
    return [_loop_view(r, jobs_map.get(r["id"], [])) for r in rows]


@router.get("/loops/{loop_id}")
def get_loop(loop_id: str, user: dict = Depends(get_current_user)) -> dict:
    row = _loop_or_404(loop_id, user)
    jobs = _jobs_for_loops([loop_id]).get(loop_id, [])
    return _loop_view(row, jobs)


@router.get("/loops/{loop_id}/status")
def get_loop_status(loop_id: str, user: dict = Depends(get_current_user)) -> dict:
    """轻量视图（2-5s 轮询）：与详情同构但省 env_lock 文件 IO；无权返回 {loop: null}。"""
    row = _get_loop_row(loop_id)
    if row is None or not perms.can_access_owner(user, row.get("owner_id")):
        return {"loop": None}
    jobs = _jobs_for_loops([loop_id]).get(loop_id, [])
    return {"loop": _loop_view(row, jobs, include_lock=False)}


@router.post("/run", status_code=201)
def run(body: RunIn, user: dict = Depends(get_current_user)) -> dict:
    manager = get_job_manager()

    env_row = pool.query_one(
        "SELECT * FROM environments WHERE id = %s", (body.env_id,)
    )
    if env_row is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    if env_row.get("disabled"):
        raise HTTPException(status_code=400, detail="环境已停用，不能运行")
    if not perms.can_operate_env(user, body.env_id):
        raise HTTPException(status_code=403, detail="forbidden")

    params = {
        "product": (body.product or "").strip(),
        "suite": (body.suite or "").strip(),
        "test": (body.test or "").strip(),
        "git_ref": body.git_ref,
        "headless": bool(body.headless),
        "branch": body.branch,
        "build": body.build,
        "pause_on_fail": bool(body.pause_on_fail),
        "source": body.source if body.source in ("repo", "upload") else "repo",
    }
    if params["product"] not in PRODUCTS:
        raise HTTPException(
            status_code=400,
            detail=f"product 必须是：{', '.join(PRODUCTS)}",
        )

    overlays: list[tuple[str, Path]] = []
    if params["source"] == "upload":
        up = pool.query_one(
            "SELECT * FROM uploads WHERE id = %s", (body.upload_id or "",)
        )
        if up is None:
            raise HTTPException(status_code=404, detail="上传件不存在")
        if not perms.can_access_owner(user, up.get("owner_id")):
            raise HTTPException(status_code=403, detail="forbidden")
        # 我的测试：suite 用名称（去扩展名）、script 用 overlay 相对路径
        #（= 上传文件名；DB relpath 是 '<user>/<uid>/<name>' 存储路径，不能直接当 CLI 参数）
        rel_name = Path(str(up["relpath"])).name
        if up["kind"] == "suite":
            params["suite"] = Path(str(up["name"])).stem
        else:
            params["test"] = rel_name
        overlays = [(rel_name, upload_abs_path(up))]

    if not params["suite"] and not params["test"]:
        raise HTTPException(status_code=400, detail="suite / test 至少填一个")

    repeat = body.repeat if body.repeat is not None else 1
    if repeat < 0:
        raise HTTPException(status_code=400, detail="repeat 不能为负数（0=无限）")

    try:
        result = manager.start(
            user=user,
            env_row=env_row,
            params=params,
            repeat=int(repeat),
            overlays=overlays,
        )
    except LoopStartError as exc:
        raise HTTPException(
            status_code=409,
            detail={"detail": str(exc), "holder": exc.holder, "error": str(exc)},
        ) from exc
    return {
        "loop_id": result["loop_id"],
        "command": result["command"],
        "repeat": result["repeat"],
    }


@router.post("/loops/{loop_id}/stop")
def stop_loop(loop_id: str, user: dict = Depends(get_current_user)) -> dict:
    _loop_or_404(loop_id, user)
    try:
        ok, message = get_job_manager().stop(loop_id, user=user)
    except LoopStopError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": bool(ok), "message": message}
