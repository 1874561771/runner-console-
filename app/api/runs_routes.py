"""业务路由：runs 列表 / 详情 / joblog / summary.html。

契约权威 = frontend/js/api.js mockRoutes + mock-data.js：
* GET /api/runs?loop_id=&env_id=&days=&outcome=&offset=&limit
* GET /api/runs/{run_id}                  详情 + cases + failures + 产物统计
* GET /api/runs/{run_id}/joblog?tail=400  产物 job.log 尾部（text/plain）
* GET /api/runs/{run_id}/summary.html     产物汇总页（text/html，浏览器直开）

说明：
* 数据全走 T5 dao（runs/cases/case_failures/artifact_files），不扫盘；
  列表的 outcome 过滤与 has_summary 列 dao.list_runs 未覆盖，在本模块
  用 pool 补充查询（JOIN 口径与 dao._RUNS_JOIN 一致，另加 loop 兜底归属）。
* run 归属 = job.owner_id 优先，否则 loop.owner_id（legacy run）；环境同理；
  owner 本人、admin 与该环境的授权用户（viewer/operator/env owner）可查看。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse

from app.api.common import artifacts_root, fmt_dt, parse_int
from app.api.deps import maybe_current_user
from app.auth import perms
from app.db import pool
from app.db.dao import runs as runs_dao

router = APIRouter(prefix="/api")

# JOIN 口径对照 dao._RUNS_JOIN，差异：
# 1) 归属列 COALESCE(j.owner_id, l.owner_id)（legacy run 回落 loop 归属）
# 2) 附加 summary_files 子查询（has_summary 契约字段，避免逐 run 二次查询）
_RUNS_SELECT = (
    "SELECT r.*, j.iteration AS job_iteration, j.status AS job_status, "
    "COALESCE(j.owner_id, l.owner_id) AS owner_id, j.env_id, "
    "u.username AS owner_name, e.name AS environment_name, "
    "COALESCE(j.loop_id, r.loop_id) AS eff_loop_id, "
    "(SELECT COUNT(*) FROM artifact_files af "
    "  WHERE af.run_id = r.run_id AND af.kind = 'summary_html') AS summary_files "
    "FROM runs r "
    "LEFT JOIN jobs j ON j.id = r.job_id "
    "LEFT JOIN loops l ON l.id = COALESCE(j.loop_id, r.loop_id) "
    "LEFT JOIN users u ON u.id = COALESCE(j.owner_id, l.owner_id) "
    "LEFT JOIN environments e ON e.id = j.env_id "
)


# ------------------------------------------------------------------ helper

def run_scope(run_id: str) -> tuple[int | None, str | None]:
    """run 归属 (owner_id, env_id)；run 不存在返回 (None, None)。"""
    row = pool.query_one(
        "SELECT COALESCE(j.owner_id, l.owner_id) AS owner_id, "
        "COALESCE(j.env_id, l.env_id) AS env_id "
        "FROM runs r "
        "LEFT JOIN jobs j ON j.id = r.job_id "
        "LEFT JOIN loops l ON l.id = COALESCE(j.loop_id, r.loop_id) "
        "WHERE r.run_id = %s",
        (run_id,),
    )
    return (row["owner_id"], row["env_id"]) if row else (None, None)


def get_run_or_404(run_id: str, user: dict | None) -> dict:
    """校验 run 存在且当前用户可查看（owner / admin / 环境授权用户）；404 / 403。
    供本模块与 cases_routes / files_routes 复用。"""
    row = runs_dao.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    owner_id, env_id = run_scope(run_id)
    if not perms.can_view_resource(user, owner_id, env_id):
        raise HTTPException(status_code=403, detail="forbidden")
    return row


def _run_view(row: dict) -> dict:
    total = row.get("total") or 0
    has_summary = bool(row.get("summary_files"))
    return {
        "run_id": row["run_id"],
        "mtime": fmt_dt(row.get("ended_at") or row.get("started_at")),
        "status": row.get("outcome"),
        "passed": row.get("passed") if total else None,
        "failed": row.get("failed") if total else None,
        "broken": row.get("broken") if total else None,
        "total": total or None,
        "pass_rate": row.get("pass_rate"),
        "product": row.get("product"),
        "dut_model": row.get("dut_model"),
        "dut_version": row.get("dut_version"),
        "branch": row.get("branch"),
        "build": row.get("build"),
        "env_name": row.get("environment_name") or row.get("env_name"),
        "git_ref": row.get("git_ref"),
        "host": row.get("host"),
        "loop_id": row.get("eff_loop_id"),
        "iteration": row.get("job_iteration"),
        "owner_name": row.get("owner_name"),
        "job_duration_s": row.get("job_duration_s"),
        "failed_reason": row.get("failed_reason") or "",
        "has_summary": has_summary,
    }


# ------------------------------------------------------------------ routes

@router.get("/runs")
def list_runs(
    loop_id: str = "",
    env_id: str = "",
    days: str | None = None,
    outcome: str = "",
    offset: int = 0,
    limit: int = 200,
    user: dict | None = Depends(maybe_current_user),
) -> list[dict]:
    where: list[str] = []
    params: list = []
    if not perms.is_admin(user):
        scope_sql, scope_params = perms.visible_scope_sql(
            "COALESCE(j.owner_id, l.owner_id)", "COALESCE(j.env_id, l.env_id)", user
        )
        where.append(scope_sql)
        params.extend(scope_params)
    if loop_id:
        where.append("COALESCE(j.loop_id, r.loop_id) = %s")
        params.append(loop_id)
    if env_id:
        where.append("j.env_id = %s")
        params.append(env_id)
    days_int = parse_int(days)
    if days_int and days_int > 0:
        where.append("r.started_at >= NOW() - INTERVAL %s DAY")
        params.append(days_int)
    if outcome:
        where.append("r.outcome = %s")
        params.append(outcome)
    sql = _RUNS_SELECT
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    offset = max(parse_int(offset, 0) or 0, 0)
    limit = min(max(parse_int(limit, 200) or 200, 1), 500)
    sql += "ORDER BY r.started_at DESC, r.run_id DESC LIMIT %s OFFSET %s"
    params += [limit, offset]
    return [_run_view(r) for r in pool.query(sql, tuple(params))]


@router.get("/run-comparisons")
def compare_runs(
    base_run_id: str,
    target_run_id: str,
    user: dict | None = Depends(maybe_current_user),
) -> dict:
    """比较两个 run 的指标及用例状态变化。"""
    get_run_or_404(base_run_id, user)
    get_run_or_404(target_run_id, user)
    base_row = pool.query_one(_RUNS_SELECT + "WHERE r.run_id = %s", (base_run_id,))
    target_row = pool.query_one(_RUNS_SELECT + "WHERE r.run_id = %s", (target_run_id,))
    base_cases = {
        (row["name"], row.get("seq") or 0): row
        for row in runs_dao.list_cases(base_run_id)
    }
    target_cases = {
        (row["name"], row.get("seq") or 0): row
        for row in runs_dao.list_cases(target_run_id)
    }
    changes = {
        "regressions": [],
        "fixed": [],
        "unchanged_failures": [],
        "added": [],
        "removed": [],
        "other_changes": [],
    }
    failed_states = {"fail", "broken"}
    for key in sorted(base_cases.keys() | target_cases.keys()):
        base_case = base_cases.get(key)
        target_case = target_cases.get(key)
        item = {
            "name": key[0],
            "seq": key[1],
            "base_status": base_case and base_case["status"],
            "target_status": target_case and target_case["status"],
            "duration_delta_s": (
                round(
                    float(target_case.get("duration_s") or 0)
                    - float(base_case.get("duration_s") or 0),
                    3,
                )
                if base_case and target_case
                else None
            ),
        }
        if base_case is None:
            changes["added"].append(item)
        elif target_case is None:
            changes["removed"].append(item)
        elif base_case["status"] == "pass" and target_case["status"] in failed_states:
            changes["regressions"].append(item)
        elif base_case["status"] in failed_states and target_case["status"] == "pass":
            changes["fixed"].append(item)
        elif (
            base_case["status"] in failed_states
            and target_case["status"] in failed_states
        ):
            changes["unchanged_failures"].append(item)
        elif base_case["status"] != target_case["status"]:
            changes["other_changes"].append(item)

    def metric_delta(name: str) -> float:
        return round(
            float(target_row.get(name) or 0) - float(base_row.get(name) or 0), 3
        )

    return {
        "base": _run_view(base_row),
        "target": _run_view(target_row),
        "delta": {
            "pass_rate": metric_delta("pass_rate"),
            "duration_s": metric_delta("job_duration_s"),
            "passed": int(metric_delta("passed")),
            "failed": int(metric_delta("failed")),
            "broken": int(metric_delta("broken")),
        },
        "changes": changes,
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str, user: dict | None = Depends(maybe_current_user)) -> dict:
    get_run_or_404(run_id, user)
    row = pool.query_one(_RUNS_SELECT + "WHERE r.run_id = %s", (run_id,)) or {}
    cases = runs_dao.list_cases(run_id)
    failures = runs_dao.list_case_failures(run_id)
    artifacts = runs_dao.list_artifacts(run_id)
    by_kind: dict[str, int] = {}
    for a in artifacts:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
    out = _run_view(row)
    out.update(
        {
            "cases": cases,
            "failures": failures,
            "artifacts_by_kind": by_kind,
            "artifact_count": len(artifacts),
        }
    )
    return out


@router.get("/runs/{run_id}/joblog")
def run_joblog(
    run_id: str,
    tail: int = 400,
    user: dict | None = Depends(maybe_current_user),
) -> PlainTextResponse:
    get_run_or_404(run_id, user)
    path = artifacts_root() / run_id / "job.log"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="job.log 不存在（未生成或已清理）")
    tail_n = min(max(parse_int(tail, 400) or 400, 1), 2000)
    return PlainTextResponse("\n".join(_tail_lines(path, tail_n)))


def _tail_lines(path, n: int) -> list[str]:
    """读文件末尾 n 行（最多回溯 256KB，避免大文件整读）。"""
    size = path.stat().st_size
    with open(path, "rb") as fh:
        fh.seek(max(0, size - 262144))
        text = fh.read().decode("utf-8", errors="replace")
    lines = text.splitlines()
    if size > 262144 and lines:
        lines = lines[1:]  # 首行可能是截断的半行，丢弃
    return lines[-n:]


@router.get("/runs/{run_id}/summary.html")
def run_summary_html(run_id: str, user: dict | None = Depends(maybe_current_user)):
    """302 → /runs/{run_id}/summary.html（files_routes 提供）。

    summary.html 内的截图/case.log 引用是相对路径，浏览器按文档 URL 解析；
    若从 /api/runs/... 直出，相对路径会落到 /api/runs/<id>/firebox/... 404。
    跳到 /runs/<id>/ 前缀下，相对引用正好命中 files_routes 的产物路由。
    """
    get_run_or_404(run_id, user)
    return RedirectResponse(f"/runs/{run_id}/summary.html", status_code=302)
