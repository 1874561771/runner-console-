"""T7 业务路由共享小工具。

仅被 app.api.* 路由模块 import；不 import core/job_manager（避免装载顺序
耦合），需要 env_root / 上传路径时由调用方从 config 传入或用本模块的
path helper（只依赖 app.config / app.core.env_lock）。
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from app.config import get_settings
from app.core import env_lock


# ------------------------------------------------------------------ time

def fmt_dt(value, fmt: str = "%Y-%m-%d %H:%M:%S"):
    """DB datetime/date → mock 契约的 'YYYY-MM-DD HH:MM:SS'；None/其他原样返回。"""
    if isinstance(value, (datetime, date)):
        return value.strftime(fmt)
    return value


# --------------------------------------------------------- query params

def parse_int(raw, default: int | None = None) -> int | None:
    """query 字符串 → int；空/非法返回 default。"""
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def parse_days(raw: str | None):
    """days=today|7|14|30|all → None(all) / 'today' / 正整数；非法归 all。"""
    if raw in (None, "", "all"):
        return None
    if raw == "today":
        return "today"
    n = parse_int(raw)
    return n if n is not None and n > 0 else None


# ----------------------------------------------------------------- paths

def console_dir() -> Path:
    """config.paths.console_dir（env 注册 / 上传的根，resolve 后返回）。"""
    return Path(get_settings().paths.console_dir).expanduser().resolve()


def artifacts_root() -> Path:
    """config.paths.artifacts_root（run 产物根，resolve 后返回）。"""
    return Path(get_settings().paths.artifacts_root).expanduser().resolve()


def env_dir_for(relpath: str | None) -> Path | None:
    """environments.relpath → env 目录（也是锁目录）；relpath 为空返回 None。"""
    if not relpath:
        return None
    return console_dir() / str(relpath)


def upload_abs_path(upload_row: dict) -> Path:
    """uploads 表行 → 上传文件绝对路径。

    DB relpath 约定为相对 console_dir/uploads 的 '<username>/<uid>/<name>'。
    """
    return console_dir() / "uploads" / str(upload_row.get("relpath") or "")


# ------------------------------------------------------------------ lock

def env_lock_view(relpath: str | None) -> dict:
    """环境锁视图（mock 契约形状：{held, stale, run_id, owner_name}）。"""
    env_dir = env_dir_for(relpath)
    info = env_lock.info_payload(env_dir) if env_dir else {
        "held": False, "stale": False, "run_id": None, "owner": None,
    }
    return {
        "held": bool(info.get("held")),
        "stale": bool(info.get("stale")),
        "run_id": info.get("run_id"),
        "owner_name": info.get("owner"),
    }
