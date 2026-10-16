"""loops / jobs 表的数据访问层（DAO）。

* 只依赖 app.db.pool，不 import 任何 api / core 模块（避免循环依赖）；
  app.core.loop_runner / app.core.job_manager 调用本模块。
* 时间一律用 SQL 端 NOW(3)（DB 时区为准），不传 Python datetime，
  与 users.py 风格一致。
* 语义对照原 webui/db.py 的同名函数；新 schema 差异：
  - jobs 表不再有 passed/total（归 runs 表，由 T5 ingest 写入）；
  - loops.status 枚举为 running/done/stopped/failed（无 paused）。
"""

from __future__ import annotations

from app.db import pool

_LOOP_JOIN = (
    "SELECT l.*, u.username AS owner_name, e.name AS env_name "
    "FROM loops l "
    "JOIN users u ON u.id = l.owner_id "
    "LEFT JOIN environments e ON e.id = l.env_id "
)


# ------------------------------------------------------------------ loops

def insert_loop(
    *,
    loop_id: str,
    owner_id: int,
    env_id: str | None,
    product: str | None,
    suite: str | None,
    test: str | None,
    git_ref: str | None,
    source: str = "repo",
    firmware_branch: str | None = None,
    firmware_build: str | None = None,
    headless: bool = False,
    pause_on_fail: bool = False,
    repeat_total: int = 1,
    command: str | None = None,
) -> None:
    pool.execute(
        """
        INSERT INTO loops
            (id, owner_id, env_id, product, suite, test, git_ref, source,
             firmware_branch, firmware_build, headless, pause_on_fail,
             repeat_total, status, created_at, command)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'running', NOW(3), %s)
        """,
        (
            loop_id, owner_id, env_id, product, suite, test, git_ref, source,
            firmware_branch, firmware_build, int(bool(headless)),
            int(bool(pause_on_fail)), int(repeat_total or 1), command,
        ),
    )


def get_loop(loop_id: str) -> dict | None:
    return pool.query_one(_LOOP_JOIN + "WHERE l.id = %s", (loop_id,))


def list_loops(owner_id: int | None = None, limit: int = 200) -> list[dict]:
    sql = _LOOP_JOIN
    params: list = []
    if owner_id is not None:
        sql += "WHERE l.owner_id = %s "
        params.append(owner_id)
    sql += "ORDER BY l.created_at DESC LIMIT %s"
    params.append(limit)
    return pool.query(sql, tuple(params))


def get_running_loops() -> list[dict]:
    """全部 status='running' 的 loop（含 env relpath，供孤儿回收定位锁目录）。"""
    return pool.query(
        "SELECT l.*, e.relpath AS env_relpath "
        "FROM loops l LEFT JOIN environments e ON e.id = l.env_id "
        "WHERE l.status = 'running' "
        "ORDER BY l.created_at",
    )


def update_loop_status(
    loop_id: str,
    status: str,
    *,
    stop_reason: str | None = None,
) -> None:
    """置终态：ended_at=NOW(3)；stop_reason 截断到 255 字符（VARCHAR(255)）。"""
    if status not in ("running", "done", "stopped", "failed"):
        raise ValueError(f"非法 loops.status: {status}")
    pool.execute(
        "UPDATE loops SET status = %s, ended_at = NOW(3), stop_reason = %s "
        "WHERE id = %s",
        (status, (stop_reason or "")[:255] or None, loop_id),
    )


# ------------------------------------------------------------------- jobs

def insert_job(
    *,
    job_id: str,
    loop_id: str,
    owner_id: int | None,
    env_id: str | None,
    iteration: int,
    git_ref: str | None = None,
) -> None:
    """插入 running 状态的 job 行，started_at=NOW(3)。"""
    pool.execute(
        """
        INSERT INTO jobs
            (id, loop_id, owner_id, env_id, run_id, iteration, status,
             started_at, git_ref)
        VALUES (%s, %s, %s, %s, NULL, %s, 'running', NOW(3), %s)
        """,
        (job_id, loop_id, owner_id, env_id, iteration, git_ref),
    )


def update_job_result(
    job_id: str,
    *,
    status: str,
    run_id: str | None = None,
    exit_code: int | None = None,
    job_duration_s: float | None = None,
    failed_reason: str | None = None,
    job_setup_failed: bool | None = None,
) -> None:
    """写一轮迭代结果并置 ended_at=NOW(3)。

    run_id/exit_code/duration/reason 为 None 时不动对应列（保持 NULL）。
    passed/total 不在此写——归 runs 表（T5 ingest）。
    """
    if status not in ("running", "pass", "fail", "setup_fail", "broken", "stopped"):
        raise ValueError(f"非法 jobs.status: {status}")
    sets = ["status = %s", "ended_at = NOW(3)"]
    params: list = [status]
    if run_id is not None:
        sets.append("run_id = %s")
        params.append(run_id)
    if exit_code is not None:
        sets.append("exit_code = %s")
        params.append(exit_code)
    if job_duration_s is not None:
        sets.append("job_duration_s = %s")
        params.append(job_duration_s)
    if failed_reason is not None:
        sets.append("failed_reason = %s")
        params.append(failed_reason)
    if job_setup_failed is not None:
        sets.append("job_setup_failed = %s")
        params.append(1 if job_setup_failed else 0)
    params.append(job_id)
    pool.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = %s", tuple(params))


def get_job(job_id: str) -> dict | None:
    return pool.query_one("SELECT * FROM jobs WHERE id = %s", (job_id,))


def get_job_by_run_id(run_id: str) -> dict | None:
    return pool.query_one("SELECT * FROM jobs WHERE run_id = %s", (run_id,))


def list_jobs_for_loop(loop_id: str) -> list[dict]:
    return pool.query(
        "SELECT * FROM jobs WHERE loop_id = %s ORDER BY iteration", (loop_id,)
    )
