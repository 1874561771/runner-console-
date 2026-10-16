"""runs / cases / case_failures / artifact_files 表的数据访问层（T5）。

* 只依赖 app.db.pool，不 import 任何 api / core 模块（与 loops.py 约定一致）；
  app.ingest.run_ingest 与 T7 的 api 层调用本模块。
* 表结构以 app/db/schema.sql 为权威；outcome/status/kind 写入前做白名单
  校验，非法值回落到默认枚举，避免 ENUM 不匹配直接报错。
* 事务：写函数支持传入已开启的 connection（conn=...，commit/rollback 由
  调用方负责）；不传 conn 则各自开短事务。ingest_run 用它把 runs 主行 +
  三张明细表 + jobs 回填包进同一事务。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from app.db import pool

# ------------------------------------------------------------------ 枚举白名单（与 schema.sql ENUM 严格一致）

_RUN_OUTCOMES = ("pass", "fail", "broken", "setup_fail", "unknown")
_CASE_STATUSES = ("pass", "fail", "broken", "skipped")
_FAILURE_KINDS = ("job_setup", "case_setup", "main", "case_teardown")
_ARTIFACT_KINDS = (
    "job_log", "summary_html", "summary_json", "run_meta", "case_log",
    "screenshot", "support_tgz", "config", "other",
)


def _enum(value, allowed: tuple, default: str) -> str:
    return value if value in allowed else default


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float | None = None):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@contextmanager
def _conn_or(conn) -> Iterator:
    """有 conn 用外层事务的连接；没有则开短事务（自动 commit/rollback）。"""
    if conn is not None:
        yield conn
        return
    with pool.connection() as c:
        yield c


# ------------------------------------------------------------------ runs 主行

_RUN_COLS = (
    "run_id", "job_id", "loop_id", "product", "dut_model", "dut_version",
    "outcome", "passed", "failed", "broken", "total", "pass_rate",
    "failed_reason", "job_duration_s", "branch", "build", "env_name",
    "git_ref", "host", "exit_code", "artifacts_relpath", "started_at",
    "ended_at",
)


def _run_row(run: dict) -> tuple:
    total = _to_int(run.get("total"))
    pass_rate = _to_float(run.get("pass_rate"), None)
    if pass_rate is None:
        pass_rate = 100.0 * _to_int(run.get("passed")) / total if total > 0 else 0.0
    return (
        run.get("run_id"),
        run.get("job_id"),
        run.get("loop_id"),
        run.get("product"),
        run.get("dut_model"),
        run.get("dut_version"),
        _enum(run.get("outcome"), _RUN_OUTCOMES, "unknown"),
        _to_int(run.get("passed")),
        _to_int(run.get("failed")),
        _to_int(run.get("broken")),
        total,
        pass_rate,
        run.get("failed_reason"),
        _to_float(run.get("job_duration_s"), None),
        run.get("branch"),
        run.get("build"),
        run.get("env_name"),
        run.get("git_ref"),
        run.get("host"),
        _to_int(run.get("exit_code"), 0) if run.get("exit_code") is not None else None,
        run.get("artifacts_relpath") or run.get("run_id") or "",
        run.get("started_at") or datetime.now(),
        run.get("ended_at"),
    )


def upsert_run(run: dict, *, conn=None) -> None:
    """INSERT ... ON DUPLICATE KEY UPDATE 全字段（run_id 除外），ingested_at 刷新。

    run: 字段名为 runs 表列名（多余键忽略，缺省键按 NOT NULL 约束补默认值）。
    """
    cols = ", ".join(_RUN_COLS)
    placeholders = ", ".join(["%s"] * len(_RUN_COLS))
    updates = ", ".join(f"{c} = VALUES({c})" for c in _RUN_COLS[1:])
    with _conn_or(conn) as c, c.cursor() as cur:
        cur.execute(
            f"INSERT INTO runs ({cols}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {updates}, ingested_at = NOW(3)",
            _run_row(run),
        )


def get_run(run_id: str) -> dict | None:
    return pool.query_one("SELECT * FROM runs WHERE run_id = %s", (run_id,))


# ------------------------------------------------------------------ cases

_CASE_COLS = ("run_id", "name", "seq", "status", "duration_s", "message",
              "case_relpath")


def _case_row(run_id: str, case: dict) -> tuple:
    return (
        run_id,
        str(case.get("name") or "")[:255],
        _to_int(case.get("seq")),
        _enum(case.get("status"), _CASE_STATUSES, "skipped"),
        _to_float(case.get("duration_s"), None),
        case.get("message"),
        str(case["case_relpath"])[:512] if case.get("case_relpath") else None,
    )


def insert_case(run_id: str, case: dict, *, conn=None) -> int:
    """单条插入，返回自增 id。seq 冲突（UNIQUE run_id+name+seq）由调用方处理。"""
    cols = ", ".join(_CASE_COLS)
    placeholders = ", ".join(["%s"] * len(_CASE_COLS))
    with _conn_or(conn) as c, c.cursor() as cur:
        cur.execute(
            f"INSERT INTO cases ({cols}) VALUES ({placeholders})",
            _case_row(run_id, case),
        )
        return cur.lastrowid


def replace_cases(run_id: str, cases: list[dict], *, conn=None) -> int:
    """事务内先删后插（保 UNIQUE(run_id, name,seq)），幂等可重跑。返回插入行数。"""
    rows = [_case_row(run_id, c) for c in (cases or [])]
    cols = ", ".join(_CASE_COLS)
    placeholders = ", ".join(["%s"] * len(_CASE_COLS))
    with _conn_or(conn) as c, c.cursor() as cur:
        cur.execute("DELETE FROM cases WHERE run_id = %s", (run_id,))
        if rows:
            cur.executemany(
                f"INSERT INTO cases ({cols}) VALUES ({placeholders})", rows
            )
        return len(rows)


def list_cases(run_id: str) -> list[dict]:
    return pool.query(
        "SELECT * FROM cases WHERE run_id = %s ORDER BY seq, id", (run_id,)
    )


# ------------------------------------------------------------------ case_failures

_FAILURE_COLS = ("run_id", "case_name", "kind", "message", "log_relpath")


def _failure_row(run_id: str, f: dict) -> tuple:
    return (
        run_id,
        str(f["case_name"])[:255] if f.get("case_name") else None,
        _enum(f.get("kind"), _FAILURE_KINDS, "main"),
        str(f.get("message") or ""),  # TEXT NOT NULL，兜底空串
        str(f["log_relpath"])[:512] if f.get("log_relpath") else None,
    )


def replace_case_failures(run_id: str, failures: list[dict], *, conn=None) -> int:
    """事务内先删后插，幂等可重跑。返回插入行数。"""
    rows = [_failure_row(run_id, f) for f in (failures or [])]
    cols = ", ".join(_FAILURE_COLS)
    placeholders = ", ".join(["%s"] * len(_FAILURE_COLS))
    with _conn_or(conn) as c, c.cursor() as cur:
        cur.execute("DELETE FROM case_failures WHERE run_id = %s", (run_id,))
        if rows:
            cur.executemany(
                f"INSERT INTO case_failures ({cols}) VALUES ({placeholders})", rows
            )
        return len(rows)


def list_case_failures(run_id: str) -> list[dict]:
    return pool.query(
        "SELECT * FROM case_failures WHERE run_id = %s ORDER BY id", (run_id,)
    )


# ------------------------------------------------------------------ artifact_files

_ARTIFACT_COLS = ("run_id", "relpath", "kind", "size_bytes", "case_name")


def _artifact_row(run_id: str, a: dict) -> tuple:
    return (
        run_id,
        str(a.get("relpath") or "")[:1024],
        _enum(a.get("kind"), _ARTIFACT_KINDS, "other"),
        _to_int(a.get("size_bytes")),
        str(a["case_name"])[:255] if a.get("case_name") else None,
    )


def replace_artifact_files(run_id: str, files: list[dict], *, conn=None) -> int:
    """事务内先删后插（保 UNIQUE(run_id, relpath)），幂等可重跑。返回插入行数。"""
    rows = [_artifact_row(run_id, f) for f in (files or [])]
    cols = ", ".join(_ARTIFACT_COLS)
    placeholders = ", ".join(["%s"] * len(_ARTIFACT_COLS))
    with _conn_or(conn) as c, c.cursor() as cur:
        cur.execute("DELETE FROM artifact_files WHERE run_id = %s", (run_id,))
        if rows:
            cur.executemany(
                f"INSERT INTO artifact_files ({cols}) VALUES ({placeholders})", rows
            )
        return len(rows)


def list_artifacts(run_id: str, kind: str | None = None) -> list[dict]:
    if kind is not None:
        return pool.query(
            "SELECT * FROM artifact_files WHERE run_id = %s AND kind = %s"
            " ORDER BY relpath",
            (run_id, _enum(kind, _ARTIFACT_KINDS, "other")),
        )
    return pool.query(
        "SELECT * FROM artifact_files WHERE run_id = %s ORDER BY relpath",
        (run_id,),
    )


# ------------------------------------------------------------------ list_runs（JOIN 归属，供 T7）

_RUNS_JOIN = (
    "SELECT r.*, "
    "j.iteration AS job_iteration, j.status AS job_status, "
    "j.owner_id, j.env_id, "
    "u.username AS owner_name, "
    "e.name AS environment_name, "
    "l.product AS loop_product, l.suite AS loop_suite, l.test AS loop_test "
    "FROM runs r "
    "LEFT JOIN jobs j ON j.id = r.job_id "
    "LEFT JOIN users u ON u.id = j.owner_id "
    "LEFT JOIN environments e ON e.id = j.env_id "
    "LEFT JOIN loops l ON l.id = COALESCE(j.loop_id, r.loop_id) "
)


def list_runs(
    *,
    owner_id: int | None = None,
    env_id: str | None = None,
    loop_id: str | None = None,
    days: int | None = None,
    offset: int = 0,
    limit: int = 200,
) -> list[dict]:
    """列表页查询：JOIN jobs/users/environments/loops 取归属信息。

    过滤：owner_id / env_id 取 jobs 侧归属（run 由 job 产生）；
    loop_id 兼容 runs.loop_id（jobs 行可能被清理）；days = 最近 N 天
    （按 runs.started_at）。按开始时间倒序分页。
    """
    where: list[str] = []
    params: list = []
    if owner_id is not None:
        where.append("j.owner_id = %s")
        params.append(owner_id)
    if env_id is not None:
        where.append("j.env_id = %s")
        params.append(env_id)
    if loop_id is not None:
        where.append("COALESCE(j.loop_id, r.loop_id) = %s")
        params.append(loop_id)
    if days:
        where.append("r.started_at >= NOW() - INTERVAL %s DAY")
        params.append(int(days))
    sql = _RUNS_JOIN
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY r.started_at DESC, r.run_id DESC LIMIT %s OFFSET %s"
    params += [int(limit), int(max(offset, 0))]
    return pool.query(sql, tuple(params))


# ------------------------------------------------------------------ 统计聚合（供 T7 /api/stats）

def stats_summary(days: int = 7) -> dict:
    """近 N 天总体概览：run 数按 outcome 分布 + 用例计数 + 平均通过率。"""
    return pool.query_one(
        """
        SELECT COUNT(*) AS runs,
               CAST(COALESCE(SUM(outcome = 'pass'), 0) AS SIGNED) AS pass_runs,
               CAST(COALESCE(SUM(outcome = 'fail'), 0) AS SIGNED) AS fail_runs,
               CAST(COALESCE(SUM(outcome = 'broken'), 0) AS SIGNED) AS broken_runs,
               CAST(COALESCE(SUM(outcome = 'setup_fail'), 0) AS SIGNED) AS setup_fail_runs,
               CAST(COALESCE(SUM(outcome = 'unknown'), 0) AS SIGNED) AS unknown_runs,
               CAST(COALESCE(AVG(pass_rate), 0) AS DOUBLE) AS avg_pass_rate,
               CAST(COALESCE(SUM(passed), 0) AS SIGNED) AS cases_passed,
               CAST(COALESCE(SUM(failed), 0) AS SIGNED) AS cases_failed,
               CAST(COALESCE(SUM(broken), 0) AS SIGNED) AS cases_broken,
               CAST(COALESCE(SUM(total), 0) AS SIGNED) AS cases_total
        FROM runs
        WHERE started_at >= NOW() - INTERVAL %s DAY
        """,
        (int(days),),
    ) or {}


def pass_rate_trend(days: int = 14) -> list[dict]:
    """按日聚合通过率趋势（折线图：day / runs / pass_runs / avg_pass_rate）。"""
    return pool.query(
        """
        SELECT DATE(started_at) AS day,
               COUNT(*) AS runs,
               CAST(COALESCE(SUM(outcome = 'pass'), 0) AS SIGNED) AS pass_runs,
               CAST(COALESCE(AVG(pass_rate), 0) AS DOUBLE) AS avg_pass_rate
        FROM runs
        WHERE started_at >= NOW() - INTERVAL %s DAY
        GROUP BY day
        ORDER BY day
        """,
        (int(days),),
    )


def top_failed_cases(days: int = 7, limit: int = 10) -> list[dict]:
    """近 N 天失败次数最多的用例（排行：name / fail_count / broken_count）。"""
    return pool.query(
        """
        SELECT c.name,
               COUNT(*) AS fail_count,
               CAST(COALESCE(SUM(c.status = 'broken'), 0) AS SIGNED) AS broken_count,
               MAX(r.run_id) AS last_run_id,
               MAX(r.started_at) AS last_seen
        FROM cases c
        JOIN runs r ON r.run_id = c.run_id
        WHERE c.status IN ('fail', 'broken')
          AND r.started_at >= NOW() - INTERVAL %s DAY
        GROUP BY c.name
        ORDER BY fail_count DESC, c.name
        LIMIT %s
        """,
        (int(days), int(limit)),
    )


def loop_bars(days: int = 7) -> list[dict]:
    """近 N 天按 loop 聚合的柱状数据（loop_id / outcome 分布 / 平均通过率）。"""
    return pool.query(
        """
        SELECT r.loop_id,
               MAX(l.product) AS product,
               MAX(l.suite) AS suite,
               COUNT(*) AS runs,
               CAST(COALESCE(SUM(r.outcome = 'pass'), 0) AS SIGNED) AS pass_runs,
               CAST(COALESCE(SUM(r.outcome = 'fail'), 0) AS SIGNED) AS fail_runs,
               CAST(COALESCE(SUM(r.outcome = 'setup_fail'), 0) AS SIGNED) AS setup_fail_runs,
               CAST(COALESCE(SUM(r.outcome = 'broken'), 0) AS SIGNED) AS broken_runs,
               CAST(COALESCE(AVG(r.pass_rate), 0) AS DOUBLE) AS avg_pass_rate
        FROM runs r
        LEFT JOIN loops l ON l.id = r.loop_id
        WHERE r.started_at >= NOW() - INTERVAL %s DAY
          AND r.loop_id IS NOT NULL
        GROUP BY r.loop_id
        ORDER BY runs DESC, r.loop_id
        LIMIT 20
        """,
        (int(days),),
    )
