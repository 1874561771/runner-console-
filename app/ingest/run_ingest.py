"""产物入库（T5）：解析 artifacts/<run_id>/ 并写入 runs 及明细表。

调用点：app.core.loop_runner._maybe_ingest()，每轮 iteration 结束后：
    ingest_run(job_row, run_id, artifacts_dir)

职责：
1. 读 summary.json（缺失/坏 JSON/半写文件 → outcome='unknown' 兜底，不抛出）
   + run_meta.json（可选：host / started_at / cli_args 里的 branch、build 优先）。
2. upsert runs 主行；3. cases；4. case_failures；5. artifact_files（只 stat 不读
   内容）；6. 回填 jobs 行。全部包在同一个事务里（见 _ingest）。

失败处理：任何异常只记日志，并把 job 标 failed_reason='ingest pending: <err>'
（不抛给调用方，循环不中断）；后台任务可调 retry_pending_ingest() 补偿重试。

解析语义参照原 webui/server.py 的 load_summary_json / scan_run_dir 与
framework/common/run_summary.py 的 summary.json schema（T2 版本含
env_name / git_ref / host / exit_code）。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from app.config import PROJECT_ROOT, get_settings
from app.db import pool
from app.db.dao import runs as runs_dao

logger = logging.getLogger("runnerconsole.ingest")

# summary.json 的 outcome（run_summary.write_summary_html 产出）→ runs.outcome
_OUTCOME_MAP = {
    "PASS": "pass",
    "FAILED": "fail",
    "SETUP FAILED": "setup_fail",
    "NO CASES": "unknown",
}
# summary.cases[].status → cases.status；其他取值（running/unknown 等）→ skipped
_CASE_STATUS_MAP = {"pass": "pass", "failed": "fail", "broken": "broken"}
# exit_code → jobs.status（回填 jobs）
_EXIT_STATUS_MAP = {0: "pass", 1: "fail", 2: "setup_fail", 3: "broken"}
# exit_code 缺失时按 runs.outcome 回填 jobs.status；
# unknown（summary 缺失/不可解析）视为产物/汇总损坏 → broken（schema 头注释口径）
_OUTCOME_STATUS_MAP = {
    "pass": "pass",
    "fail": "fail",
    "setup_fail": "setup_fail",
    "broken": "broken",
    "unknown": "broken",
}

_MESSAGE_MAX = 2000  # case/failure message 截断长度
_SCAN_DEPTH = 4      # artifact 扫描限深：文件相对 run 目录的路径段数上限
                     # （firebox/<feature>/<case>/case.log 恰为 4 段，case 内文件可入账）


# ------------------------------------------------------------------ 入口

def ingest_run(job_row: dict, run_id: str, artifacts_dir: Path) -> dict | None:
    """把一次 run 的产物解析入库；成功返回 {run_id, cases, artifacts}。

    任何异常不外抛：记日志 + job 标 'ingest pending: <err>'，返回 None。
    """
    try:
        return _ingest(job_row, run_id, Path(artifacts_dir))
    except Exception as exc:  # noqa: BLE001 - 对调用方（loop 线程）绝不抛出
        logger.exception("ingest_run 失败（job=%s run=%s）", job_row.get("id"), run_id)
        _mark_ingest_pending(job_row.get("id"), str(exc))
        return None


def retry_pending_ingest(limit: int = 200) -> int:
    """后台补偿：扫 jobs 中 run_id 非空但 runs 无行的记录，重新入库。

    返回本次成功入库条数。简单实现：单次最多重试 limit 条，按 started_at 升序。
    """
    try:
        rows = pool.query(
            "SELECT j.* FROM jobs j LEFT JOIN runs r ON r.run_id = j.run_id "
            "WHERE j.run_id IS NOT NULL AND r.run_id IS NULL "
            "ORDER BY j.started_at LIMIT %s",
            (int(limit),),
        )
    except Exception:
        logger.exception("retry_pending_ingest 查询待补偿 jobs 失败")
        return 0
    root = _artifacts_root()
    done = 0
    for job in rows:
        if ingest_run(job, job["run_id"], root) is not None:
            done += 1
    return done


# ------------------------------------------------------------------ 主流程

def _ingest(job_row: dict, run_id: str, artifacts_dir: Path) -> dict:
    run_dir = artifacts_dir / run_id

    # ---- 1. 读 summary.json / run_meta.json（缺失或坏 JSON 都不抛出）----
    summary_path = run_dir / "summary.json"
    summary = _read_json(summary_path)
    run_meta = _read_json(run_dir / "run_meta.json") or {}
    if summary is None:
        summary = {}
        summary_reason = (
            "summary.json invalid" if summary_path.is_file() else "summary.json missing"
        )
    else:
        summary_reason = ""

    # ---- 2. runs 主行 ----
    outcome = _OUTCOME_MAP.get(str(summary.get("outcome") or "").upper(), "unknown")
    if summary_reason:
        outcome = "unknown"  # summary 缺失/不可解析：一律 unknown

    exit_code = summary.get("exit_code")
    if not isinstance(exit_code, int):
        ec = job_row.get("exit_code")
        exit_code = ec if isinstance(ec, int) else None

    # 按 exit_code 校正 outcome：
    #   2 → setup_fail（runner 起不来）；3 且 summary 未细分（PASS/NO CASES/无法
    #   解析）→ broken；summary 已判 fail/broken 保持不变。
    if exit_code == 2:
        outcome = "setup_fail"
    elif exit_code == 3 and outcome in ("pass", "unknown"):
        outcome = "broken"

    total = _to_int(summary.get("total"))
    passed = _to_int(summary.get("passed"))
    failed = _to_int(summary.get("failed"))
    broken = _to_int(summary.get("broken"))
    pass_rate = _to_float(summary.get("pass_rate"), None)
    if pass_rate is None:
        pass_rate = 100.0 * passed / total if total > 0 else 0.0

    duration = _to_float(summary.get("job_duration_s"), None)
    if duration is None:
        duration = _to_float(job_row.get("job_duration_s"), None)

    failed_reason = summary_reason or (str(summary.get("failed_reason") or "").strip())

    cli_args = run_meta.get("cli_args") or {}
    # branch/build：run_meta.cli_args 优先（runner 侧目前未必写入，预留字段），
    # 其次 summary 同名键；均无则 NULL。
    branch = _clean(cli_args.get("branch") or summary.get("branch"), 128)
    build = _clean(cli_args.get("build") or summary.get("build"), 64)
    env_name = _clean(summary.get("env_name") or run_meta.get("env_name"), 128)
    if env_name is None and job_row.get("env_id"):
        env_name = _clean(_lookup_env_name(job_row["env_id"]), 128)
    git_ref = _clean(summary.get("git_ref") or job_row.get("git_ref"), 128)
    host = _clean(run_meta.get("host") or summary.get("host"), 128)

    started_at = _parse_iso(run_meta.get("started_at"))
    if started_at is None:
        started_at = _parse_run_id_ts(run_id)  # run_id 前 14 位 YYYYMMDDHHMMSS
    if started_at is None:
        started_at = _mtime_of(summary_path) or datetime.now()
    # ended_at：summary.json 写出时间（取文件 mtime）→ run 目录 mtime → now
    ended_at = _mtime_of(summary_path) or _mtime_of(run_dir) or datetime.now()

    run_row = {
        "run_id": run_id,
        "job_id": job_row.get("id"),
        "loop_id": job_row.get("loop_id"),
        "product": _clean(summary.get("product") or run_meta.get("product"), 16),
        "dut_model": _clean(summary.get("dut_model"), 128),
        "dut_version": _clean(summary.get("dut_version"), 128),
        "outcome": outcome,
        "passed": passed,
        "failed": failed,
        "broken": broken,
        "total": total,
        "pass_rate": pass_rate,
        "failed_reason": failed_reason or None,
        "job_duration_s": duration,
        "branch": branch,
        "build": build,
        "env_name": env_name,
        "git_ref": git_ref,
        "host": host,
        "exit_code": exit_code,
        # artifacts_relpath：run 目录相对 artifacts_root 的路径，即 run_id 本身
        "artifacts_relpath": run_id,
        "started_at": started_at,
        "ended_at": ended_at,
    }

    # ---- 3. cases ----
    cases: list[dict] = []
    for seq, c in enumerate(summary.get("cases") or []):
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        cases.append({
            "name": name[:255],
            "seq": seq,  # 枚举序号，保 UNIQUE(run_id, name, seq)
            "status": _CASE_STATUS_MAP.get(
                str(c.get("status") or "").lower(), "skipped"
            ),
            "duration_s": _to_float(c.get("duration_s"), None),
            "message": _truncate(str(c.get("message") or "")),
            "case_relpath": _clean(c.get("case_dir"), 512),
        })

    # ---- 4. case_failures ----
    # job 级失败判定：loop 侧探测的 job_setup_failed 标记 / outcome=setup_fail / exit 2
    job_setup = (
        bool(job_row.get("job_setup_failed"))
        or outcome == "setup_fail"
        or exit_code == 2
    )
    failures: list[dict] = []
    for c in summary.get("cases") or []:
        if not isinstance(c, dict):
            continue
        status = str(c.get("status") or "").lower()
        if status == "pass" or not status:
            continue  # 只收 status≠pass 的用例
        name = str(c.get("name") or "").strip()
        msg = str(c.get("message") or "").strip() or f"{name}: {status}"
        failures.append({
            "case_name": name[:255] or None,
            "kind": _infer_kind(msg, job_setup),
            "message": _truncate(msg),
            "log_relpath": _clean(c.get("log"), 512),
        })
    # failed_reason 作为 job 级失败片段（case_name=NULL）单独入账：
    # 覆盖 summary 缺失兜底文案与 job setup 失败原因
    if failed_reason:
        failures.append({
            "case_name": None,  # job 级失败
            "kind": _infer_kind(failed_reason, job_setup),
            "message": _truncate(failed_reason),
            "log_relpath": _clean(summary.get("job_log") or "job.log", 512),
        })

    # ---- 5. artifact_files（只 os.stat，不读文件内容）----
    artifacts = _scan_artifacts(run_dir)

    # ---- 6. 单事务写库：runs 主行 + 三张明细 + jobs 回填 ----
    if exit_code is not None and exit_code in _EXIT_STATUS_MAP:
        job_status = _EXIT_STATUS_MAP[exit_code]
    else:
        job_status = _OUTCOME_STATUS_MAP[outcome]

    with pool.connection() as conn:
        runs_dao.upsert_run(run_row, conn=conn)
        runs_dao.replace_cases(run_id, cases, conn=conn)
        runs_dao.replace_case_failures(run_id, failures, conn=conn)
        runs_dao.replace_artifact_files(run_id, artifacts, conn=conn)
        _update_job(
            conn,
            job_row.get("id"),
            run_id=run_id,
            status=job_status,
            exit_code=exit_code,
            job_duration_s=duration,
            ended_at=ended_at,
        )

    return {"run_id": run_id, "cases": len(cases), "artifacts": len(artifacts)}


# ------------------------------------------------------------------ helpers

def _read_json(path: Path) -> dict | None:
    """读 JSON；文件缺失 / OSError / 半写坏 JSON 一律返回 None，不抛出。"""
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # ValueError 覆盖 json.JSONDecodeError
        return None
    return data if isinstance(data, dict) else None


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=None):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean(value, limit: int) -> str | None:
    s = str(value).strip() if value is not None else ""
    return s[:limit] or None


def _truncate(text: str) -> str:
    return text[:_MESSAGE_MAX]


def _parse_iso(value) -> datetime | None:
    """解析 ISO8601（run_meta.started_at 带时区）；转本地 naive 时间。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _parse_run_id_ts(run_id: str) -> datetime | None:
    """run_id 前 14 位 YYYYMMDDHHMMSS → 本地 naive 时间。"""
    try:
        return datetime.strptime((run_id or "")[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _mtime_of(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def _infer_kind(message: str, job_setup_failed: bool) -> str:
    """case_failures.kind 推断。

    注意：T7/T11 展示时只区分「job 级 / case 级」两类失败来源即可；这里的
    四类细分（job_setup/case_setup/main/case_teardown）仅供排查。summary
    结构里没有细分信息时一律归 main。
    """
    if job_setup_failed:
        return "job_setup"
    m = (message or "").lower()
    if "job_setup_failed" in m:
        return "job_setup"
    if "case setup" in m:
        return "case_setup"
    if "teardown" in m:
        return "case_teardown"
    return "main"


def _scan_artifacts(run_dir: Path) -> list[dict]:
    """os.walk 限深扫描 run 目录，只取 relpath/kind/size/case_name（不读内容）。

    kind 分类：job.log→job_log；summary.json/html→summary_json/summary_html；
    run_meta.json→run_meta；case.log→case_log；configs/*→config；
    *.png（含 jpg/jpeg/webp，与 artifacts.py 截图口径一致）→screenshot；
    *.tgz（含 .tar.gz/.tar 支持包）→support_tgz；其他→other。
    case_name：从 firebox/<feature>/<case>/ 三级结构提取（路径第 3 段）。
    """
    files: list[dict] = []
    if not run_dir.is_dir():
        return files
    for root, dirs, names in os.walk(run_dir):
        rel_root = Path(root).relative_to(run_dir)
        depth = 0 if rel_root == Path(".") else len(rel_root.parts)
        if depth >= _SCAN_DEPTH:
            dirs[:] = []
            continue
        if depth >= _SCAN_DEPTH - 1:
            dirs[:] = []  # 再下一层文件的路径段数将超限，不再下钻
        dirs.sort()
        names.sort()
        for name in names:
            path = Path(root) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            rel = path.relative_to(run_dir).as_posix()
            parts = rel.split("/")
            files.append({
                "relpath": rel[:1024],
                "kind": _classify(rel),
                "size_bytes": size,
                "case_name": parts[-2] if len(parts) >= 4 else None,
            })
    return files


def _classify(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1].lower()
    if name == "job.log":
        return "job_log"
    if name == "summary.json":
        return "summary_json"
    if name == "summary.html":
        return "summary_html"
    if name == "run_meta.json":
        return "run_meta"
    if name == "case.log":
        return "case_log"
    if "configs" in rel.split("/")[:-1]:
        return "config"
    if name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "screenshot"
    if name.endswith((".tgz", ".tar.gz", ".tar")):
        return "support_tgz"
    return "other"


def _lookup_env_name(env_id) -> str | None:
    """env_id → environments.name（summary.env_name 探测常为空时的兜底）。"""
    if not env_id:
        return None
    try:
        row = pool.query_one(
            "SELECT name FROM environments WHERE id = %s", (env_id,)
        )
    except Exception:
        return None
    return row["name"] if row else None


def _update_job(
    conn,
    job_id,
    *,
    run_id: str,
    status: str,
    exit_code: int | None,
    job_duration_s: float | None,
    ended_at: datetime,
) -> None:
    """回填 jobs 行（同一事务）。exit_code/duration 为 None 时不动对应列。"""
    if not job_id:
        return
    sets = ["status = %s", "run_id = %s", "ended_at = %s"]
    params: list = [status, run_id, ended_at]
    if exit_code is not None:
        sets.append("exit_code = %s")
        params.append(exit_code)
    if job_duration_s is not None:
        sets.append("job_duration_s = %s")
        params.append(job_duration_s)
    params.append(job_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = %s", tuple(params))


def _mark_ingest_pending(job_id, err: str) -> None:
    """ingest 失败后把 job 标记为待补偿（best-effort，自身失败只记日志）。"""
    if not job_id:
        return
    try:
        pool.execute(
            "UPDATE jobs SET failed_reason = %s WHERE id = %s",
            (f"ingest pending: {err}"[:2000], job_id),
        )
    except Exception:
        logger.exception("标记 ingest pending 失败（job=%s）", job_id)


def _artifacts_root() -> Path:
    """config.paths.artifacts_root（相对路径按 PROJECT_ROOT 解析）。"""
    p = Path(get_settings().paths.artifacts_root)
    return p if p.is_absolute() else (PROJECT_ROOT / p)
