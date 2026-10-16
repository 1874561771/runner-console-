"""audit 表的数据访问层（DAO）。

* 只依赖 app.db.pool，不 import 任何 api / core 模块（避免循环依赖）。
* detail 统一存 JSON 字符串（dict/list 自动序列化，截断 2000 字符，
  对应 schema 的 TEXT 列）。
* insert_audit 为 best-effort：审计写失败只记日志、不抛异常——审计
  绝不能阻断 loop 启停/回收等业务主流程。
* 时间用 SQL 端 NOW(3)，与 loops.py / users.py 风格一致。
"""

from __future__ import annotations

import json
import logging

from app.db import pool

logger = logging.getLogger("runnerconsole.db.dao.audit")

_DETAIL_MAX_LEN = 2000
_ACTION_MAX_LEN = 64


def _normalize_detail(detail) -> str | None:
    """dict/list → JSON 字符串；其他类型转 str；截断到 2000 字符。"""
    if detail is None:
        return None
    if isinstance(detail, (dict, list)):
        try:
            text = json.dumps(detail, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(detail)
    else:
        text = str(detail)
    return text[:_DETAIL_MAX_LEN] or None


def insert_audit(
    actor_id: int | None,
    action: str,
    detail: dict | list | str | None = None,
) -> None:
    """写一条审计记录。best-effort：失败只告警，不向调用方抛异常。

    actor_id 为操作者 users.id；系统动作（retention/孤儿回收）传 None。
    """
    try:
        pool.execute(
            "INSERT INTO audit (actor_id, action, detail, created_at) "
            "VALUES (%s, %s, %s, NOW(3))",
            (actor_id, (action or "")[:_ACTION_MAX_LEN], _normalize_detail(detail)),
        )
    except Exception:
        logger.warning(
            "audit 写入失败（action=%s actor_id=%s）——忽略不阻断业务",
            action, actor_id, exc_info=True,
        )


def list_audit(offset: int = 0, limit: int = 50) -> dict:
    """分页列出审计记录（新→旧），对齐前端契约返回 {items, total}。

    items 附带 actor_name（LEFT JOIN users，账号被清时为 NULL）。
    """
    offset = max(0, int(offset))
    limit = min(max(1, int(limit)), 500)
    total_row = pool.query_one("SELECT COUNT(*) AS n FROM audit")
    items = pool.query(
        "SELECT a.id, a.actor_id, a.action, a.detail, a.created_at, "
        "u.username AS actor_name "
        "FROM audit a LEFT JOIN users u ON u.id = a.actor_id "
        "ORDER BY a.id DESC LIMIT %s OFFSET %s",
        (limit, offset),
    )
    return {"items": items, "total": int(total_row["n"]) if total_row else 0}
