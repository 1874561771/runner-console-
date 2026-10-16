"""users / sessions / audit 表的数据访问层（DAO）。

* 只依赖 app.db.pool，不 import 任何 api / auth 模块（避免循环依赖）。
* 时间一律用 SQL 端 NOW(3) 计算（DB 时区为准），不传 Python datetime。
* 语义对照原 webui/db.py 的同名函数；MySQL 8 的
  INSERT ... ON DUPLICATE KEY UPDATE 使用 VALUES() 写法（8.x 仍支持）。
"""

from __future__ import annotations

from app.db import pool

# 全量列（含敏感字段，仅内部使用；对外输出走 app/schemas.UserOut 过滤）
_USER_COLS = (
    "id, gitlab_id, username, name, email, role, created_at, "
    "last_login, token_hash, token_salt, auth_source"
)
# 对外展示列（不含 token_hash/token_salt）
_USER_SAFE_COLS = (
    "id, gitlab_id, username, name, email, role, created_at, "
    "last_login, auth_source"
)


# ------------------------------------------------------------------ users

def get_by_id(user_id: int) -> dict | None:
    return pool.query_one(f"SELECT {_USER_COLS} FROM users WHERE id = %s", (user_id,))


def get_by_username(username: str) -> dict | None:
    return pool.query_one(
        f"SELECT {_USER_COLS} FROM users WHERE username = %s", (username,)
    )


def get_by_gitlab_id(gitlab_id: int) -> dict | None:
    return pool.query_one(
        f"SELECT {_USER_COLS} FROM users WHERE gitlab_id = %s", (gitlab_id,)
    )


def count_admins() -> int:
    row = pool.query_one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'")
    return int(row["n"]) if row else 0


def list_users() -> list[dict]:
    return pool.query(
        f"SELECT {_USER_SAFE_COLS} FROM users ORDER BY username"
    )


def upsert_user(
    *,
    username: str,
    gitlab_id: int | None = None,
    name: str | None = None,
    email: str | None = None,
    role: str = "user",
    token_hash: str | None = None,
    token_salt: str | None = None,
    auth_source: str = "local",
) -> dict:
    """插入或更新用户，返回更新后的完整行。

    * gitlab 登录：按 gitlab_id / username 任一唯一键命中即更新——
      同名旧 local 账号（gitlab_id 为 NULL）会被关联（补上 gitlab_id），
      而不是新建第二个身份丢失 env/job 所有权（对应原 auth_gitlab.login 语义）。
    * role 不在 ON DUPLICATE KEY UPDATE 中更新：角色变更由登录逻辑
      调 set_role() 显式提权，避免每次登录覆盖手工调整的角色。
    * token_hash/token_salt 用 COALESCE 保留旧值：gitlab 登录不传时
      不清除已绑定的 local 口令。
    """
    pool.execute(
        """
        INSERT INTO users
            (gitlab_id, username, name, email, role, token_hash, token_salt,
             auth_source, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(3))
        ON DUPLICATE KEY UPDATE
            gitlab_id   = COALESCE(users.gitlab_id, VALUES(gitlab_id)),
            name        = COALESCE(VALUES(name), users.name),
            email       = COALESCE(VALUES(email), users.email),
            token_hash  = COALESCE(VALUES(token_hash), users.token_hash),
            token_salt  = COALESCE(VALUES(token_salt), users.token_salt),
            auth_source = VALUES(auth_source)
        """,
        (gitlab_id, username, name, email, role, token_hash, token_salt, auth_source),
    )
    if gitlab_id is not None:
        row = get_by_gitlab_id(gitlab_id)
        if row:
            return row
    row = get_by_username(username)
    if row is None:
        raise RuntimeError(f"upsert_user 后无法取回用户行: {username}")
    return row


def update_password(user_id: int, token_hash: str, token_salt: str) -> None:
    pool.execute(
        "UPDATE users SET token_hash = %s, token_salt = %s WHERE id = %s",
        (token_hash, token_salt, user_id),
    )


def clear_password(user_id: int) -> None:
    """清空 local 口令（管理员重置；下次 local 登录重新绑定）。"""
    pool.execute(
        "UPDATE users SET token_hash = NULL, token_salt = NULL WHERE id = %s",
        (user_id,),
    )


def set_role(user_id: int, role: str) -> None:
    if role not in ("admin", "user"):
        raise ValueError(f"非法 role: {role}")
    pool.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))


def touch_login(user_id: int) -> None:
    pool.execute("UPDATE users SET last_login = NOW(3) WHERE id = %s", (user_id,))


# --------------------------------------------------------------- sessions

def insert_session(token_hash: str, user_id: int, ttl_days: int = 7) -> None:
    pool.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
        "VALUES (%s, %s, NOW(3), DATE_ADD(NOW(3), INTERVAL %s DAY))",
        (token_hash, user_id, ttl_days),
    )


def get_session(token_hash: str) -> dict | None:
    """取有效会话并联出用户信息；过期行视为不存在（由 SQL NOW(3) 判定）。"""
    return pool.query_one(
        """
        SELECT s.user_id, s.expires_at,
               u.id, u.gitlab_id, u.username, u.name, u.email, u.role,
               u.created_at, u.last_login, u.auth_source
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = %s AND s.expires_at > NOW(3)
        """,
        (token_hash,),
    )


def delete_session(token_hash: str) -> None:
    pool.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash,))


def purge_expired_sessions() -> int:
    """删除全部过期会话行，返回删除行数。"""
    return pool.execute("DELETE FROM sessions WHERE expires_at < NOW(3)")


# ------------------------------------------------------------------ audit

def insert_audit(actor_id: int | None, action: str, detail: str | None = None) -> None:
    pool.execute(
        "INSERT INTO audit (actor_id, action, detail, created_at) "
        "VALUES (%s, %s, %s, NOW(3))",
        (actor_id, action, detail),
    )
