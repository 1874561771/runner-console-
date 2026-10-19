"""运行发起服务：POST /api/run 与定时任务调度共用的入口。

从 loops_routes.run 抽取（T16）：两者需要完全一致的参数校验、cases→临时
suite 生成、overlay 组装与 manager.start 调用。业务错误统一抛 RunError，
由调用方（HTTP 路由 → HTTPException；调度器 → 记录 last_status）翻译。

cases 模式：调用方传 case 脚本路径集合（分支上的 scripts/**/*.py），
这里生成临时 suite 文件（runner suite 格式：一行一个脚本路径），经现有
overlay 链路复制进 worktree 的 suites/ 下。loop 结束时 worktree 整体清理，
LoopRunner 的 finally 还会删除 data/console/tmp 下的源文件——临时 suite
不会残留到真实仓库的 suites 目录。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from app.api.common import console_dir, upload_abs_path
from app.core.job_manager import PRODUCTS, LoopStartError, get_job_manager
from app.db import pool
from app.schemas import RunIn


class RunError(Exception):
    """业务校验/启动失败。status: 400/403/404/409；holder：环境锁持有者（409 时）。"""

    def __init__(self, status: int, detail: str, holder: str | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.holder = holder


def _tmp_suite_path() -> tuple[str, Path]:
    """生成临时 suite 的 (suite_name, 源文件路径)。源文件放 console tmp 目录。"""
    name = f"rc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    tmp_dir = console_dir() / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return name, tmp_dir / f"{name}.txt"


def do_start_run(user: dict, body: RunIn) -> dict:
    """校验并发起一个 loop。成功返回 {"loop_id", "command", "repeat"}。"""
    manager = get_job_manager()

    env_row = pool.query_one("SELECT * FROM environments WHERE id = %s", (body.env_id,))
    if env_row is None:
        raise RunError(404, "环境不存在")
    if env_row.get("disabled"):
        raise RunError(400, "环境已停用，不能运行")
    from app.auth import perms  # 局部导入避免环

    if not perms.can_operate_env(user, body.env_id):
        raise RunError(403, "forbidden")

    params = {
        "product": (body.product or "").strip(),
        "suite": (body.suite or "").strip(),
        "test": (body.test or "").strip(),
        "git_ref": body.git_ref,
        "headless": bool(body.headless),
        "branch": body.branch,
        "build": body.build,
        "pause_on_fail": bool(body.pause_on_fail),
        "source": body.source if body.source in ("repo", "upload") else "repo",
    }
    if params["product"] not in PRODUCTS:
        raise RunError(400, f"product 必须是：{', '.join(PRODUCTS)}")

    overlays: list[tuple[str, Path]] = []
    if params["source"] == "upload":
        up = pool.query_one("SELECT * FROM uploads WHERE id = %s", (body.upload_id or "",))
        if up is None:
            raise RunError(404, "上传件不存在")
        if not perms.can_access_owner(user, up.get("owner_id")):
            raise RunError(403, "forbidden")
        # 我的测试：suite 用名称（去扩展名）、script 用 overlay 相对路径
        #（= 上传文件名；DB relpath 是 '<user>/<uid>/<name>' 存储路径，不能直接当 CLI 参数）
        rel_name = Path(str(up["relpath"])).name
        if up["kind"] == "suite":
            # runner 在 <worktree>/suites/ 下找 suite（--suite 先补 .txt 再用原名），
            # overlay 必须复制到 suites/ 内而不是 worktree 根
            params["suite"] = Path(str(up["name"])).stem
            overlays = [(f"suites/{rel_name}", upload_abs_path(up))]
        else:
            params["test"] = rel_name
            overlays = [(rel_name, upload_abs_path(up))]
    elif body.cases:
        # 勾选 Case 模式：生成临时 suite 注入 worktree（随 worktree 清理删除）
        cases = [c.strip() for c in body.cases if c and c.strip()]
        if not cases:
            raise RunError(400, "cases 不能为空")
        bad = [c for c in cases if not c.startswith("scripts/")]
        if bad:
            raise RunError(400, f"case 路径必须以 scripts/ 开头：{bad[:3]}")
        suite_name, tmp_path = _tmp_suite_path()
        tmp_path.write_text("\n".join(cases) + "\n", encoding="utf-8")
        params["suite"] = suite_name
        overlays.append((f"suites/{suite_name}.txt", tmp_path))

    if not params["suite"] and not params["test"]:
        raise RunError(400, "suite / test / cases 至少提供一个")

    repeat = body.repeat if body.repeat is not None else 1
    if repeat < 0:
        raise RunError(400, "repeat 不能为负数（0=无限）")

    try:
        return manager.start(
            user=user,
            env_row=env_row,
            params=params,
            repeat=int(repeat),
            overlays=overlays,
        )
    except LoopStartError as exc:
        raise RunError(409, str(exc), holder=getattr(exc, "holder", None)) from exc
