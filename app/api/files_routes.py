"""产物文件流：GET /runs/{run_id}/{relpath:path}（浏览器直开截图/报告）。

要点：
* 认证走 deps.get_current_user（Cookie rc_session 优先，<a>/<img> 等导航
  请求自动携带；Bearer 兼容脚本调试）。
* 权限 can_access_owner（run 归属经 job/loop 的 owner；owner 为 NULL 的
  legacy run 仅 admin 可见）。
* 路径穿越防护：resolve 后必须仍在 run 目录内。
* Content-Type 按扩展名（summary.html 特例即 .html → text/html）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.common import artifacts_root
from app.api.deps import get_current_user
from app.api.runs_routes import get_run_or_404

router = APIRouter()

# Content-Type 白名单（按扩展名；未命中 → application/octet-stream）
_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".json": "application/json",
    ".xml": "application/xml",
    ".css": "text/css",
    ".js": "text/javascript",
    ".tgz": "application/gzip",
    ".gz": "application/gzip",
    ".zip": "application/zip",
    ".pdf": "application/pdf",
}


@router.get("/runs/{run_id}/{relpath:path}")
def artifact_file(
    run_id: str, relpath: str, user: dict = Depends(get_current_user)
) -> FileResponse:
    get_run_or_404(run_id, user)
    base = (artifacts_root() / run_id).resolve()
    target = (base / relpath).resolve()
    # 穿越防护：resolve 后必须是 base 自身或其子路径
    if target != base and base not in target.parents:
        raise HTTPException(status_code=404, detail="not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在（未生成或已清理）")
    media_type = _CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(target, media_type=media_type)
