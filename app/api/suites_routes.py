"""保存的套件（saved_suites）CRUD——勾选 Case 集合的命名保存（T17）。

* GET    /api/suites        → [SuiteView]（自己的；admin 全量）
* POST   /api/suites        → 201 {suite}
* PUT    /api/suites/{id}   → {suite}（改名 / 改勾选集合）
* DELETE /api/suites/{id}   → {ok}

cases 存 case 脚本路径数组（相对 runner 仓库：scripts/<product>/<feature>/<case>.py）。
运行时运行台/定时任务按当前分支解析这些路径的内容——分支删了某个 case，
该条目会在运行结果里报错，属预期行为。
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.common import fmt_dt
from app.api.deps import get_current_user
from app.auth import perms
from app.core.scheduler import new_id
from app.db import pool
from app.db.dao import audit as audit_dao

router = APIRouter(prefix="/api")


class SuiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    product: str = "firebox"
    cases: list[str] = Field(min_length=1)


def _normalize(cases: list[str]) -> list[str]:
    out: list[str] = []
    for c in cases:
        c = (c or "").strip()
        if not c:
            continue
        if not c.startswith("scripts/") or not c.endswith(".py"):
            raise HTTPException(status_code=400, detail=f"case 路径须为 scripts/…/*.py：{c}")
        if c not in out:
            out.append(c)
    if not out:
        raise HTTPException(status_code=400, detail="cases 不能为空")
    return out


def _row_view(row: dict) -> dict:
    created = row.get("created_at")
    updated = row.get("updated_at")
    return {
        "id": row["id"],
        "name": row["name"],
        "product": row["product"],
        "cases": json.loads(row["cases"]) if isinstance(row["cases"], str) else row["cases"],
        "owner_id": row["owner_id"],
        "owner_name": row.get("owner_name"),
        "created_at": fmt_dt(created) if created else None,
        "updated_at": fmt_dt(updated) if updated else None,
    }


_SELECT = """
SELECT s.*, u.username AS owner_name
FROM saved_suites s LEFT JOIN users u ON u.id = s.owner_id
"""


def _get_owned(sid: str, user: dict) -> dict:
    row = pool.query_one(_SELECT + " WHERE s.id = %s", (sid,))
    if row is None:
        raise HTTPException(status_code=404, detail="套件不存在")
    if not perms.can_access_owner(user, row.get("owner_id")):
        raise HTTPException(status_code=403, detail="forbidden")
    return row


@router.get("/suites")
def list_suites(user: dict = Depends(get_current_user)) -> list[dict]:
    if perms.is_admin(user):
        rows = pool.query(_SELECT + " ORDER BY s.updated_at DESC")
    else:
        rows = pool.query(
            _SELECT + " WHERE s.owner_id = %s ORDER BY s.updated_at DESC", (user["id"],)
        )
    return [_row_view(r) for r in rows]


@router.post("/suites", status_code=201)
def create_suite(body: SuiteIn, user: dict = Depends(get_current_user)) -> dict:
    sid = new_id()
    now = datetime.now()
    cases = _normalize(body.cases)
    pool.execute(
        "INSERT INTO saved_suites (id, owner_id, name, product, cases, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (sid, user["id"], body.name.strip(), body.product,
         json.dumps(cases, ensure_ascii=False), now, now),
    )
    audit_dao.insert_audit(user["id"], "suite.create",
                           {"id": sid, "name": body.name, "cases": len(cases),
                            "operator": user["username"]})
    row = pool.query_one(_SELECT + " WHERE s.id = %s", (sid,))
    return {"suite": _row_view(row)}


@router.put("/suites/{sid}")
def update_suite(sid: str, body: SuiteIn, user: dict = Depends(get_current_user)) -> dict:
    _get_owned(sid, user)
    cases = _normalize(body.cases)
    pool.execute(
        "UPDATE saved_suites SET name = %s, product = %s, cases = %s, updated_at = %s "
        "WHERE id = %s",
        (body.name.strip(), body.product, json.dumps(cases, ensure_ascii=False),
         datetime.now(), sid),
    )
    audit_dao.insert_audit(user["id"], "suite.update",
                           {"id": sid, "name": body.name, "operator": user["username"]})
    row = pool.query_one(_SELECT + " WHERE s.id = %s", (sid,))
    return {"suite": _row_view(row)}


@router.delete("/suites/{sid}")
def delete_suite(sid: str, user: dict = Depends(get_current_user)) -> dict:
    row = _get_owned(sid, user)
    pool.execute("DELETE FROM saved_suites WHERE id = %s", (sid,))
    audit_dao.insert_audit(user["id"], "suite.del",
                           {"id": sid, "name": row["name"], "operator": user["username"]})
    return {"ok": True}
