"""业务路由：管理端（全部 require_admin）。

契约权威 = frontend/js/api.js mockRoutes + views/admin.js：
* GET   /api/admin/users                        → [{id, username, name, role, source, last_login}]
* POST  /api/admin/users {username,password?,name?,role?}
        → 用户对象（password 为空时额外返回一次性 password）+ audit user.create
* PATCH /api/admin/users/{id}/role {role}       → 用户对象；不能改自己（400）
* POST  /api/admin/users/{id}/reset-password    → {ok, password}（一次性返回）+ audit user.reset
* GET   /api/admin/audit?offset=&limit=         → {items, total}（items 带 actor）
* GET   /api/admin/settings                     → {retain_count, retain_days}
* POST  /api/admin/settings                     → {ok, cleaned}（cleaned = 本次清理 run 数）
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException

from app.api.common import fmt_dt, parse_int
from app.api.deps import require_admin
from app.auth.local import USERNAME_RE, hash_password
from app.core.retention import get_settings as get_retention_settings
from app.core.retention import save_settings as save_retention_settings
from app.db.dao import audit as audit_dao
from app.db.dao import users as users_dao
from app.schemas import RoleIn, SettingsIn, UserCreateIn

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ users

def _user_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "name": row.get("name"),
        "email": row.get("email"),
        "role": row["role"],
        "source": row.get("auth_source") or "local",
        "auth_source": row.get("auth_source"),
        "created_at": fmt_dt(row.get("created_at")),
        "last_login": fmt_dt(row.get("last_login")),
    }


@router.get("/admin/users")
def list_users(user: dict = Depends(require_admin)) -> list[dict]:
    return [_user_view(r) for r in users_dao.list_users()]


@router.post("/admin/users")
def create_user(body: UserCreateIn, user: dict = Depends(require_admin)) -> dict:
    username = (body.username or "").strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=400, detail="用户名只能是字母/数字/. _ -，长度 2-40"
        )
    if body.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="role 只能是 admin 或 user")
    if users_dao.get_by_username(username) is not None:
        raise HTTPException(status_code=400, detail=f"用户名已存在：{username}")

    # password 留空 → 生成一次性随机口令，响应中唯一一次明文展示
    generated = not (body.password or "").strip()
    password = ("rc-" + secrets.token_urlsafe(9)) if generated else body.password.strip()
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="口令至少 6 个字符")
    token_hash, token_salt = hash_password(password)
    row = users_dao.upsert_user(
        username=username,
        name=(body.name or "").strip() or username,
        role=body.role,
        token_hash=token_hash,
        token_salt=token_salt,
        auth_source="local",
    )
    audit_dao.insert_audit(
        user["id"],
        "user.create",
        {"target": username, "role": body.role, "operator": user["username"]},
    )
    result = _user_view(row)
    if generated:
        result["password"] = password
    return result


@router.patch("/admin/users/{user_id}/role")
def set_user_role(
    user_id: int, body: RoleIn, user: dict = Depends(require_admin)
) -> dict:
    if body.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="role 只能是 admin 或 user")
    if int(user_id) == int(user["id"]):
        raise HTTPException(status_code=400, detail="不能修改自己的角色")
    target = users_dao.get_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    users_dao.set_role(user_id, body.role)
    audit_dao.insert_audit(
        user["id"],
        "user.role",
        {"target": target["username"], "role": body.role, "operator": user["username"]},
    )
    return _user_view(users_dao.get_by_id(user_id))


@router.post("/admin/users/{user_id}/reset-password")
def reset_password(user_id: int, user: dict = Depends(require_admin)) -> dict:
    target = users_dao.get_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 一次性随机口令（本次响应唯一一次明文展示；服务端只存 PBKDF2 哈希）
    password = "rc-" + secrets.token_urlsafe(9)
    token_hash, token_salt = hash_password(password)
    users_dao.update_password(user_id, token_hash, token_salt)
    audit_dao.insert_audit(
        user["id"],
        "user.reset",
        {"target": target["username"], "operator": user["username"]},
    )
    return {"ok": True, "password": password}


# ------------------------------------------------------------------ audit

@router.get("/admin/audit")
def list_audit(offset: int = 0, limit: int = 20, user: dict = Depends(require_admin)) -> dict:
    offset = max(parse_int(offset, 0) or 0, 0)
    limit = min(max(parse_int(limit, 20) or 20, 1), 100)
    data = audit_dao.list_audit(offset=offset, limit=limit)
    items = [
        {
            "id": item["id"],
            "created_at": fmt_dt(item.get("created_at")),
            "actor": item.get("actor_name") or "system",
            "action": item.get("action"),
            "detail": item.get("detail"),
        }
        for item in data["items"]
    ]
    return {"items": items, "total": data["total"]}


# ------------------------------------------------------------------ settings

@router.get("/admin/settings")
def get_settings_view(user: dict = Depends(require_admin)) -> dict:
    return get_retention_settings()


@router.post("/admin/settings")
def save_settings_view(body: SettingsIn, user: dict = Depends(require_admin)) -> dict:
    try:
        result = save_retention_settings(
            body.retain_count, body.retain_days, actor_id=user["id"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 契约：cleaned 为本次清理掉的 run 数（数字）
    cleaned = result.get("removed_runs", 0) if isinstance(result, dict) else 0
    return {"ok": True, "cleaned": int(cleaned)}
