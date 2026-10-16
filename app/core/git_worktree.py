"""Git worktree helpers: list branches, check out a ref for one job, overlay files.

迁移自 webui/git_worktree.py，逻辑保持一致。

适配说明：路径全部由调用方传入——
* worktree 根目录 = config.paths.console_dir / "worktrees"（JobManager 注入）；
* artifacts 链接目标 = config.paths.artifacts_root；
* git 命令的 cwd = config.paths.workdir。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


class GitError(Exception):
    pass


def _run(args: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def is_git_repo(workdir: Path) -> bool:
    return (workdir / ".git").exists() or (workdir / ".git").is_file()


_BRANCH_CACHE_TTL = 60.0
_BRANCH_CACHE: dict = {"key": None, "data": [], "at": 0.0}


def list_branches(workdir: Path) -> list[dict]:
    """Remote + local branch names. Does a best-effort fetch (ignored on failure).

    带 60s TTL 缓存：git fetch 每次要数秒（内网 GitLab），运行台每次渲染
    都调本函数，不缓存会拖慢整个 /api/config。切分支后最多 60s 延迟。
    """
    key = str(workdir)
    now = time.monotonic()
    if _BRANCH_CACHE["key"] == key and now - _BRANCH_CACHE["at"] < _BRANCH_CACHE_TTL:
        return _BRANCH_CACHE["data"]
    if not is_git_repo(workdir):
        return []
    try:
        _run(["git", "fetch", "--prune", "origin"], cwd=workdir, timeout=8)
    except Exception:
        pass
    names: list[str] = []
    r = _run(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes/origin"], cwd=workdir)
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            name = line.strip()
            if not name or name == "origin" or name.endswith("/HEAD"):
                continue
            if name.startswith("origin/"):
                name = name[len("origin/"):]
            if name not in names:
                names.append(name)
    head = current_head(workdir)
    data = [{"name": n, "current": n == head} for n in names]
    _BRANCH_CACHE.update(key=key, data=data, at=now)
    return data


def current_head(workdir: Path) -> str:
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workdir)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def list_tree_files(workdir: Path, git_ref: str, prefix: str) -> list[str]:
    if not git_ref or git_ref == "HEAD" or git_ref == "(workdir)":
        root = workdir / prefix
        if not root.is_dir():
            return []
        out = []
        for f in sorted(root.rglob("*")):
            if f.is_file():
                out.append(f.relative_to(workdir).as_posix())
        return out
    ref = _resolve_ref(workdir, git_ref)
    r = _run(["git", "ls-tree", "-r", "--name-only", ref, prefix], cwd=workdir)
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _resolve_ref(workdir: Path, git_ref: str) -> str:
    for cand in (git_ref, "origin/" + git_ref, "refs/heads/" + git_ref):
        r = _run(["git", "rev-parse", "--verify", cand], cwd=workdir)
        if r.returncode == 0:
            return cand
    raise GitError(f"找不到 Git 分支/引用：{git_ref}（请确认已 fetch）")


def prepare_worktree(workdir: Path, dest: Path, git_ref: str) -> Path:
    dest = dest.resolve()
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run(["git", "fetch", "--prune", "origin"], cwd=workdir, timeout=90)
    except Exception:
        pass
    if git_ref in ("", "HEAD", "(workdir)"):
        ref = "HEAD"
    else:
        ref = _resolve_ref(workdir, git_ref)
    r = _run(
        ["git", "worktree", "add", "--detach", str(dest), ref],
        cwd=workdir,
        timeout=90,
    )
    if r.returncode != 0:
        raise GitError((r.stderr or r.stdout or "git worktree add failed").strip()[:800])
    return dest


def link_artifacts(worktree: Path, artifacts_dir: Path) -> None:
    """Point worktree/artifacts at the shared artifacts directory."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    link = worktree / "artifacts"
    if link.exists() or link.is_symlink():
        if link.is_dir() and not link.is_symlink():
            shutil.rmtree(link, ignore_errors=True)
        else:
            link.unlink(missing_ok=True)
    try:
        os.symlink(str(artifacts_dir.resolve()), str(link), target_is_directory=True)
        return
    except OSError:
        pass
    if sys.platform.startswith("win"):
        r = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(artifacts_dir.resolve())],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return
    # Last resort: just mkdir; artifacts stay inside the worktree.
    link.mkdir(parents=True, exist_ok=True)


def overlay_file(worktree: Path, relpath: str, src: Path) -> None:
    dest = worktree / relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def copy_env(worktree: Path, env_file: Path) -> None:
    dest = worktree / "framework" / "firebox" / ".firebox_env"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(env_file, dest)


def _is_junction(path: Path) -> bool:
    """Windows 目录 junction 检测（os.path.isjunction 需 Python 3.12+）。"""
    try:
        return os.path.isjunction(str(path))
    except AttributeError:
        return False


def _unlink_link(link: Path) -> None:
    """移除 symlink/junction 链接本身，不触碰目标内容。"""
    try:
        link.unlink()
    except OSError:
        link.rmdir()  # junction 在部分 Windows 版本需按空目录移除


def remove_worktree(workdir: Path, dest: Path) -> None:
    dest = dest.resolve()
    # 必须先摘除 artifacts 链接再交给 git：git worktree remove --force 递归
    # 删除目录树时会穿透 junction/symlink，把共享产物根（artifacts_root）
    # 整体清空（Windows 下已实测复现）。Python 的 shutil.rmtree 自 3.12 起
    # 有 junction 防护，git 没有。
    link = dest / "artifacts"
    if link.is_symlink() or _is_junction(link):
        _unlink_link(link)
    r = _run(["git", "worktree", "remove", "--force", str(dest)], cwd=workdir, timeout=60)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    if r.returncode != 0:
        _run(["git", "worktree", "prune"], cwd=workdir)
