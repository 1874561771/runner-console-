"""业务路由：我的上传（suite / script）。

契约权威 = frontend/js/api.js mockRoutes + mock-data.js + views/resources.js：
* GET    /api/uploads           → [{id, kind, name, relpath, owner_name, uploaded_at}]
* POST   /api/uploads           form-data file（.py → script，其余 → suite）→ 201
* DELETE /api/uploads/{id}      owner|admin → {ok: true}

存储：console_dir/uploads/<username>/<uid>/<filename>（DB relpath 记相对
console_dir/uploads 的完整路径，API 输出文件名形式，与 mock 一致）。
"""

from __future__ import annotations

import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.common import console_dir, fmt_dt
from app.api.deps import get_current_user
from app.auth import perms
from app.db import pool
from app.db.dao import audit as audit_dao

router = APIRouter(prefix="/api")

_UPLOAD_SELECT = (
    "SELECT up.*, u.username AS owner_name "
    "FROM uploads up JOIN users u ON u.id = up.owner_id "
)


def _upload_row(upload_id: str) -> dict | None:
    return pool.query_one(_UPLOAD_SELECT + "WHERE up.id = %s", (upload_id,))


def _upload_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "name": row["name"],
        "relpath": Path(str(row["relpath"])).name,  # 文件名形式（mock 契约）
        "owner_name": row.get("owner_name"),
        "uploaded_at": fmt_dt(row.get("created_at")),
    }


@router.get("/uploads")
def list_uploads(user: dict = Depends(get_current_user)) -> list[dict]:
    if perms.is_admin(user):
        rows = pool.query(_UPLOAD_SELECT + "ORDER BY up.created_at DESC")
    else:
        rows = pool.query(
            _UPLOAD_SELECT + "WHERE up.owner_id = %s ORDER BY up.created_at DESC",
            (user["id"],),
        )
    return [_upload_view(r) for r in rows]


@router.post("/uploads", status_code=201)
def create_upload(
    file: UploadFile = File(...), user: dict = Depends(get_current_user)
) -> dict:
    # 只取 basename，防路径穿越；空名拒绝
    name = Path(file.filename or "").name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    kind = "script" if name.lower().endswith(".py") else "suite"

    uid = secrets.token_hex(6)
    rel = f"{user['username']}/{uid}/{name}"
    dest = console_dir() / "uploads" / rel
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"上传文件保存失败: {exc}") from exc

    pool.execute(
        "INSERT INTO uploads (id, owner_id, kind, name, relpath, created_at) "
        "VALUES (%s, %s, %s, %s, %s, NOW(3))",
        (uid, user["id"], kind, name, rel),
    )
    audit_dao.insert_audit(
        user["id"],
        "upload.create",
        {"upload_id": uid, "kind": kind, "name": name, "operator": user["username"]},
    )
    return _upload_view(_upload_row(uid))


@router.delete("/uploads/{upload_id}")
def delete_upload(upload_id: str, user: dict = Depends(get_current_user)) -> dict:
    row = _upload_row(upload_id)
    if row is None:
        raise HTTPException(status_code=404, detail="上传件不存在")
    if not perms.can_access_owner(user, row.get("owner_id")):
        raise HTTPException(status_code=403, detail="forbidden")
    path = console_dir() / "uploads" / str(row["relpath"])
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass  # 文件删除失败不阻断 DB 清理（孤儿文件由保留策略兜底）
    pool.execute("DELETE FROM uploads WHERE id = %s", (upload_id,))
    audit_dao.insert_audit(
        user["id"],
        "upload.del",
        {"upload_id": upload_id, "name": row["name"], "operator": user["username"]},
    )
    return {"ok": True}
