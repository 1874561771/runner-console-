"""业务路由：顶栏轮询 GET /api/status 与运行台配置 GET /api/config。

契约权威：
* /api/status —— frontend/js/main.js pollStatus（2s 轮询）消费 `st.jobs`
  的长度决定顶栏胶囊 idle/running；mock-data.js 的 mock 形状为
  jobs: [{loop_id, iteration, repeat_total, console_tail}]。
  另附任务清单要求的 status / active_loops / env_locks / consoles 字段。
* /api/config —— main.js 消费 workdir；views/console.js 消费
  products / branches[{name,current}] / suites[{name,cases}] / tests[]。
  suites/tests 按 ?git_ref=（默认 HEAD）从 runner 仓库列出（git ls-tree，
  HEAD 走本地文件，不扫历史）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from app.api.common import env_lock_view
from app.api.deps import get_current_user
from app.auth import perms
from app.core import git_worktree
from app.core.job_manager import PRODUCTS, get_job_manager
from app.db import pool

router = APIRouter(prefix="/api")


@router.get("/status")
def status(user: dict = Depends(get_current_user)) -> dict:
    manager = get_job_manager()
    snapshots = [r.snapshot() for r in manager.active()]
    if not perms.is_admin(user):
        snapshots = [s for s in snapshots if s.get("owner_id") == user["id"]]

    # env_name 批量补齐（active_loops 用）
    env_ids = {s.get("env_id") for s in snapshots if s.get("env_id")}
    env_names: dict[str, str] = {}
    if env_ids:
        placeholders = ", ".join(["%s"] * len(env_ids))
        for row in pool.query(
            f"SELECT id, name FROM environments WHERE id IN ({placeholders})",
            tuple(env_ids),
        ):
            env_names[row["id"]] = row["name"]

    jobs = []
    active_loops = []
    consoles = {}
    for snap in snapshots:
        loop_id = snap["loop_id"]
        jobs.append(
            {
                "loop_id": loop_id,
                "iteration": snap.get("iteration"),
                "repeat_total": snap.get("repeat_total"),
                "console_tail": manager.console_tail(loop_id, 3),
            }
        )
        active_loops.append(
            {
                "loop_id": loop_id,
                "env_name": env_names.get(snap.get("env_id")),
                "iteration": snap.get("iteration"),
            }
        )
        consoles[loop_id] = manager.console_tail(loop_id, 60)

    env_locks = []
    for row in pool.query("SELECT id, relpath FROM environments"):
        lock = env_lock_view(row.get("relpath"))
        env_locks.append({"env_id": row["id"], **lock})

    return {
        "status": "running" if jobs else "idle",
        "jobs": jobs,
        "active_loops": active_loops,
        "env_locks": env_locks,
        "consoles": consoles,
    }


@router.get("/config")
def config(git_ref: str = "", user: dict = Depends(get_current_user)) -> dict:
    manager = get_job_manager()
    workdir: Path = manager.workdir
    ref = (git_ref or "").strip() or "HEAD"

    branches = git_worktree.list_branches(workdir)
    suites = [
        {"name": Path(p).stem, "cases": _count_suite_cases(workdir, p, ref)}
        for p in git_worktree.list_tree_files(workdir, ref, "suites")
        if p.endswith(".txt")
    ]
    tests = [
        p for p in git_worktree.list_tree_files(workdir, ref, "scripts")
        if p.endswith(".py") and not Path(p).name.startswith("_")
    ]
    return {
        "workdir": str(workdir),
        "products": list(PRODUCTS),
        "branches": branches,
        "suites": suites,
        "tests": tests,
    }


@router.get("/cases")
def cases(ref: str = "", product: str = "", user: dict = Depends(get_current_user)) -> dict:
    """按分支列出 case（勾选 Case 模式的数据源，T17）。

    返回按 feature（scripts/<product> 下的子目录）分组的 case 列表，
    供前端勾选器展示（搜索 / 全选 / 清除在前端做）。
    """
    manager = get_job_manager()
    workdir: Path = manager.workdir
    r = (ref or "").strip() or "HEAD"
    prefix = f"scripts/{product.strip()}" if (product or "").strip() else "scripts"
    files = [
        p for p in git_worktree.list_tree_files(workdir, r, prefix)
        if p.endswith(".py") and not Path(p).name.startswith("_")
    ]
    groups: dict[str, list[str]] = {}
    for p in files:
        parts = p.split("/")
        feature = "/".join(parts[:-1]) if len(parts) > 2 else "(root)"
        groups.setdefault(feature, []).append(p)
    return {
        "ref": r,
        "total": len(files),
        "groups": [{"feature": k, "cases": v} for k, v in sorted(groups.items())],
    }


def _count_suite_cases(workdir: Path, relpath: str, ref: str) -> int:
    """suite 文件的 case 行数（非空非注释）；仅本地可读（HEAD）时统计。"""
    if ref not in ("", "HEAD", "(workdir)"):
        return 0
    try:
        text = (workdir / relpath).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(
        1
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
