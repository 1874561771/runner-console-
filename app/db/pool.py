"""MySQL connection pool for RunnerConsole.

依赖：pymysql、DBUtils（PooledDB）。安装：
    pip install pymysql DBUtils

访问风格与原 webui/db.py 保持一致：每次操作取连接、用完归还。
无降级模式——configure() 时对 DB 做 ping 自检，MySQL 不可用直接抛异常
（由调用方决定退出），绝不静默降级到无 DB 运行。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pymysql
from dbutils.pooled_db import PooledDB
from pymysql.cursors import DictCursor

_pool: PooledDB | None = None

MAX_CONNECTIONS = 8


def configure(dsn: dict) -> None:
    """用 config 传入的 DSN 初始化连接池。

    dsn 键：host / port / user / password / database / charset（默认 utf8mb4）。
    """
    global _pool
    params = dict(dsn)
    params.setdefault("charset", "utf8mb4")
    _pool = PooledDB(
        creator=pymysql,
        maxconnections=MAX_CONNECTIONS,
        blocking=True,          # 池耗尽时阻塞等待，不抛 TooManyConnections
        ping=1,                 # 每次取连接时 ping，自动重连失效连接
        cursorclass=DictCursor,
        autocommit=False,       # 事务由 connection() 上下文统一 commit/rollback
        **params,
    )
    # 启动自检：DB 不可用直接抛异常退出，无降级模式
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()


@contextmanager
def connection() -> Iterator:
    """yield 一个池化连接；正常退出 commit，异常 rollback，finally 归还池。"""
    if _pool is None:
        raise RuntimeError("db pool not configured: call pool.configure(dsn) first")
    conn = _pool.connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()  # PooledDB: close() = 归还池，不是物理关闭


def query(sql: str, params: tuple | list | dict | None = None) -> list[dict]:
    """执行 SELECT，返回 list[dict]（DictCursor）。"""
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return list(cur.fetchall())


def query_one(sql: str, params: tuple | list | dict | None = None) -> dict | None:
    """执行 SELECT 返回首行，无结果返回 None。"""
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple | list | dict | None = None) -> int:
    """执行写语句并提交，返回 lastrowid（自增主键）或 rowcount。

    CHAR(12) 主键的 INSERT lastrowid 为 0，此时返回 rowcount。
    """
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            if cur.lastrowid:
                return cur.lastrowid
            return cur.rowcount
