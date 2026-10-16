"""FastAPI 依赖：从请求中还原当前用户。

token 提取顺序（对应原 webui/server.py _bearer 的逻辑，Cookie 优先）：
1. Cookie rc_session（浏览器主通道；HttpOnly，<img>/<a> 等导航请求也能带上）
2. Authorization: Bearer <token>（过渡期兼容，供脚本/调试用）
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.auth import perms, sessions
from app.auth.sessions import SESSION_COOKIE


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def get_current_user(request: Request) -> dict:
    """校验会话并返回 user dict；未登录抛 401。"""
    user = sessions.resolve_session(_extract_token(request))
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


def maybe_current_user(request: Request) -> dict | None:
    """同上但不抛异常——登出等允许匿名的接口用。"""
    return sessions.resolve_session(_extract_token(request))


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """要求 admin 角色，否则 403。"""
    if not perms.is_admin(user):
        raise HTTPException(status_code=403, detail="forbidden")
    return user
