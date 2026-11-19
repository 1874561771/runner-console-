"""用户运行配置模板 CRUD。"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.common import fmt_dt
from app.api.deps import get_current_user
from app.core.scheduler import new_id
from app.db import pool
from app.db.dao import audit as audit_dao
from app.schemas import RunIn

router = APIRouter(prefix="/api")


class RunTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    run: RunIn


def _view(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "params": json.loads(row["params"]) if isinstance(row["params"], str) else row["params"],
        "created_at": fmt_dt(row.get("created_at")),
        "updated_at": fmt_dt(row.get("updated_at")),
    }


def _owned_or_404(template_id: str, user: dict) -> dict:
    row = pool.query_one(
        "SELECT * FROM run_templates WHERE id = %s AND owner_id = %s",
        (template_id, user["id"]),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="运行配置模板不存在")
    return row


@router.get("/run-templates")
def list_templates(user: dict = Depends(get_current_user)) -> list[dict]:
    rows = pool.query(
        "SELECT * FROM run_templates WHERE owner_id = %s ORDER BY updated_at DESC",
        (user["id"],),
    )
    return [_view(row) for row in rows]


@router.post("/run-templates", status_code=201)
def create_template(
    body: RunTemplateIn, user: dict = Depends(get_current_user)
) -> dict:
    template_id = new_id()
    now = datetime.now()
    name = body.name.strip()
    params = json.dumps(body.run.model_dump(), ensure_ascii=False)
    pool.execute(
        "INSERT INTO run_templates "
        "(id, owner_id, name, params, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (template_id, user["id"], name, params, now, now),
    )
    audit_dao.insert_audit(
        user["id"],
        "run_template.create",
        {"id": template_id, "name": name, "operator": user["username"]},
    )
    return {"template": _view(_owned_or_404(template_id, user))}


@router.put("/run-templates/{template_id}")
def update_template(
    template_id: str,
    body: RunTemplateIn,
    user: dict = Depends(get_current_user),
) -> dict:
    _owned_or_404(template_id, user)
    name = body.name.strip()
    pool.execute(
        "UPDATE run_templates SET name = %s, params = %s, updated_at = %s "
        "WHERE id = %s AND owner_id = %s",
        (
            name,
            json.dumps(body.run.model_dump(), ensure_ascii=False),
            datetime.now(),
            template_id,
            user["id"],
        ),
    )
    audit_dao.insert_audit(
        user["id"],
        "run_template.update",
        {"id": template_id, "name": name, "operator": user["username"]},
    )
    return {"template": _view(_owned_or_404(template_id, user))}


@router.delete("/run-templates/{template_id}")
def delete_template(
    template_id: str, user: dict = Depends(get_current_user)
) -> dict:
    row = _owned_or_404(template_id, user)
    pool.execute(
        "DELETE FROM run_templates WHERE id = %s AND owner_id = %s",
        (template_id, user["id"]),
    )
    audit_dao.insert_audit(
        user["id"],
        "run_template.delete",
        {"id": template_id, "name": row["name"], "operator": user["username"]},
    )
    return {"ok": True}
