"""持久化运行队列：环境空闲后按入队顺序自动发起。"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from app.core import run_service
from app.db import pool
from app.schemas import RunIn

logger = logging.getLogger("runnerconsole.core.run_queue")


class RunQueueWorker:
    def __init__(self, interval_seconds: float = 5.0) -> None:
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        # starting 只会在发起 loop 的短临界区存在；服务异常退出后需恢复，避免永久卡住。
        pool.execute(
            "UPDATE run_queue SET status = 'queued', note = %s "
            "WHERE status = 'starting'",
            ("服务重启，已恢复排队",),
        )
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="run-queue"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("run queue tick failed")
            if self._stop.wait(self.interval_seconds):
                break

    def tick(self) -> None:
        rows = pool.query(
            "SELECT q.*, u.username, u.role FROM run_queue q "
            "JOIN users u ON u.id = q.owner_id "
            "WHERE q.status = 'queued' ORDER BY q.created_at LIMIT 100"
        )
        busy_envs: set[str] = set()
        for row in rows:
            env_id = row["env_id"]
            if env_id in busy_envs:
                continue
            claimed = pool.execute(
                "UPDATE run_queue SET status = 'starting' "
                "WHERE id = %s AND status = 'queued'",
                (row["id"],),
            )
            if not claimed:
                continue
            try:
                body = RunIn(**json.loads(row["params"]))
                user = {
                    "id": row["owner_id"],
                    "username": row["username"],
                    "role": row["role"],
                }
                result = run_service.do_start_run(user, body)
            except run_service.RunError as exc:
                if exc.status == 409:
                    pool.execute(
                        "UPDATE run_queue SET status = 'queued', note = %s WHERE id = %s",
                        (f"等待环境空闲：{exc.detail}"[:500], row["id"]),
                    )
                    busy_envs.add(env_id)
                else:
                    pool.execute(
                        "UPDATE run_queue SET status = 'failed', note = %s WHERE id = %s",
                        (exc.detail[:500], row["id"]),
                    )
            except Exception as exc:
                logger.exception("queued run %s failed to start", row["id"])
                pool.execute(
                    "UPDATE run_queue SET status = 'failed', note = %s WHERE id = %s",
                    (str(exc)[:500], row["id"]),
                )
            else:
                pool.execute(
                    "UPDATE run_queue SET status = 'started', loop_id = %s, "
                    "started_at = %s, note = %s WHERE id = %s",
                    (
                        result["loop_id"],
                        datetime.now(),
                        f"已发起 loop {result['loop_id']}",
                        row["id"],
                    ),
                )
                busy_envs.add(env_id)


_worker = RunQueueWorker()


def get_run_queue_worker() -> RunQueueWorker:
    return _worker
