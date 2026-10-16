"""保留策略与产物清理（T6，迁移重构自 webui/jobs.py prune_artifacts）。

与原版的关键差异：
1. 清理对象从"扫 artifacts 目录 + mtime"改为"DB runs 表驱动"——
   runs 表是 run 的权威清单（T5 ingest 写入）；磁盘孤儿目录（ingest
   前进程崩溃等产生的无 runs 行目录）由 _sweep_orphan_dirs 兜底清理。
2. 删除顺序：先删磁盘目录，后删 DB 行（DELETE FROM runs ...）。
   runs 删除后 cases / case_failures / artifact_files 经 FK CASCADE
   一并清除；磁盘删失败则跳过该 run 的 DB 删除（下次重试，与原版
   "rmtree 失败 continue" 语义一致）。
3. jobs.run_id 无外键，删除 runs 后 jobs 行保留（迭代历史不丢，
   run_id 成为悬空引用——详情页按 runs 是否存在判 404）。
4. 正在执行的 run 受保护：收集活跃 loop 的 current_run_id，不清理。
5. 幂等/并发安全：模块级锁串行化；即使双进程并发，重复执行也是
   无害的——目录不存在跳过、DB DELETE 命中 0 行。
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import time
from pathlib import Path

from app.config import get_settings as get_app_config
from app.db import pool
from app.db.dao import audit as audit_dao
from app.db.dao import settings as settings_dao

__all__ = ["run_retention", "get_settings", "save_settings"]

logger = logging.getLogger("runnerconsole.core.retention")

# 与 loop_runner.RUN_ID_RE 一致（本地副本，避免 import core.loop_runner）
RUN_ID_RE = re.compile(r"^(\d{14})(_\d+)?$")

# 并发串行化：同一进程内 run_retention 互斥；跨进程靠幂等性兜底
_retention_lock = threading.Lock()

# audit detail 中 run_id 清单最多保留条数（防 TEXT 溢出，详情看日志）
_MAX_RUN_IDS_IN_DETAIL = 100


# ---------------------------------------------------------------- settings

def get_settings() -> dict:
    """读保留策略（settings 表）：{retain_count, retain_days}，0=不限制。"""
    return settings_dao.get_retention()


def save_settings(
    retain_count: int, retain_days: int, actor_id: int | None = None
) -> dict:
    """保存保留策略并立即执行一次清理。

    对齐前端 T12 契约：POST /api/admin/settings 返回 {ok, cleaned}。
    """
    retain_count = _validate_policy_value(retain_count, "retain_count")
    retain_days = _validate_policy_value(retain_days, "retain_days")
    old = settings_dao.get_retention()
    settings_dao.save_retention(retain_count, retain_days)
    audit_dao.insert_audit(
        actor_id,
        "settings.update",
        {
            "keys": ["retain_count", "retain_days"],
            "old": old,
            "new": {"retain_count": retain_count, "retain_days": retain_days},
        },
    )
    cleaned = run_retention(actor_id=actor_id)
    return {"ok": True, "cleaned": cleaned}


def _validate_policy_value(value, name: str) -> int:
    try:
        iv = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是整数") from None
    if iv < 0:
        raise ValueError(f"{name} 不能为负数（0=不限制）")
    return iv


# ----------------------------------------------------------- run_retention

def run_retention(actor_id: int | None = None) -> dict:
    """按 settings 保留策略清理过期 runs（磁盘目录 + DB 行），写审计。

    选出待清理 run_id 集合 = （超出 retain_count 的最旧 runs）∪
    （ended_at 早于 now - retain_days 的 runs），去集并排除正在执行
    的 run。返回 {removed_runs, removed_files_est, ...}。
    """
    with _retention_lock:
        return _run_retention_locked(actor_id)


def _run_retention_locked(actor_id: int | None) -> dict:
    policy = settings_dao.get_retention()
    retain_count = int(policy["retain_count"])
    retain_days = int(policy["retain_days"])
    result = {
        "retain_count": retain_count,
        "retain_days": retain_days,
        "removed_runs": 0,
        "removed_files_est": 0,
        "orphan_dirs_removed": 0,
        "skipped": False,
    }
    # 两个维度都是 0 = 全保留（对齐原版语义）
    if retain_count <= 0 and retain_days <= 0:
        result["skipped"] = True
        return result

    to_remove = _select_stale_runs(retain_count, retain_days)
    to_remove -= _protected_run_ids()
    _sweep_orphan_dirs(retain_days, result)

    if not to_remove:
        return result

    artifacts_root = _artifacts_root()
    removed_files = 0
    removed: list[str] = []
    # 文件数估计必须在 DB 删除前统计（runs 行删后 artifact_files CASCADE 消失）
    pending_ids = tuple(sorted(to_remove))
    removed_files = _count_artifact_files(pending_ids)
    for run_id in pending_ids:
        # 1) 先删磁盘目录（失败则跳过 DB 删除，下次重试）
        target = artifacts_root / run_id
        if target.is_dir():
            try:
                shutil.rmtree(target)
            except OSError:
                logger.warning("retention: 删除产物目录失败，跳过 run %s", run_id)
                continue
        # 2) 后删 DB 行（cases/case_failures/artifact_files FK CASCADE）
        pool.execute("DELETE FROM runs WHERE run_id = %s", (run_id,))
        removed.append(run_id)

    if removed:
        result["removed_runs"] = len(removed)
        result["removed_files_est"] = removed_files

    if removed or result["orphan_dirs_removed"]:
        logger.info(
            "retention: removed %d runs (%d files, %d orphan dirs): %s%s",
            len(removed), removed_files, result["orphan_dirs_removed"],
            ", ".join(removed[:10]),
            " ..." if len(removed) > 10 else "",
        )
        audit_dao.insert_audit(
            actor_id,
            "retention.run",
            {
                "retain_count": retain_count,
                "retain_days": retain_days,
                "removed_runs": len(removed),
                "removed_files_est": removed_files,
                "orphan_dirs_removed": result["orphan_dirs_removed"],
                "run_ids": removed[:_MAX_RUN_IDS_IN_DETAIL],
            },
        )
    return result


def _select_stale_runs(retain_count: int, retain_days: int) -> set[str]:
    """DB 选出待清理 run_id：按天过期 ∪ 超出保留条数的最旧 runs。"""
    stale: set[str] = set()
    if retain_days > 0:
        rows = pool.query(
            "SELECT run_id FROM runs "
            "WHERE ended_at IS NOT NULL "
            "  AND ended_at < NOW(3) - INTERVAL %s DAY",
            (retain_days,),
        )
        stale.update(r["run_id"] for r in rows)
    if retain_count > 0:
        # MySQL 不允许 IN 子查询直接带 LIMIT，用派生表包装；
        # 新→旧排保留集合（ended_at 可能为 NULL，排最后）
        rows = pool.query(
            "SELECT run_id FROM runs WHERE run_id NOT IN ("
            "  SELECT run_id FROM ("
            "    SELECT run_id FROM runs "
            "    ORDER BY ended_at DESC, started_at DESC, run_id DESC "
            "    LIMIT %s"
            "  ) t)",
            (retain_count,),
        )
        stale.update(r["run_id"] for r in rows)
    return stale


def _protected_run_ids() -> set[str]:
    """活跃 loop 正在执行的 run 不清理（对齐原版 protected 语义）。"""
    protected: set[str] = set()
    try:
        from app.core.job_manager import get_job_manager  # noqa: PLC0415

        for runner in get_job_manager().active():
            if runner.current_run_id:
                protected.add(runner.current_run_id)
    except Exception:
        # JobManager 未初始化（如 lifespan 早期）不影响清理主流程
        logger.debug("retention: 无法获取活跃 run 保护集合", exc_info=True)
    return protected


def _count_artifact_files(run_ids: tuple[str, ...]) -> int:
    """删除前的 artifact_files 行数估计（随 runs 行 CASCADE 消失）。"""
    total = 0
    chunk_size = 500
    for i in range(0, len(run_ids), chunk_size):
        chunk = run_ids[i:i + chunk_size]
        placeholders = ", ".join(["%s"] * len(chunk))
        rows = pool.query(
            f"SELECT COUNT(*) AS n FROM artifact_files "
            f"WHERE run_id IN ({placeholders})",
            chunk,
        )
        total += int(rows[0]["n"]) if rows else 0
    return total


def _sweep_orphan_dirs(retain_days: int, result: dict) -> None:
    """清理磁盘上无 runs 行的孤儿产物目录（如 ingest 前崩溃遗留）。

    仅当 retain_days > 0 时按目录 mtime 早于 cutoff 清理（条数维度
    以 DB 为准，无法对孤儿目录判定"最新 N 个"）。目录不存在 runs 行
    即无 DB 行可删，纯磁盘操作。
    """
    if retain_days <= 0:
        return
    artifacts_root = _artifacts_root()
    if not artifacts_root.is_dir():
        return
    cutoff = time.time() - retain_days * 86400
    try:
        dirs = [p for p in artifacts_root.iterdir() if p.is_dir()]
    except OSError:
        return
    dir_names = [p.name for p in dirs if RUN_ID_RE.match(p.name)]
    if not dir_names:
        return
    known: set[str] = set()
    chunk_size = 500
    for i in range(0, len(dir_names), chunk_size):
        chunk = dir_names[i:i + chunk_size]
        placeholders = ", ".join(["%s"] * len(chunk))
        rows = pool.query(
            f"SELECT run_id FROM runs WHERE run_id IN ({placeholders})",
            chunk,
        )
        known.update(r["run_id"] for r in rows)
    removed = 0
    for p in dirs:
        if not RUN_ID_RE.match(p.name) or p.name in known:
            continue
        try:
            if p.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(p)
            removed += 1
            logger.warning("retention: 清理孤儿产物目录 %s", p.name)
        except OSError:
            logger.warning("retention: 孤儿目录清理失败 %s", p.name, exc_info=True)
    result["orphan_dirs_removed"] = removed


def _artifacts_root() -> Path:
    cfg = get_app_config()
    return Path(cfg.paths.artifacts_root).expanduser().resolve()
