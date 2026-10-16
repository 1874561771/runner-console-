"""settings 表的数据访问层（DAO）。

* 只依赖 app.db.pool，不 import 任何 api / core 模块（避免循环依赖）。
* schema：settings(setting_key VARCHAR(64) PK, setting_value TEXT)，
  预置 retain_count=50 / retain_days=30（V1 迁移 INSERT）。
* 值统一以字符串落库，读出时按用途解析（解析失败回退默认值）。
"""

from __future__ import annotations

from app.db import pool

_DEFAULT_RETAIN_COUNT = 50
_DEFAULT_RETAIN_DAYS = 30


def get_value(key: str, default: str | None = None) -> str | None:
    row = pool.query_one(
        "SELECT setting_value FROM settings WHERE setting_key = %s", (key,)
    )
    return row["setting_value"] if row else default


def set_value(key: str, value: str) -> None:
    """upsert 单个设置项（ON DUPLICATE KEY UPDATE）。"""
    pool.execute(
        "INSERT INTO settings (setting_key, setting_value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)",
        (key, str(value)),
    )


def _to_int(raw: str | None, default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def get_retention() -> dict:
    """读保留策略：{retain_count: int, retain_days: int}。

    0 表示该维度不限制；缺行/非法值回退内置默认（与 V1 预置一致）。
    """
    rows = pool.query(
        "SELECT setting_key, setting_value FROM settings "
        "WHERE setting_key IN ('retain_count', 'retain_days')"
    )
    values = {r["setting_key"]: r["setting_value"] for r in rows}
    return {
        "retain_count": max(
            0, _to_int(values.get("retain_count"), _DEFAULT_RETAIN_COUNT)
        ),
        "retain_days": max(
            0, _to_int(values.get("retain_days"), _DEFAULT_RETAIN_DAYS)
        ),
    }


def save_retention(retain_count: int, retain_days: int) -> None:
    """保存保留策略（调用方负责先做数值校验）。"""
    set_value("retain_count", int(retain_count))
    set_value("retain_days", int(retain_days))
