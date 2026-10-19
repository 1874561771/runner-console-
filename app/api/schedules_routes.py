"""定时任务 CRUD + 立即触发（T16）。

契约（frontend/js/api.js mockRoutes 同步维护）：
* GET    /api/schedules                    → [ScheduleView]
* POST   /api/schedules                    → 201 {schedule}
* PATCH  /api/schedules/{id}               → {schedule}   （改名/改规则/启停/改配置）
* DELETE /api/schedules/{id}               → {ok}
* POST   /api/schedules/{id}/run-now       → {loop_id}    （立即触发一次，不改规则）

权限：普通用户只能看到/操作自己的；admin 可见全部。
params 是 RunIn 快照（JSON），触发时经 run_service.do_start_run 发起——
与 POST /api/run 同一入口；git_ref 存分支名 = 每次运行取该分支最新。
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.common import fmt_dt
from app.api.deps import get_current_user
from app.auth import perms
from app.core import run_service, scheduler as sched_mod
from app.db import pool
from app.db.dao import audit as audit_dao
from app.schemas import RunIn

router = APIRouter(prefix="/api")


class ScheduleIn(BaseModel):
    name: str
    rule_type: str                     # daily | once
    time: str | None = None            # daily 用 'HH:MM'
    run_at: str | None = None          # once 用 'YYYY-MM-DD HH:MM'
    enabled: bool = True
    run: RunIn


def _validate_rule(body: ScheduleIn) -> tuple[str, str | None, datetime | None]:
    if body.rule_type not in ("daily", "once"):
        raise HTTPException(status_code=400, detail="rule_type 必须是 daily 或 once")
    if body.rule_type == "daily":
        t = (body.time or "").strip()
        try:
            hh, mm = t.split(":")
            if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="time 格式应为 HH:MM（24 小时制）")
        return t, None, None
    # once
    raw = (body.run_at or "").strip()
    try:
        run_at = datetime.strptime(raw, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="run_at 格式应为 YYYY-MM-DD HH:MM")
    return "", raw, run_at


def _row_view(row: dict) -> dict:
    next_at = row.get("next_run_at")
    run_at = row.get("run_at")
    created = row.get("created_at")
    return {
        "id": row["id"],
        "name": row["name"],
        "owner_id": row["owner_id"],
        "owner_name": row.get("owner_name"),
        "env_id": row["env_id"],
        "env_name": row.get("env_name"),
        "params": json.loads(row["params"]) if isinstance(row["params"], str) else row["params"],
        "rule_type": row["rule_type"],
        "time": row.get("rule_time") or None,
        "run_at": fmt_dt(run_at) if run_at else None,
        "enabled": bool(row["enabled"]),
        "next_run_at": fmt_dt(next_at) if next_at else None,
        "last_loop_id": row.get("last_loop_id"),
        "last_status": row.get("last_status"),
        "last_note": row.get("last_note"),
        "created_at": fmt_dt(created) if created else None,
    }


_SELECT = """
SELECT s.*, u.username AS owner_name, e.name AS env_name
FROM schedules s
LEFT JOIN users u ON u.id = s.owner_id
LEFT JOIN environments e ON e.id = s.env_id
"""


def _get_row(sid: str) -> dict:
    row = pool.query_one(_SELECT + " WHERE s.id = %s", (sid,))
    if row is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return row


def _get_owned(sid: str, user: dict) -> dict:
    row = _get_row(sid)
    if not perms.can_access_owner(user, row.get("owner_id")):
        raise HTTPException(status_code=403, detail="forbidden")
    return row


@router.get("/schedules")
def list_schedules(user: dict = Depends(get_current_user)) -> list[dict]:
    if perms.is_admin(user):
        rows = pool.query(_SELECT + " ORDER BY s.created_at DESC")
    else:
        rows = pool.query(
            _SELECT + " WHERE s.owner_id = %s ORDER BY s.created_at DESC",
            (user["id"],),
        )
    return [_row_view(r) for r in rows]


@router.post("/schedules", status_code=201)
def create_schedule(body: ScheduleIn, user: dict = Depends(get_current_user)) -> dict:
    rule_time, _raw, run_at = _validate_rule(body)
    sid = sched_mod.new_id()
    now = datetime.now()
    next_at = (
        run_at
        if body.rule_type == "once"
        else sched_mod.next_daily_occurrence(rule_time, now)
    )
    pool.execute(
        "INSERT INTO schedules (id, owner_id, name, env_id, params, rule_type, "
        "rule_time, run_at, enabled, next_run_at, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (sid, user["id"], body.name.strip()[:128], body.run.env_id,
         json.dumps(body.run.model_dump(), ensure_ascii=False),
         body.rule_type, rule_time, run_at, int(body.enabled), next_at, now),
    )
    audit_dao.insert_audit(user["id"], "schedule.create",
                           {"id": sid, "name": body.name, "operator": user["username"]})
    return {"schedule": _row_view(_get_row(sid))}


@router.patch("/schedules/{sid}")
def update_schedule(sid: str, body: dict, user: dict = Depends(get_current_user)) -> dict:
    row = _get_owned(sid, user)
    sets: list[str] = []
    args: list = []
    if "name" in body and str(body["name"]).strip():
        sets.append("name = %s")
        args.append(str(body["name"]).strip()[:128])
    if "enabled" in body:
        sets.append("enabled = %s")
        args.append(int(bool(body["enabled"])))
    rule_type = body.get("rule_type", row["rule_type"])
    if "rule_type" in body or "time" in body or "run_at" in body:
        if rule_type not in ("daily", "once"):
            raise HTTPException(status_code=400, detail="rule_type 必须是 daily 或 once")
        sets.append("rule_type = %s")
        args.append(rule_type)
        if rule_type == "daily":
            t = (body.get("time") or row.get("rule_time") or "").strip()
            try:
                hh, mm = t.split(":")
                if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                    raise ValueError
            except (ValueError, AttributeError):
                raise HTTPException(status_code=400, detail="time 格式应为 HH:MM")
            sets += ["rule_time = %s", "run_at = NULL"]
            args.append(t)
            sets.append("next_run_at = %s")
            args.append(sched_mod.next_daily_occurrence(t))
        else:
            raw = (body.get("run_at") or "").strip()
            try:
                run_at = datetime.strptime(raw, "%Y-%m-%d %H:%M")
            except ValueError:
                raise HTTPException(status_code=400, detail="run_at 格式应为 YYYY-MM-DD HH:MM")
            sets += ["run_at = %s", "next_run_at = %s"]
            args += [run_at, run_at]
    if "run" in body and isinstance(body["run"], dict):
        try:
            run_in = RunIn(**body["run"])
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"run 配置非法：{exc}")
        sets.append("params = %s")
        args.append(json.dumps(run_in.model_dump(), ensure_ascii=False))
        sets.append("env_id = %s")
        args.append(run_in.env_id)
    if not sets:
        raise HTTPException(status_code=400, detail="没有要更新的字段")
    args.append(sid)
    pool.execute(f"UPDATE schedules SET {', '.join(sets)} WHERE id = %s", tuple(args))
    audit_dao.insert_audit(user["id"], "schedule.update",
                           {"id": sid, "operator": user["username"]})
    return {"schedule": _row_view(_get_row(sid))}


@router.delete("/schedules/{sid}")
def delete_schedule(sid: str, user: dict = Depends(get_current_user)) -> dict:
    row = _get_owned(sid, user)
    pool.execute("DELETE FROM schedules WHERE id = %s", (sid,))
    audit_dao.insert_audit(user["id"], "schedule.del",
                           {"id": sid, "name": row["name"], "operator": user["username"]})
    return {"ok": True}


@router.post("/schedules/{sid}/run-now")
def run_schedule_now(sid: str, user: dict = Depends(get_current_user)) -> dict:
    row = _get_owned(sid, user)
    body = RunIn(**json.loads(row["params"]))
    try:
        result = run_service.do_start_run(user, body)
    except run_service.RunError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    now = datetime.now()
    pool.execute(
        "UPDATE schedules SET last_loop_id = %s, last_status = 'started', "
        "last_note = %s, next_run_at = %s WHERE id = %s",
        (result["loop_id"], f"手动触发 loop {result['loop_id']}",
         sched_mod.next_daily_occurrence(row["rule_time"], now)
         if row["rule_type"] == "daily" else None,
         sid),
    )
    if row["rule_type"] == "once":
        pool.execute("UPDATE schedules SET enabled = 0 WHERE id = %s", (sid,))
    audit_dao.insert_audit(user["id"], "schedule.run",
                           {"id": sid, "loop_id": result["loop_id"], "operator": user["username"]})
    return {"loop_id": result["loop_id"]}
