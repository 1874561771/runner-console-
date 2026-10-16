"""Per-environment (or per-directory) runner lock.

迁移自 webui/env_lock.py，逻辑保持一致（Windows ctypes OpenProcess 判活保留）。

The lab may have many Firebox environments. Each environment is locked
independently so two jobs can run in parallel as long as they use different
env files. The lock is a small JSON file next to the env file:

    <env-dir>/.runner.lock

适配说明：锁目录由调用方决定——RunnerConsole 里是 environments 表 relpath
相对 config.paths.console_dir 解析出的 env 目录（env 文件所在目录即锁目录）。
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

LOCK_NAME = ".runner.lock"
_RETRIES = 3
_RETRY_SLEEP = 0.25


def lock_path(lock_dir: Path) -> Path:
    return Path(lock_dir).expanduser().resolve() / LOCK_NAME


def pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform.startswith("win"):
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return kernel32.GetLastError() != 87
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def read_lock(lock_dir: Path) -> dict | None:
    path = lock_path(lock_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        info = json.loads(text)
    except json.JSONDecodeError:
        return None
    return info if isinstance(info, dict) else None


def _write_atomic(path: Path, info: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def acquire(
    lock_dir: Path,
    *,
    run_id: str | None,
    source: str,
    command: list[str],
    extra: dict | None = None,
) -> tuple[bool, dict]:
    path = lock_path(lock_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    info = {
        "pid": os.getpid(),
        "token": secrets.token_hex(8),
        "run_id": run_id,
        "source": source,
        "host": _hostname(),
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "command": list(command),
    }
    if extra:
        info.update(extra)

    for _ in range(_RETRIES + 1):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = read_lock(lock_dir)
            if holder is None:
                time.sleep(_RETRY_SLEEP)
                holder = read_lock(lock_dir)
            if holder is not None and pid_alive(int(holder.get("pid") or 0)):
                return False, holder
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            continue

        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False, indent=2)
        return True, dict(info)

    _write_atomic(path, info)
    return True, dict(info)


def update(lock_dir: Path, token: str, **fields: object) -> bool:
    path = lock_path(lock_dir)
    info = read_lock(lock_dir)
    if info is None or info.get("token") != token:
        return False
    info.update({k: v for k, v in fields.items() if v is not None})
    try:
        _write_atomic(path, info)
        return True
    except OSError:
        return False


def release(lock_dir: Path, token: str | None) -> bool:
    if not token:
        return False
    path = lock_path(lock_dir)
    info = read_lock(lock_dir)
    if info is None:
        return True
    if info.get("token") != token:
        return False
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def force_release(lock_dir: Path) -> dict | None:
    path = lock_path(lock_dir)
    info = read_lock(lock_dir)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return None
    return info


def describe(holder: dict) -> str:
    if not holder:
        return "未知占用者"
    parts = []
    rid = holder.get("run_id")
    parts.append(f"run {rid}" if rid else "run_id 未生成")
    parts.append(f"PID {holder.get('pid', '?')}")
    if holder.get("owner"):
        parts.append(f"user {holder['owner']}")
    if holder.get("host"):
        parts.append(f"host {holder['host']}")
    parts.append(f"来源 {holder.get('source', '?')}")
    if holder.get("started_at"):
        parts.append(f"开始于 {holder['started_at']}")
    return " · ".join(parts)


def info_payload(lock_dir: Path) -> dict:
    holder = read_lock(lock_dir)
    if not holder:
        return {
            "held": False, "stale": False, "run_id": None, "pid": None,
            "host": None, "started_at": None, "source": None, "owner": None,
        }
    return {
        "held": True,
        "stale": not pid_alive(int(holder.get("pid") or 0)),
        "run_id": holder.get("run_id"),
        "pid": holder.get("pid"),
        "host": holder.get("host"),
        "started_at": holder.get("started_at"),
        "source": holder.get("source"),
        "owner": holder.get("owner"),
        "loop_id": holder.get("loop_id"),
    }
