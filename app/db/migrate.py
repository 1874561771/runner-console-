"""RunnerConsole schema migration runner.

按版本号顺序执行 app/db/migrations/ 下的 V<NN>__<name>.sql，
并把已执行版本记录到 schema_migrations 表（幂等：已执行的版本跳过）。

独立运行（在项目根目录 D:\\RunnerConsole 下）：
    python -m app.db.migrate --config config.toml

依赖：pymysql、DBUtils、Python 3.11+（tomllib）。

注意：本模块尚未在真实 MySQL 8 上执行过——开发机无 MySQL 且 shell 通道
间歇断连无法验证。待 MySQL 8 就绪后执行上述命令验证：
建库字符集应为 utf8mb4（CREATE DATABASE runner_console CHARACTER SET utf8mb4;）。
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

from . import pool

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_MIG_NAME_RE = re.compile(r"^V(\d+)__(\w+)\.sql$")


def discover_migrations() -> list[tuple[int, str, Path]]:
    """扫描 migrations/ 目录，返回按版本号升序的 (version, name, path) 列表。"""
    found: list[tuple[int, str, Path]] = []
    for path in MIGRATIONS_DIR.glob("V*.sql"):
        m = _MIG_NAME_RE.match(path.name)
        if not m:
            raise ValueError(f"非法迁移文件名（应为 V<NN>__<name>.sql）: {path.name}")
        found.append((int(m.group(1)), m.group(2), path))
    versions = [v for v, _, _ in found]
    if len(versions) != len(set(versions)):
        raise ValueError(f"迁移版本号重复: {sorted(versions)}")
    return sorted(found, key=lambda item: item[0])


def split_statements(sql_text: str) -> list[str]:
    """按分号拆分语句，去掉注释与空白；本项目的迁移 SQL 不在字符串值内使用分号。"""
    statements: list[str] = []
    for chunk in sql_text.split(";"):
        # 去掉以 -- 开头的整行注释后仍剩实质内容才执行
        lines = [
            line for line in chunk.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        if lines:
            statements.append(chunk.strip())
    return statements


def run_migrations() -> list[int]:
    """执行所有未应用的迁移，返回本次应用的版本号列表。"""
    migrations = discover_migrations()
    applied: list[int] = []
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version     INT          NOT NULL,
                    applied_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
                    PRIMARY KEY (version)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
                """
            )
            cur.execute("SELECT version FROM schema_migrations")
            done = {int(row["version"]) for row in cur.fetchall()}

        for version, name, path in migrations:
            if version in done:
                continue
            sql_text = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                for stmt in split_statements(sql_text):
                    cur.execute(stmt)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
            conn.commit()  # 每个版本一个事务：失败则整版本回滚
            applied.append(version)
            print(f"applied V{version}__{name}")
    return applied


def load_database_dsn(config_path: Path) -> dict:
    """从 config.toml 的 [database] 段读取 DSN。"""
    with open(config_path, "rb") as fh:
        cfg = tomllib.load(fh)
    dsn = cfg.get("database")
    if not dsn:
        raise KeyError(f"config 缺少 [database] 段: {config_path}")
    required = ("host", "user", "password", "database")
    missing = [k for k in required if not dsn.get(k)]
    if missing:
        raise KeyError(f"[database] 缺少必填项: {', '.join(missing)}")
    return dsn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RunnerConsole schema migrations")
    parser.add_argument("--config", default="config.toml", help="配置文件路径（默认 config.toml）")
    args = parser.parse_args(argv)

    dsn = load_database_dsn(Path(args.config))
    pool.configure(dsn)  # DB 不可用会直接抛异常（无降级模式）
    applied = run_migrations()
    if not applied:
        print("schema already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
