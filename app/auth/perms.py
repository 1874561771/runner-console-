"""权限判定（语义对应原 webui/server.py 的 _require_admin / owner 检查，
并按新 schema 扩展 env_grants 环境级授权）。

判定规则：
* is_admin          —— role == 'admin'；
* can_access_owner  —— 资源 owner 本人或 admin（env/job/loop/upload 等通用）；
* can_operate_env   —— admin / env owner / env_grants 中 level='operator'；
* can_view_env      —— 在 can_operate_env 基础上放宽到 level='viewer'。
env_grants 查询统一走 app.db.pool（不接收外部连接对象）。
"""

from __future__ import annotations

from app.db import pool


def is_admin(user: dict) -> bool:
    return bool(user) and user.get("role") == "admin"


def can_access_owner(user: dict, owner_id: int | None) -> bool:
    """owner 本人或 admin 可访问其资源。"""
    if is_admin(user):
        return True
    if owner_id is None or user.get("id") is None:
        return False
    return int(user["id"]) == int(owner_id)


def can_operate_env(user: dict, env_id: str, conn: object | None = None) -> bool:
    """可对环境执行操作（启停/删改等）。

    conn 参数仅为兼容原签名保留；池化封装后查询统一走 pool，该参数被忽略。
    """
    if is_admin(user):
        return True
    row = pool.query_one(
        """
        SELECT 1 AS ok
        FROM environments e
        LEFT JOIN env_grants g
               ON g.env_id = e.id AND g.user_id = %s AND g.level = 'operator'
        WHERE e.id = %s AND (e.owner_id = %s OR g.user_id IS NOT NULL)
        """,
        (user["id"], env_id, user["id"]),
    )
    return row is not None


def can_view_env(user: dict, env_id: str, conn: object | None = None) -> bool:
    """可查看环境（operator 或 viewer 授权均算）。conn 参数同上，被忽略。"""
    if is_admin(user):
        return True
    row = pool.query_one(
        """
        SELECT 1 AS ok
        FROM environments e
        LEFT JOIN env_grants g
               ON g.env_id = e.id AND g.user_id = %s
        WHERE e.id = %s AND (e.owner_id = %s OR g.user_id IS NOT NULL)
        """,
        (user["id"], env_id, user["id"]),
    )
    return row is not None
