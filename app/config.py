"""RunnerConsole 配置加载。

读取顺序（后者覆盖前者）：
1. 内置默认值（下方 *Config 类字段默认值）
2. config.toml（路径：RC_CONFIG 环境变量 > 项目根 config.toml）
3. 环境变量覆盖：前缀 RC_，段名与字段名用双下划线分隔，例如
   RC_SERVER__PORT=9000
   RC_DATABASE__PASSWORD=secret
   RC_AUTH__ADMINS='["alice","bob"]'      （列表用 JSON）
   RC_GITLAB__GITLAB_INSECURE=true

pydantic v2 BaseModel 做字段校验；tomllib 为 Python 3.11+ 标准库。
"""

from __future__ import annotations

import json
import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("runnerconsole.config")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"

ENV_PREFIX = "RC_"
ENV_SEP = "__"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class DatabaseConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "runner"
    password: str = ""
    database: str = "runner_console"
    charset: str = "utf8mb4"


class PathsConfig(BaseModel):
    # 测试框架工作目录（被测代码 / runner 所在仓库）
    workdir: str = "."
    # 测试产物根目录（其下按 run_id 分目录）
    artifacts_root: str = "./artifacts"
    # 单环境控制台数据目录
    console_dir: str = "./data/console"
    # 循环任务控制台日志目录
    consoles_dir: str = "./data/consoles"


class AuthConfig(BaseModel):
    # gitlab | local
    auth_mode: str = "gitlab"
    # 管理员用户名列表（登录时自动提权为 role='admin'）
    admins: list[str] = Field(default_factory=list)
    # 会话有效期（天）；Cookie max_age 同步使用
    session_ttl_days: int = 7


class GitlabConfig(BaseModel):
    # GitLab 实例地址，如 https://gitlab.example.com
    gitlab_url: str = ""
    # 校验用户归属/拉取信息的 GitLab 项目 ID（数字或路径）
    gitlab_project_id: int | None = None
    # 内网 CA 自签证书时跳过 TLS 校验（等价原 --gitlab-insecure）
    gitlab_insecure: bool = False


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    gitlab: GitlabConfig = Field(default_factory=GitlabConfig)

    def dsn(self) -> dict[str, Any]:
        """供 app.db.pool.configure() 消费的连接参数。"""
        db = self.database
        return {
            "host": db.host,
            "port": db.port,
            "user": db.user,
            "password": db.password,
            "database": db.database,
            "charset": db.charset,
        }


def _coerce_value(raw: str, default: Any) -> Any:
    """按默认值的类型把环境变量字符串转成对应类型。"""
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int) and not isinstance(default, bool):
        return int(raw)
    if isinstance(default, list):
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError(f"环境变量列表值必须是 JSON 数组，收到: {raw[:100]}")
        return parsed
    return raw


def _apply_env_overrides(settings: AppConfig) -> AppConfig:
    """RC_<段>__<字段> 环境变量覆盖（仅作用于已知字段，未知项忽略并告警）。"""
    for env_name, raw in os.environ.items():
        if not env_name.startswith(ENV_PREFIX):
            continue
        rest = env_name[len(ENV_PREFIX):]
        if not rest:
            continue
        if ENV_SEP in rest:
            section, field = rest.split(ENV_SEP, 1)
            section, field = section.lower(), field.lower()
            sub = getattr(settings, section, None)
            if not isinstance(sub, BaseModel) or field not in sub.model_fields:
                logger.warning("忽略未知配置项环境变量: %s", env_name)
                continue
            try:
                setattr(sub, field, _coerce_value(raw, getattr(sub, field)))
            except (ValueError, TypeError) as e:
                raise ValueError(f"环境变量 {env_name} 取值非法: {e}") from e
        else:
            field = rest.lower()
            if field not in settings.model_fields:
                logger.warning("忽略未知配置项环境变量: %s", env_name)
                continue
            try:
                setattr(settings, field, _coerce_value(raw, getattr(settings, field)))
            except (ValueError, TypeError) as e:
                raise ValueError(f"环境变量 {env_name} 取值非法: {e}") from e
    return settings


def load_config(path: str | Path | None = None) -> AppConfig:
    """加载配置：toml 为基底，RC_ 环境变量覆盖。文件缺失直接抛异常。"""
    cfg_path = Path(path or os.environ.get("RC_CONFIG") or DEFAULT_CONFIG_PATH)
    if not cfg_path.is_file():
        raise FileNotFoundError(
            f"配置文件不存在: {cfg_path}（请复制 config.example.toml 为 config.toml 后修改）"
        )
    with open(cfg_path, "rb") as f:
        data = tomllib.load(f)
    known = set(AppConfig.model_fields)
    unknown = set(data) - known
    if unknown:
        logger.warning("config.toml 中存在未知段（忽略）: %s", ", ".join(sorted(unknown)))
    settings = AppConfig(**{k: v for k, v in data.items() if k in known})
    settings = _apply_env_overrides(settings)
    if settings.auth.auth_mode not in ("gitlab", "local"):
        raise ValueError(f"auth_mode 只能是 gitlab 或 local，收到: {settings.auth.auth_mode}")
    if settings.auth.session_ttl_days < 1:
        raise ValueError("session_ttl_days 必须 >= 1")
    return settings


_settings: AppConfig | None = None


def get_settings(path: str | Path | None = None) -> AppConfig:
    """进程级单例；首次调用时加载，之后返回缓存。"""
    global _settings
    if _settings is None:
        _settings = load_config(path)
    return _settings


def reset_settings() -> None:
    """清空单例缓存（测试/重载配置用）。"""
    global _settings
    _settings = None
