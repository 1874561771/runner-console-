"""GitLab Personal Access Token 登录（迁移自 webui/auth_gitlab.py）。

保留的关键行为：
* 公司 GitLab 在内网，请求用 ProxyHandler({}) 禁用系统 HTTP(S)_PROXY，
  避免代理吞请求导致登录超时；
* 证书为内网 CA 签发时可跳过 TLS 校验（原 --gitlab-insecure，
  本版改由 config.gitlab.gitlab_insecure / RC_GITLAB__GITLAB_INSECURE 控制）；
* 按 gitlab_id upsert 用户；同名旧 local 账号自动关联（保留其
  env/job 所有权与已绑口令）；
* admins 名单每次登录强制提权；admins 为空且库里无 admin 时首个
  登录者 bootstrap 为 admin。
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.auth import sessions
from app.auth.errors import AuthError
from app.auth.local import admin_names_from_config, resolve_role
from app.config import get_settings
from app.db.dao import users as users_dao

DEFAULT_TIMEOUT = 20


class GitLabAuthError(AuthError):
    pass


def _ssl_ctx(insecure: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _opener(insecure: bool) -> urllib.request.OpenerDirector:
    # 永不继承 HTTP(S)_PROXY：内网 GitLab 直达，走代理必然超时。
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=_ssl_ctx(insecure)),
    )


def _try_json(text: str) -> Any:
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return {"raw": text[:400]}


def _conn_hint(base_url: str, exc: Exception) -> str:
    reason = getattr(exc, "reason", exc)
    return (
        f"无法连接 GitLab（{base_url}）：{reason}。"
        "确认服务器能访问该地址；证书为内网 CA 时将 gitlab_insecure 置为 true；"
        "也可改用 auth_mode = \"local\" 不依赖 GitLab。"
    )


def gitlab_get(
    base_url: str,
    path: str,
    pat: str,
    *,
    insecure: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[int, Any]:
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(
        url,
        headers={
            "PRIVATE-TOKEN": pat,
            "User-Agent": "RunnerConsole/2.0",
        },
        method="GET",
    )
    try:
        with _opener(insecure).open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            code = resp.getcode()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, _try_json(body)
    except (urllib.error.URLError, OSError) as e:
        raise GitLabAuthError(_conn_hint(base_url, e), 502) from e
    return code, _try_json(body)


def verify_pat(
    base_url: str, pat: str, project: str | None, *, insecure: bool = False
) -> dict:
    """校验 PAT 有效性，并（可选）校验对 project 的读权限。返回用户信息。"""
    code, user = gitlab_get(base_url, "/api/v4/user", pat, insecure=insecure)
    if code in (401, 403):
        raise GitLabAuthError("GitLab token 无效或权限不足")
    if code != 200 or not isinstance(user, dict) or not user.get("id"):
        raise GitLabAuthError(f"GitLab 返回异常（HTTP {code}）", 502)
    if project:
        encoded = urllib.parse.quote(project, safe="")
        pcode, _ = gitlab_get(base_url, f"/api/v4/projects/{encoded}", pat, insecure=insecure)
        if pcode in (401, 403, 404):
            raise GitLabAuthError(f"该 token 无法访问项目 {project}")
        if pcode != 200:
            raise GitLabAuthError(f"校验项目权限失败（HTTP {pcode}）", 502)
    return {
        "gitlab_id": int(user["id"]),
        "username": str(user.get("username") or ""),
        "name": str(user.get("name") or user.get("username") or ""),
        "email": str(user.get("email") or ""),
    }


def login(pat: str) -> tuple[str, dict]:
    """PAT 登录：校验 → upsert → 提权 → 审计 → 签发会话。返回 (token, user)。"""
    if not (pat or "").strip():
        raise GitLabAuthError("缺少 GitLab token", 400)

    cfg = get_settings()
    base_url = cfg.gitlab.gitlab_url.rstrip("/")
    if not base_url:
        raise GitLabAuthError("未配置 gitlab_url（config [gitlab] 段）", 500)
    insecure = bool(cfg.gitlab.gitlab_insecure)
    project = str(cfg.gitlab.gitlab_project_id) if cfg.gitlab.gitlab_project_id else None

    info = verify_pat(base_url, pat.strip(), project, insecure=insecure)
    username = info["username"]
    if not username:
        raise GitLabAuthError("GitLab 用户缺少 username")

    admins = admin_names_from_config()
    existing = users_dao.get_by_gitlab_id(info["gitlab_id"])
    if not existing:
        # 同名 local 账号 → 关联而不是新建身份（保留 env/job 所有权）
        existing = users_dao.get_by_username(username)

    role = resolve_role(username, admins)
    if existing and role == "user":
        role = existing["role"]
    # admins 名单永远优先，且每次登录都执行提权（后加名单即生效）
    if username.lower() in admins:
        role = "admin"
        if existing and existing["role"] != "admin":
            users_dao.set_role(existing["id"], "admin")
    # admins 为空且库中零 admin：本次登录者 bootstrap 为 admin
    elif not admins and users_dao.count_admins() == 0:
        role = "admin"
        if existing and existing["role"] != "admin":
            users_dao.set_role(existing["id"], "admin")

    user = users_dao.upsert_user(
        gitlab_id=info["gitlab_id"],
        username=username,
        name=info["name"],
        email=info["email"],
        role=role,
        auth_source="gitlab",
    )
    if user["role"] != role:
        users_dao.set_role(user["id"], role)
        user = users_dao.get_by_id(user["id"]) or user
    users_dao.insert_audit(user["id"], "login", username)
    return sessions.issue_session(user["id"]), user
