"""会话签发与解析（迁移自 webui/auth.py 的 session 部分）。

与原版的关键差异：
* 原版把明文 session token 存库；本版只存 sha256(token) 的 hex
  （sessions.token_hash 为 PK，见 app/db/schema.sql），明文不落库。
* 原 issue_session(user) 收整个 user dict；本版按任务约定收 user_id。
* TTL 来自 config.auth.session_ttl_days（默认 7 天），不再硬编码。
"""

from __future__ import annotations

import hashlib
import secrets

from fastapi import Response

from app.config import get_settings
from app.db.dao import users as users_dao

SESSION_COOKIE = "rc_session"
_TOKEN_BYTES = 32  # secrets.token_urlsafe(32) → ~43 字符 URL 安全串


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(user_id: int) -> str:
    """签发新会话：生成随机 token，落库 sha256 hex，刷新 last_login。

    返回明文 token（仅此刻存在，交给 Cookie；服务端不保存）。
    """
    ttl_days = get_settings().auth.session_ttl_days
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    users_dao.insert_session(_hash_token(token), user_id, ttl_days)
    users_dao.touch_login(user_id)
    return token


def resolve_session(token: str | None) -> dict | None:
    """由明文 token 解析用户；无效/过期返回 None。

    顺带清理全部过期会话行（等价原 session_user 的 purge 逻辑，
    放在 SQL 端执行，行数多时也不会拖慢 Python）。
    """
    if not token:
        return None
    users_dao.purge_expired_sessions()
    return users_dao.get_session(_hash_token(token))


def destroy_session(token: str | None) -> None:
    if not token:
        return
    users_dao.delete_session(_hash_token(token))


# ------------------------------------------------------------------ cookie

def set_session_cookie(response: Response, token: str) -> None:
    """种会话 Cookie：HttpOnly / SameSite=Lax / path=/，max_age 与 TTL 同步。

    不设 secure：控制台跑在内网 HTTP 上；若将来上 HTTPS，可加 secure=True。
    """
    max_age = get_settings().auth.session_ttl_days * 86400
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")
