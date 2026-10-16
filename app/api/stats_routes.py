"""业务路由：数据看板统计 GET /api/stats?days=7|14|30。

契约权威 = frontend/js/mock-data.js 的 mockStats（views/dashboard.js 消费）：
  {jobs, loops, running, pass_rate(0-1), failed_jobs, broken_jobs,
   trend: [{date, pass_rate}], fail_cases: [{name, count}],
   loop_bars: [{created_at 'YYYY-MM-DD HH:MM', suite, iterations: [{iteration, status}]}]}

聚合主体走 T5 dao（stats_summary / pass_rate_trend / top_failed_cases）；
loops 数 / running 数与 loop_bars 的 per-loop 轮次色条 dao 未覆盖，
在本模块用 pool 补充查询（不扫盘，全部走 runs/jobs/loops 表）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.common import fmt_dt
from app.api.deps import get_current_user
from app.db import pool
from app.db.dao import runs as runs_dao

router = APIRouter(prefix="/api")


def _loop_bars(days: int, limit: int = 8) -> list[dict]:
    """按 loop 聚合的 iteration 色条（最新在前，最多 limit 条）。"""
    rows = pool.query(
        "SELECT l.id, l.created_at, l.suite, j.iteration, j.status "
        "FROM loops l JOIN jobs j ON j.loop_id = l.id "
        "WHERE l.created_at >= NOW() - INTERVAL %s DAY "
        "ORDER BY l.created_at DESC, j.iteration ASC "
        "LIMIT %s",
        (days, max(limit, 1) * 50),
    )
    grouped: dict[str, dict] = {}
    for row in rows:
        entry = grouped.setdefault(
            row["id"],
            {
                "created_at": fmt_dt(row.get("created_at"), "%Y-%m-%d %H:%M"),
                "suite": row.get("suite") or "",
                "iterations": [],
            },
        )
        entry["iterations"].append(
            {"iteration": row["iteration"], "status": row["status"]}
        )
    return list(grouped.values())[:limit]


@router.get("/stats")
def stats(days: int = 14, user: dict = Depends(get_current_user)) -> dict:
    days = days if days in (7, 14, 30) else 14

    summary = runs_dao.stats_summary(days) or {}
    loops_count = pool.query_one(
        "SELECT COUNT(*) AS n FROM loops "
        "WHERE created_at >= NOW() - INTERVAL %s DAY",
        (days,),
    )
    running_count = pool.query_one(
        "SELECT COUNT(*) AS n FROM loops WHERE status = 'running'"
    )

    trend = [
        {
            "date": fmt_dt(t.get("day"), "%Y-%m-%d"),
            "pass_rate": round(float(t.get("avg_pass_rate") or 0) / 100.0, 4),
        }
        for t in runs_dao.pass_rate_trend(days)
    ]
    fail_cases = [
        {"name": c["name"], "count": int(c["fail_count"])}
        for c in runs_dao.top_failed_cases(days, 10)
    ]

    return {
        "jobs": int(summary.get("runs") or 0),
        "loops": int(loops_count["n"]) if loops_count else 0,
        "running": int(running_count["n"]) if running_count else 0,
        "pass_rate": round(float(summary.get("avg_pass_rate") or 0) / 100.0, 4),
        # failed_jobs = case 失败的 job；broken = Job setup 失败 + 产物损坏
        "failed_jobs": int(summary.get("fail_runs") or 0),
        "broken_jobs": int(summary.get("setup_fail_runs") or 0)
        + int(summary.get("broken_runs") or 0),
        "trend": trend,
        "fail_cases": fail_cases,
        "loop_bars": _loop_bars(days),
    }
