"""认证路由：POST /api/login、POST /api/logout、GET /api/me。

登录模式由 config.auth.auth_mode 自动决定：
* gitlab → body.token 走 PAT 校验；
* local  → body.username + body.password（兼容口令放在 token 字段）。

登录成功种 HttpOnly Cookie（rc_session）并返回 UserOut；
登录/登出均写 audit（对应原 webui 的 db.audit("login"/"logout")）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.deps import get_current_user
from app.auth import gitlab, local, sessions
from app.auth.errors import AuthError
from app.auth.sessions import SESSION_COOKIE
from app.config import get_settings
from app.db.dao import users as users_dao
from app.schemas import LoginIn, MeOut, UserOut

router = APIRouter(prefix="/api")


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response) -> dict:
    cfg = get_settings()
    try:
        if cfg.auth.auth_mode == "gitlab":
            token, user = gitlab.login(body.token or "")
        else:
            password = body.password or body.token
            token, user = local.login_local(body.username, password)
    except AuthError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    sessions.set_session_cookie(response, token)
    return user


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    user = sessions.resolve_session(token) if token else None
    if token:
        sessions.destroy_session(token)
    sessions.clear_session_cookie(response)
    if user:
        users_dao.insert_audit(user["id"], "logout", user["username"])
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(user: dict = Depends(get_current_user)) -> MeOut:
    return MeOut(user=UserOut(**user), auth_mode=get_settings().auth.auth_mode)
