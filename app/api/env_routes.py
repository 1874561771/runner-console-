"""业务路由：环境 CRUD、强制释放锁、env_grants 授权。

契约权威 = frontend/js/api.js mockRoutes + mock-data.js + views/resources.js：
* GET    /api/envs                        列表（owner ∪ admin 全部 ∪ grants 授权）
* POST   /api/envs {name, content}        → 201 完整环境对象
* GET    /api/envs/{id}                   详情（content 脱敏 redacted map）
* PATCH  /api/envs/{id}                   name/content（owner|admin）、disabled（仅 admin）
* DELETE /api/envs/{id}                   owner|admin；有存活锁拒绝 409
* POST   /api/lock/force-release          admin|owner → JobManager.clear_lock
* GET/PUT /api/envs/{id}/grants           viewer/operator 授权（audit env.grant）

env 文件存储：console_dir/<username>/<env_id>/firebox.env（environments.relpath
相对 console_dir，即 JobManager 的锁目录约定）。删除时清目录 + env_grants CASCADE。
missing[] 用 env_files 缺键检查，基准 = workdir/.firebox_env.example（缺失则无检查）。
"""

from __future__ import annotations

import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.api.common import console_dir, env_lock_view, fmt_dt
from app.api.deps import get_current_user
from app.auth import perms
from app.config import get_settings
from app.core import env_files, env_lock
from app.core.job_manager import get_job_manager
from app.db import pool
from app.db.dao import audit as audit_dao
from app.db.dao import users as users_dao
from app.schemas import EnvIdIn, EnvIn, EnvPatchIn, GrantsIn

router = APIRouter(prefix="/api")

_ENV_SELECT = (
    "SELECT e.*, u.username AS owner_name "
    "FROM environments e JOIN users u ON u.id = e.owner_id "
)

GRANT_LEVELS = ("viewer", "operator")


# ------------------------------------------------------------------ helper

def _env_file_path(row: dict) -> Path:
    return console_dir() / str(row["relpath"]) / "firebox.env"


def _required_keys() -> list[str]:
    """missing[] 检查基准：workdir/.firebox_env.example 的键（文件缺失则无检查）。"""
    example = Path(get_settings().paths.workdir).expanduser() / ".firebox_env.example"
    return env_files.example_keys(example)


def _env_row(env_id: str) -> dict | None:
    return pool.query_one(_ENV_SELECT + "WHERE e.id = %s", (env_id,))


def _env_or_404(env_id: str) -> dict:
    row = _env_row(env_id)
    if row is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    return row


def _env_view(row: dict, *, include_lock: bool = True) -> dict:
    kv = env_files.parse_env_file(_env_file_path(row))
    out = {
        "id": row["id"],
        "name": row["name"],
        "owner_id": row.get("owner_id"),
        "owner_name": row.get("owner_name"),
        "disabled": bool(row.get("disabled")),
        "created_at": fmt_dt(row.get("created_at")),
        "updated_at": fmt_dt(row.get("updated_at")),
        "missing": env_files.missing_keys(kv, _required_keys()),
    }
    if include_lock:
        out["lock"] = env_lock_view(row.get("relpath"))
    return out


def _get_env_checked(env_id: str, user: dict, need: str = "view") -> dict:
    """need: view（can_view_env）/ operate（can_operate_env）/ owner（owner|admin）。"""
    row = _env_or_404(env_id)
    if need == "view":
        ok = perms.can_view_env(user, env_id)
    elif need == "operate":
        ok = perms.can_operate_env(user, env_id)
    else:
        ok = perms.can_access_owner(user, row.get("owner_id"))
    if not ok:
        raise HTTPException(status_code=403, detail="forbidden")
    return row


# ------------------------------------------------------------------ routes

@router.get("/envs")
def list_envs(user: dict = Depends(get_current_user)) -> list[dict]:
    if perms.is_admin(user):
        rows = pool.query(_ENV_SELECT + "ORDER BY e.name")
    else:
        rows = pool.query(
            _ENV_SELECT
            + "WHERE e.owner_id = %s "
              "   OR EXISTS (SELECT 1 FROM env_grants g "
              "              WHERE g.env_id = e.id AND g.user_id = %s) "
              "ORDER BY e.name",
            (user["id"], user["id"]),
        )
    return [_env_view(r) for r in rows]


@router.post("/envs", status_code=201)
def create_env(body: EnvIn, user: dict = Depends(get_current_user)) -> dict:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="环境名称不能为空")
    parsed = env_files.parse_env_text(body.content or "")
    if not parsed:
        raise HTTPException(status_code=400, detail="env 内容解析结果为空（需要 KEY=VALUE 行）")

    env_id = secrets.token_hex(6)
    relpath = f"{user['username']}/{env_id}"
    env_file = console_dir() / relpath / "firebox.env"
    try:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text(body.content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"环境文件写入失败: {exc}") from exc
    pool.execute(
        "INSERT INTO environments (id, owner_id, name, relpath, created_at, "
        "updated_at, disabled) VALUES (%s, %s, %s, %s, NOW(3), NOW(3), 0)",
        (env_id, user["id"], name, relpath),
    )
    audit_dao.insert_audit(
        user["id"], "env.save", {"env_id": env_id, "name": name, "operator": user["username"]}
    )
    return _env_view(_env_row(env_id))


@router.get("/envs/{env_id}")
def get_env(env_id: str, user: dict = Depends(get_current_user)) -> dict:
    row = _get_env_checked(env_id, user, need="view")
    kv = env_files.parse_env_file(_env_file_path(row))
    redacted = env_files.redact_map(kv)
    out = _env_view(row)
    out["redacted"] = redacted
    # 脱敏后的文本（与 redacted map 同源；真实密钥不出网）
    out["content"] = "\n".join(f"{k}={v}" for k, v in redacted.items())
    return out


@router.patch("/envs/{env_id}")
def patch_env(
    env_id: str, body: EnvPatchIn, user: dict = Depends(get_current_user)
) -> dict:
    row = _get_env_checked(env_id, user, need="operate")
    sets: list[str] = ["updated_at = NOW(3)"]
    params: list = []
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="环境名称不能为空")
        sets.append("name = %s")
        params.append(name)
    if body.content is not None:
        parsed = env_files.parse_env_text(body.content)
        if not parsed:
            raise HTTPException(status_code=400, detail="env 内容解析结果为空（需要 KEY=VALUE 行）")
        try:
            _env_file_path(row).write_text(body.content, encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"环境文件写入失败: {exc}") from exc
    if body.disabled is not None:
        if not perms.is_admin(user):
            raise HTTPException(status_code=403, detail="disabled 仅 admin 可修改")
        sets.append("disabled = %s")
        params.append(1 if body.disabled else 0)
    params.append(env_id)
    pool.execute(f"UPDATE environments SET {', '.join(sets)} WHERE id = %s", tuple(params))
    audit_dao.insert_audit(
        user["id"],
        "env.save",
        {"env_id": env_id, "operator": user["username"], "fields": body.model_dump(exclude_none=True)},
    )
    return _env_view(_env_row(env_id))


@router.delete("/envs/{env_id}")
def delete_env(env_id: str, user: dict = Depends(get_current_user)) -> dict:
    row = _get_env_checked(env_id, user, need="owner")
    env_dir = console_dir() / str(row["relpath"])
    lock = env_lock.read_lock(env_dir)
    if lock and env_lock.pid_alive(int(lock.get("pid") or 0)):
        raise HTTPException(status_code=409, detail="环境锁被存活进程持有，请先停止任务或强制释放")
    pool.execute("DELETE FROM environments WHERE id = %s", (env_id,))  # env_grants CASCADE
    shutil.rmtree(env_dir, ignore_errors=True)
    audit_dao.insert_audit(
        user["id"], "env.del", {"env_id": env_id, "name": row["name"], "operator": user["username"]}
    )
    return {"ok": True}


@router.post("/lock/force-release")
def force_release(body: EnvIdIn, user: dict = Depends(get_current_user)) -> dict:
    row = _env_or_404(body.env_id)
    if not perms.can_access_owner(user, row.get("owner_id")):
        raise HTTPException(status_code=403, detail="forbidden")
    cleared, message = get_job_manager().clear_lock(row, user=user)
    return {"cleared": bool(cleared), "message": message}


# ------------------------------------------------------------------ grants

@router.get("/envs/{env_id}/grants")
def list_grants(env_id: str, user: dict = Depends(get_current_user)) -> list[dict]:
    _get_env_checked(env_id, user, need="view")
    rows = pool.query(
        "SELECT g.user_id, g.level, g.created_at, u.username "
        "FROM env_grants g JOIN users u ON u.id = g.user_id "
        "WHERE g.env_id = %s ORDER BY u.username",
        (env_id,),
    )
    return [{**r, "created_at": fmt_dt(r.get("created_at"))} for r in rows]


@router.put("/envs/{env_id}/grants")
def put_grants(
    env_id: str, body: GrantsIn, user: dict = Depends(get_current_user)
) -> list[dict]:
    row = _get_env_checked(env_id, user, need="owner")
    if body.grants is not None:
        items = [{"user_id": g.user_id, "level": g.level} for g in body.grants]
    elif body.user_id is not None:
        items = [{"user_id": body.user_id, "level": body.level or "operator"}]
    else:
        raise HTTPException(status_code=400, detail="需要 grants 列表或 user_id+level")
    for item in items:
        if item["level"] not in GRANT_LEVELS:
            raise HTTPException(
                status_code=400, detail=f"level 只能是 {' / '.join(GRANT_LEVELS)}"
            )
        if users_dao.get_by_id(item["user_id"]) is None:
            raise HTTPException(status_code=404, detail=f"用户不存在: {item['user_id']}")

    current = {
        g["user_id"]: g["level"]
        for g in pool.query(
            "SELECT user_id, level FROM env_grants WHERE env_id = %s", (env_id,)
        )
    }
    target = {int(i["user_id"]): i["level"] for i in items}

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM env_grants WHERE env_id = %s", (env_id,))
            if target:
                cur.executemany(
                    "INSERT INTO env_grants (env_id, user_id, level, granted_by, "
                    "created_at) VALUES (%s, %s, %s, %s, NOW(3))",
                    [(env_id, uid, level, user["id"]) for uid, level in target.items()],
                )

    # 审计：新增/变更 → env.grant；移除 → env.grant.revoke
    for uid, level in target.items():
        if current.get(uid) != level:
            audit_dao.insert_audit(
                user["id"],
                "env.grant",
                {
                    "env_id": env_id,
                    "name": row["name"],
                    "user_id": uid,
                    "level": level,
                    "operator": user["username"],
                },
            )
    for uid in set(current) - set(target):
        audit_dao.insert_audit(
            user["id"],
            "env.grant.revoke",
            {"env_id": env_id, "user_id": uid, "operator": user["username"]},
        )
    return list_grants(env_id, user)
