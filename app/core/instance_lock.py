"""用 MySQL advisory lock 保证同一数据库只运行一个 RunnerConsole 实例。"""

from __future__ import annotations

import pymysql
from pymysql.cursors import DictCursor


class InstanceAlreadyRunning(RuntimeError):
    pass


class DatabaseInstanceLock:
    def __init__(self, dsn: dict) -> None:
        self._dsn = dict(dsn)
        database = str(self._dsn.get("database") or "default")
        self.name = f"runnerconsole:{database}:primary"
        self._conn = None

    def acquire(self) -> None:
        if self._conn is not None:
            return
        params = dict(self._dsn)
        params.setdefault("charset", "utf8mb4")
        params["autocommit"] = True
        params["cursorclass"] = DictCursor
        conn = pymysql.connect(**params)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT GET_LOCK(%s, 0) AS acquired", (self.name,))
                row = cur.fetchone() or {}
            if int(row.get("acquired") or 0) != 1:
                raise InstanceAlreadyRunning(
                    "另一个 RunnerConsole 实例正在使用同一数据库；请先停止旧实例"
                )
        except Exception:
            conn.close()
            raise
        self._conn = conn

    def release(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT RELEASE_LOCK(%s)", (self.name,))
        finally:
            conn.close()
