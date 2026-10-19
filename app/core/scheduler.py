"""定时任务调度器（T16）。

守护线程每 30s 扫描 schedules 表：
* 到期且设备空闲 → 用参数快照走 run_service.do_start_run 发起 loop
  （与 POST /api/run 完全同一入口；git_ref 存分支名，发起时按当时该
  分支 tip 检出 = "运行时分支最新"）。
* 到期但该环境有 loop 在跑 → 排队：不改 next_run_at，下个 tick 重试
  （last_note 记录等待状态）。
* daily → 触发后 next_run_at 推到明天同一时刻；once → 触发后停用。
* 服务重启：boot_recovery() 重算——daily 错过的排到下个周期（留痕），
  once 错过的标记 missed 并停用。

时间口径：服务器本机时间（Windows 本机时钟）。
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta

from app.core import run_service
from app.db import pool
from app.schemas import RunIn

logger = logging.getLogger("runnerconsole.core.scheduler")

TICK_SECONDS = 30.0


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def next_daily_occurrence(hhmm: str, now: datetime | None = None) -> datetime:
    """'HH:MM' → 下一个发生时刻（含今天，若已过则明天）。"""
    hour, minute = (int(x) for x in hhmm.split(":"))
    now = now or datetime.now()
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def compute_next_run(row: dict, now: datetime | None = None) -> datetime | None:
    """按行规则计算 next_run_at；once 已过/已触发返回 None。"""
    if row["rule_type"] == "once":
        return row["run_at"] if row["run_at"] and row["run_at"] > (now or datetime.now()) else None
    return next_daily_occurrence(row["rule_time"], now)


class Scheduler:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_forever, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_forever(self) -> None:
        try:
            self.boot_recovery()
        except Exception:
            logger.exception("scheduler boot_recovery 失败（继续正常运行）")
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception:
                logger.exception("scheduler tick 异常")

    # ------------------------------------------------------------- recovery
    def boot_recovery(self) -> None:
        """服务重启后重算 next_run_at。"""
        rows = pool.query("SELECT * FROM schedules WHERE enabled = 1")
        for row in rows:
            next_at = compute_next_run(row)
            if row["rule_type"] == "once" and next_at is None:
                # once 的时刻在停机期间过去了 → 标记错过并停用
                pool.execute(
                    "UPDATE schedules SET enabled = 0, last_status = 'missed', "
                    "last_note = %s, next_run_at = NULL WHERE id = %s",
                    (f"停机期间错过计划时间 {row['run_at']}", row["id"]),
                )
                logger.warning("schedule %s（once）停机期间错过，标记 missed", row["id"])
            elif row["next_run_at"] is None or row["next_run_at"] <= datetime.now():
                note = "服务重启，错过的时间点已顺延到下次计划" if row["rule_type"] == "daily" else None
                pool.execute(
                    "UPDATE schedules SET next_run_at = %s, last_note = COALESCE(%s, last_note) "
                    "WHERE id = %s",
                    (next_at, note, row["id"]),
                )
                logger.info("schedule %s next_run_at 重算 → %s", row["id"], next_at)

    # ----------------------------------------------------------------- tick
    def tick(self) -> None:
        due = pool.query(
            "SELECT * FROM schedules WHERE enabled = 1 AND next_run_at IS NOT NULL "
            "AND next_run_at <= %s",
            (datetime.now(),),
        )
        if not due:
            return
        from app.core.job_manager import get_job_manager  # 局部导入避免环

        manager = get_job_manager()
        busy_envs = {r.env_id for r in manager.active() if r.env_id}
        for row in due:
            try:
                self._trigger(row, busy_envs)
            except Exception as exc:  # 单个任务异常不阻断其它任务
                logger.exception("schedule %s 触发失败", row["id"])
                self._mark_result(row["id"], status="start_error", note=str(exc), loop_id=None)

    def _trigger(self, row: dict, busy_envs: set[str]) -> None:
        sid = row["id"]
        if row["env_id"] in busy_envs:
            # 排队：保持 next_run_at 不变，下个 tick 重试
            pool.execute(
                "UPDATE schedules SET last_note = %s WHERE id = %s",
                (f"计划时间已到，等待环境空闲（{datetime.now():%H:%M:%S}）", sid),
            )
            return

        owner = pool.query_one(
            "SELECT id, username, role FROM users WHERE id = %s", (row["owner_id"],)
        )
        if owner is None:
            self._mark_result(sid, "start_error", "创建者账号已不存在", None)
            self._finish(row)
            return

        try:
            body = RunIn(**json.loads(row["params"]))
            result = run_service.do_start_run(owner, body)
        except run_service.RunError as exc:
            self._mark_result(sid, "start_error", exc.detail, None)
            self._finish(row)
            return
        except Exception as exc:
            self._mark_result(sid, "start_error", f"发起异常：{exc}", None)
            self._finish(row)
            return

        pool.execute(
            "UPDATE schedules SET last_loop_id = %s, last_status = 'started', "
            "last_note = %s WHERE id = %s",
            (result["loop_id"], f"已发起 loop {result['loop_id']}", sid),
        )
        self._finish(row)
        logger.info("schedule %s(%s) 触发 → loop %s", sid, row["name"], result["loop_id"])

    def _finish(self, row: dict) -> None:
        """触发完成（或放弃）后推进 next_run_at。"""
        if row["rule_type"] == "once":
            pool.execute(
                "UPDATE schedules SET enabled = 0, next_run_at = NULL WHERE id = %s",
                (row["id"],),
            )
        else:
            pool.execute(
                "UPDATE schedules SET next_run_at = %s WHERE id = %s",
                (next_daily_occurrence(row["rule_time"]), row["id"]),
            )

    def _mark_result(self, sid: str, *, status: str, note: str, loop_id: str | None) -> None:
        pool.execute(
            "UPDATE schedules SET last_status = %s, last_note = %s, last_loop_id = %s "
            "WHERE id = %s",
            (status, note[:500], loop_id, sid),
        )


_scheduler: Scheduler | None = None
_guard = threading.Lock()


def get_scheduler() -> Scheduler:
    global _scheduler
    with _guard:
        if _scheduler is None:
            _scheduler = Scheduler()
        return _scheduler
