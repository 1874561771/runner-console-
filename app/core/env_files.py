"""Parse / redact .firebox_env files.

迁移自 webui/env_files.py，逻辑保持一致。

适配说明：env 文件路径由调用方解析——
environments 表 relpath 相对 config.paths.console_dir 的目录下的 firebox.env。
"""

from __future__ import annotations

import re
from pathlib import Path

SECRET_RE = re.compile(r"(PASSWORD|SECRET|TOKEN|CREDENTIAL|_KEY$)", re.I)


def parse_env_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def parse_env_file(path: Path) -> dict[str, str]:
    try:
        return parse_env_text(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def is_secret_key(key: str) -> bool:
    return bool(SECRET_RE.search(key))


def redact_map(kv: dict[str, str]) -> dict[str, str]:
    return {k: ("••••••" if is_secret_key(k) and v else v) for k, v in kv.items()}


def example_keys(example_path: Path) -> list[str]:
    if not example_path.is_file():
        return []
    return list(parse_env_file(example_path).keys())


def missing_keys(kv: dict[str, str], required: list[str]) -> list[str]:
    miss = []
    for k in required:
        if k not in kv or not str(kv.get(k) or "").strip():
            miss.append(k)
    return miss
