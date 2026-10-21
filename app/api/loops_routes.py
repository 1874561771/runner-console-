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

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.api.common import (
    artifacts_root,
    env_lock_view,
    fmt_dt,
    parse_days,
    parse_int,
)
from app.api.deps import get_current_user
from app.auth import perms
from app.core import run_service
from app.core.job_manager import (
    LoopStopError,
    get_job_manager,
)
from app.db import pool
from app.schemas import RunIn

router = APIRouter(prefix="/api")

# 运行中实时解析：console 里的 case 状态行（runner 契约格式）
_LIVE_RUN_ID_RE = re.compile(r"Run id=(\S+)")
_LIVE_CASE_START_RE = re.compile(r"=====\s*CASE\s+(\S+)\s+=====")
_LIVE_RESULT_RE = re.compile(r"RESULT\s+(\S+)\s+->\s+(\w+)")
_LIVE_DURATION_RE = re.compile(r"CASE\s+(\S+)\s+duration=([\d.]+)s")
_LIVE_SETUP_FAIL_RE = re.compile(r"Case setup FAILED for (\S+)")

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
    # 参数校验 / cases→临时 suite / overlay 组装 / manager.start 全部在
    # run_service.do_start_run（与定时任务调度共用同一入口）
    try:
        result = run_service.do_start_run(user, body)
    except run_service.RunError as exc:
        detail: object = exc.detail
        if exc.status == 409:
            detail = {"detail": exc.detail, "holder": exc.holder, "error": exc.detail}
        raise HTTPException(status_code=exc.status, detail=detail) from exc
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


@router.get("/loops/{loop_id}/live-cases")
def loop_live_cases(loop_id: str, user: dict = Depends(get_current_user)) -> dict:
    """运行中实时解析：从 console 文本提取本轮 case 状态 + 当前 run 的材料清单。

    iteration 结束前的 case 结果不进 DB（ingest 在轮末才跑），但 console 里
    的 ===== CASE / RESULT / duration 行已含全部状态，材料文件也在边跑边
    落盘——这里解析出来供运行台概览实时显示，无需等整轮结束。
    """
    _loop_or_404(loop_id, user)
    manager = get_job_manager()
    # 全量读取：RUN_ID 行在文件头、前面的 case 会被大日志滚出尾部窗口，
    # 只取尾部会漏掉绝大部分 case（实测 14-case run 只剩 3 个）
    lines = manager.console_tail(loop_id, n=200000)

    run_id: str | None = None
    cases: dict = {}  # name -> {name, status, duration_s}（插入序 = 运行序）
    for line in lines:
        if (m := _LIVE_RUN_ID_RE.search(line)) and run_id is None:
            run_id = m.group(1)
        if m := _LIVE_CASE_START_RE.search(line):
            cases.setdefault(m.group(1), {"name": m.group(1), "status": "running"})
        if m := _LIVE_SETUP_FAIL_RE.search(line):
            cases.setdefault(m.group(1), {"name": m.group(1), "status": "running"})
            cases[m.group(1)]["status"] = "broken"
        if m := _LIVE_RESULT_RE.search(line):
            if m.group(1) in cases:
                cases[m.group(1)]["status"] = m.group(2).lower()
        if m := _LIVE_DURATION_RE.search(line):
            if m.group(1) in cases:
                try:
                    cases[m.group(1)]["duration_s"] = float(m.group(2))
                except ValueError:
                    pass

    artifacts: list[dict] = []
    if run_id:
        run_dir = artifacts_root() / run_id
        if run_dir.is_dir():
            from app.ingest.run_ingest import _scan_artifacts  # noqa: PLC0415

            artifacts = _scan_artifacts(run_dir)
    return {"run_id": run_id, "cases": list(cases.values()), "artifacts": artifacts}
