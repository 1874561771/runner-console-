"""持久化任务队列 API。"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.api.common import fmt_dt
from app.api.deps import get_current_user
from app.auth import perms
from app.core.scheduler import new_id
from app.db import pool
from app.db.dao import audit as audit_dao
from app.schemas import RunIn

router = APIRouter(prefix="/api")

_SELECT = (
    "SELECT q.*, u.username AS owner_name, e.name AS env_name "
    "FROM run_queue q JOIN users u ON u.id = q.owner_id "
    "JOIN environments e ON e.id = q.env_id "
)


def _view(row: dict) -> dict:
    return {
        "id": row["id"],
        "owner_id": row["owner_id"],
        "owner_name": row.get("owner_name"),
        "env_id": row["env_id"],
        "env_name": row.get("env_name"),
        "params": json.loads(row["params"]) if isinstance(row["params"], str) else row["params"],
        "status": row["status"],
        "loop_id": row.get("loop_id"),
        "note": row.get("note") or "",
        "created_at": fmt_dt(row.get("created_at")),
        "started_at": fmt_dt(row.get("started_at")),
    }


@router.get("/run-queue")
def list_queue(user: dict = Depends(get_current_user)) -> list[dict]:
    if perms.is_admin(user):
        rows = pool.query(_SELECT + " ORDER BY q.created_at DESC LIMIT 200")
    else:
        rows = pool.query(
            _SELECT + " WHERE q.owner_id = %s ORDER BY q.created_at DESC LIMIT 200",
            (user["id"],),
        )
    return [_view(row) for row in rows]


@router.post("/run-queue", status_code=201)
def enqueue(body: RunIn, user: dict = Depends(get_current_user)) -> dict:
    env = pool.query_one("SELECT * FROM environments WHERE id = %s", (body.env_id,))
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    if env.get("disabled"):
        raise HTTPException(status_code=400, detail="环境已停用")
    if not perms.can_operate_env(user, body.env_id):
        raise HTTPException(status_code=403, detail="forbidden")
    if not body.suite and not body.test and not body.cases:
        raise HTTPException(status_code=400, detail="suite / test / cases 至少提供一个")

    queue_id = new_id()
    pool.execute(
        "INSERT INTO run_queue "
        "(id, owner_id, env_id, params, status, created_at) "
        "VALUES (%s, %s, %s, %s, 'queued', %s)",
        (
            queue_id,
            user["id"],
            body.env_id,
            json.dumps(body.model_dump(), ensure_ascii=False),
            datetime.now(),
        ),
    )
    audit_dao.insert_audit(
        user["id"],
        "run_queue.create",
        {"id": queue_id, "env_id": body.env_id, "operator": user["username"]},
    )
    row = pool.query_one(_SELECT + " WHERE q.id = %s", (queue_id,))
    return {"queue_item": _view(row)}


@router.delete("/run-queue/{queue_id}")
def cancel_queue_item(
    queue_id: str, user: dict = Depends(get_current_user)
) -> dict:
    row = pool.query_one(_SELECT + " WHERE q.id = %s", (queue_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="队列任务不存在")
    if not perms.can_access_owner(user, row["owner_id"]):
        raise HTTPException(status_code=403, detail="forbidden")
    if row["status"] not in ("queued", "failed"):
        raise HTTPException(status_code=409, detail="该队列任务已经启动，无法取消")
    pool.execute(
        "UPDATE run_queue SET status = 'cancelled', note = '用户取消' WHERE id = %s",
        (queue_id,),
    )
    audit_dao.insert_audit(
        user["id"],
        "run_queue.cancel",
        {"id": queue_id, "operator": user["username"]},
    )
    return {"ok": True}
