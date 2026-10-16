"""API 请求/响应 Pydantic 模型。

与原 webui 的手工 JSON 解析不同，这里由 FastAPI 做校验：
字段缺失/类型不对自动返回 422。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LoginIn(BaseModel):
    """POST /api/login 请求体。

    * auth_mode = gitlab：只需 token（GitLab Personal Access Token）
    * auth_mode = local ：username + password（兼容把口令放在 token 字段）
    """

    username: str | None = None
    password: str | None = None
    token: str | None = None


class UserOut(BaseModel):
    """用户信息（不含 token_hash/token_salt 等敏感字段）。"""

    id: int
    gitlab_id: int | None = None
    username: str
    name: str | None = None
    email: str | None = None
    role: str
    created_at: datetime | None = None
    last_login: datetime | None = None
    auth_source: str | None = None


class MeOut(BaseModel):
    """GET /api/me 响应。"""

    user: UserOut
    auth_mode: str


# ---------------------------------------------------------------------
# T7 业务路由请求模型
# ---------------------------------------------------------------------

class RunIn(BaseModel):
    """POST /api/run 请求体。repeat=0 表示无限循环。"""

    env_id: str
    product: str = "firebox"
    source: str = "repo"            # repo | upload
    git_ref: str | None = None
    upload_id: str | None = None    # source=upload 时必填
    suite: str | None = None
    test: str | None = None
    headless: bool = False
    branch: str | None = None       # 固件 branch（runner --branch）
    build: str | None = None        # 固件 build（runner --build）
    repeat: int = 1
    pause_on_fail: bool = False


class EnvIn(BaseModel):
    """POST /api/envs 请求体。"""

    name: str
    content: str


class EnvPatchIn(BaseModel):
    """PATCH /api/envs/{id} 请求体；disabled 仅 admin 可改。"""

    name: str | None = None
    content: str | None = None
    disabled: bool | None = None


class EnvIdIn(BaseModel):
    """POST /api/lock/force-release 请求体。"""

    env_id: str


class GrantItem(BaseModel):
    """单条环境授权。level: viewer | operator。"""

    user_id: int
    level: str


class GrantsIn(BaseModel):
    """PUT /api/envs/{id}/grants 请求体：全量 grants 列表，或单条 user_id+level。"""

    grants: list[GrantItem] | None = None
    user_id: int | None = None
    level: str | None = None


class RoleIn(BaseModel):
    """PATCH /api/admin/users/{id}/role 请求体。"""

    role: str


class UserCreateIn(BaseModel):
    """POST /api/admin/users 请求体（管理员建号）。

    password 为空 → 服务端生成一次性随机口令并在响应中返回明文。
    """

    username: str
    password: str | None = None
    name: str | None = None
    role: str = "user"


class SettingsIn(BaseModel):
    """POST /api/admin/settings 请求体（0 = 不限制）。"""

    retain_count: int
    retain_days: int
