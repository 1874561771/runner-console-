"""权限判定（语义对应原 webui/server.py 的 _require_admin / owner 检查，
并按新 schema 扩展 env_grants 环境级授权）。

判定规则：
* is_admin          —— role == 'admin'；
* can_access_owner  —— 资源 owner 本人或 admin（env/job/loop/upload 等通用）；
* can_operate_env   —— admin / env owner / env_grants 中 level='operator'；
* can_view_env      —— 在 can_operate_env 基础上放宽到 level='viewer'；
* can_view_resource —— owner / admin，或对资源所在环境 can_view_env（loop/run 只读查看）。
env_grants 查询统一走 app.db.pool（不接收外部连接对象）。
"""

from __future__ import annotations

from app.db import pool


def is_admin(user: dict | None) -> bool:
    return bool(user) and user.get("role") == "admin"


def can_access_owner(user: dict | None, owner_id: int | None) -> bool:
    """owner 本人或 admin 可访问其资源。"""
    if is_admin(user):
        return True
    if not user or owner_id is None or user.get("id") is None:
        return False
    return int(user["id"]) == int(owner_id)


def can_operate_env(user: dict | None, env_id: str, conn: object | None = None) -> bool:
    """可对环境执行操作（启停/删改等）。

    conn 参数仅为兼容原签名保留；池化封装后查询统一走 pool，该参数被忽略。
    """
    if is_admin(user):
        return True
    if not user:
        return False
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


def can_view_env(user: dict | None, env_id: str, conn: object | None = None) -> bool:
    """可查看环境：public 对游客开放，authenticated 对登录用户开放。"""
    if is_admin(user):
        return True
    if not user:
        row = pool.query_one(
            "SELECT 1 AS ok FROM environments WHERE id = %s AND visibility = 'public'",
            (env_id,),
        )
        return row is not None
    row = pool.query_one(
        """
        SELECT 1 AS ok
        FROM environments e
        LEFT JOIN env_grants g
               ON g.env_id = e.id AND g.user_id = %s
        WHERE e.id = %s AND (
            e.visibility IN ('authenticated', 'public')
            OR e.owner_id = %s OR g.user_id IS NOT NULL
        )
        """,
        (user["id"], env_id, user["id"]),
    )
    return row is not None


def can_view_resource(user: dict | None, owner_id: int | None, env_id: str | None) -> bool:
    """loop/run 只读查看：owner / admin，或对其环境有 viewer/operator 授权（含 env owner）。"""
    if can_access_owner(user, owner_id):
        return True
    return bool(env_id) and can_view_env(user, env_id)


def visible_scope_sql(owner_col: str, env_col: str, user: dict | None) -> tuple[str, tuple]:
    """列表过滤片段：资源 owner 是本人，或所在环境可被本人查看（非 admin 使用）。"""
    if not user:
        return (
            f"{env_col} IN (SELECT id FROM environments WHERE visibility = 'public')",
            (),
        )
    uid = user["id"]
    sql = (
        f"({owner_col} = %s OR {env_col} IN ("
        "SELECT e.id FROM environments e "
        "WHERE e.owner_id = %s OR e.visibility IN ('authenticated', 'public') "
        "UNION SELECT g.env_id FROM env_grants g WHERE g.user_id = %s))"
    )
    return sql, (uid, uid, uid)


def viewable_env_ids(user: dict | None) -> set[str]:
    """本人可查看的环境 id（env owner 或 env_grants 任一级别）。"""
    if not user:
        rows = pool.query("SELECT id FROM environments WHERE visibility = 'public'")
        return {r["id"] for r in rows}
    rows = pool.query(
        "SELECT e.id AS id FROM environments e "
        "WHERE e.owner_id = %s OR e.visibility IN ('authenticated', 'public') "
        "UNION SELECT g.env_id AS id FROM env_grants g WHERE g.user_id = %s",
        (user["id"], user["id"]),
    )
    return {r["id"] for r in rows}
