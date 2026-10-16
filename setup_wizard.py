# -*- coding: utf-8 -*-
"""RunnerConsole 一键部署向导（新机器初始化）。

交互式完成：
1. 检查 MySQL 连接（需要 root 密码；MySQL 服务本身请先安装好，
   脚本不负责安装 MySQL Server——见 DEPLOY.md §1）
2. 建库 runner_console（utf8mb4）、建用户 runner、授权（均已存在则跳过）
3. 生成 config.toml（已存在则跳过向导，保留现有配置）
4. 运行 schema 迁移（幂等）

用法：在项目根目录执行  .venv/Scripts/python setup_wizard.py
或由 install.bat 自动调用。
"""
from __future__ import annotations

import secrets
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.toml"

DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_NAME = "runner_console"
DB_USER = "runner"


def ask(prompt: str, default: str = "") -> str:
    suffix = f"（回车 = {default}）" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def ask_password(prompt: str) -> str:
    import getpass

    while True:
        pw = getpass.getpass(f"{prompt}: ")
        if pw:
            return pw
        print("  不能为空，请重新输入。")


def connect_root() -> "object":
    import pymysql

    root_pw = ask_password("请输入 MySQL root 密码")
    try:
        return pymysql.connect(
            host=DB_HOST, port=DB_PORT, user="root", password=root_pw,
            charset="utf8mb4", autocommit=True,
        )
    except pymysql.err.OperationalError as exc:
        print(f"  连接失败：{exc}")
        print("  请确认：1) MySQL 服务已启动；2) root 密码正确。")
        print("  MySQL 尚未安装时，参考 DEPLOY.md §1（官网 MSI 或 winget install Oracle.MySQL）。")
        sys.exit(1)


def provision_db(conn) -> str:
    """建库 / 建用户 / 授权；返回 runner 用户密码。"""
    from pymysql.err import ProgrammingError

    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS {DB_NAME} "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        print(f"√ 数据库 {DB_NAME} 就绪")

    runner_pw = ask(
        f"设置数据库用户 {DB_USER} 的密码（回车 = 自动生成强密码）",
        secrets.token_urlsafe(12),
    )
    with conn.cursor() as cur:
        try:
            cur.execute(
                f"CREATE USER IF NOT EXISTS '{DB_USER}'@'localhost' IDENTIFIED BY %s",
                (runner_pw,),
            )
            print(f"√ 用户 {DB_USER}@localhost 已创建")
        except ProgrammingError:
            # 用户已存在：改密码到本次输入值，保证 config.toml 可用
            cur.execute(
                f"ALTER USER '{DB_USER}'@'localhost' IDENTIFIED BY %s",
                (runner_pw,),
            )
            print(f"√ 用户 {DB_USER}@localhost 已存在，密码已更新为本次输入值")
        cur.execute(
            f"GRANT ALL PRIVILEGES ON {DB_NAME}.* TO '{DB_USER}'@'localhost'"
        )
        cur.execute("FLUSH PRIVILEGES")
        print("√ 授权完成")
    return runner_pw


def write_config(runner_pw: str) -> None:
    workdir = ask("runner 仓库路径（runner.py 所在目录）", "D:/UIAutomation")
    admins = ask("管理员用户名（逗号分隔，首次登录即建号提权）", "yjwu")
    admin_list = ", ".join(f'"{a.strip()}"' for a in admins.split(",") if a.strip())

    config = f'''# RunnerConsole 配置（由 setup_wizard.py 生成；含密码，勿提交仓库）

[server]
# 0.0.0.0 = 局域网内其它电脑可访问（办公室访问实验室机器就靠它）
host = "0.0.0.0"
port = 8765

[database]
host = "{DB_HOST}"
port = {DB_PORT}
user = "{DB_USER}"
password = "{runner_pw}"
database = "{DB_NAME}"
charset = "utf8mb4"

[paths]
workdir = "{workdir}"
artifacts_root = "{workdir}/artifacts"
console_dir = "{(PROJECT_ROOT / "data" / "console").as_posix()}"
consoles_dir = "{(PROJECT_ROOT / "data" / "consoles").as_posix()}"

[auth]
auth_mode = "local"
admins = [{admin_list}]
session_ttl_days = 7

[gitlab]
gitlab_url = ""
gitlab_project_id = 0
gitlab_insecure = false
'''
    CONFIG_PATH.write_text(config, encoding="utf-8")
    print(f"√ 配置已写入 {CONFIG_PATH}")


def run_migrate() -> None:
    print("√ 执行数据库迁移（幂等）…")
    import subprocess

    py = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    exe = str(py if py.is_file() else sys.executable)
    r = subprocess.run(
        [exe, "-m", "app.db.migrate", "--config", "config.toml"],
        cwd=str(PROJECT_ROOT),
    )
    if r.returncode != 0:
        print("× 迁移失败，请把上方报错发出来。")
        sys.exit(1)
    print("√ 数据库表结构就绪")


def main() -> int:
    print("=" * 56)
    print("RunnerConsole 部署向导")
    print("=" * 56)
    if sys.version_info < (3, 11):
        print("× 需要 Python 3.11+（tomllib）。当前：", sys.version)
        return 1

    conn = connect_root()
    runner_pw = provision_db(conn)
    conn.close()

    if CONFIG_PATH.exists():
        print(f"√ {CONFIG_PATH.name} 已存在，保留现有配置（如需重写请先删除它）")
        with open(CONFIG_PATH, "rb") as fh:
            db = tomllib.load(fh).get("database", {})
        if db.get("password") != runner_pw:
            print("  注意：向导里输入的 runner 密码与 config.toml 中不一致，")
            print("  以 config.toml 为准；若想改用新密码请重跑向导并先删除 config.toml。")
    else:
        write_config(runner_pw)

    run_migrate()
    print()
    print("部署完成！启动服务：")
    print(f'  "{py}" -m uvicorn app.main:app --host 0.0.0.0 --port 8765')
    print("或直接双击 install.bat 选启动；浏览器访问 http://<本机IP>:8765/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
