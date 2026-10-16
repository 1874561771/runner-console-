"""本地账号登录：PBKDF2-SHA256 口令哈希/校验（迁移自 webui/auth.py local 分支）。

语义（2026-10-15 调整：取消匿名自注册，账号一律由管理员创建）：
* 用户名正则 ^[A-Za-z0-9._-]{2,40}$，口令最短 6 字符；
* 账号不存在 → 拒绝登录（联系管理员创建）；
* 唯一例外：admins 名单内的用户名首次登录自动建号（bootstrap 首个管理员）；
* 无口令账号（管理员重置过、或由管理员创建时未设口令）首次 local 登录时
  用本次输入的口令完成绑定；
* admins 名单中的用户每次登录都强制提权为 admin。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from app.auth import sessions
from app.auth.errors import AuthError
from app.config import get_settings
from app.db.dao import users as users_dao

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,40}$")
MIN_PASSWORD_LEN = 6
PBKDF2_ROUNDS = 120_000


def admin_names_from_config() -> set[str]:
    """config.auth.admins → 小写集合（等价原 --admins 解析）。"""
    return {a.strip().lower() for a in get_settings().auth.admins if a.strip()}


def resolve_role(username: str, admin_names: set[str]) -> str:
    """决定新账号的角色；已存在账号保持库中角色（见各 login 内逻辑）。"""
    if username.lower() in admin_names:
        return "admin"
    if not admin_names and users_dao.count_admins() == 0:
        return "admin"
    return "user"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """PBKDF2-HMAC-SHA256，12 万轮。返回 (hash_hex, salt_hex)。"""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS
    )
    return digest.hex(), salt


def verify_password(password: str, token_hash: str, salt: str) -> bool:
    try:
        calc, _ = hash_password(password, salt)
    except ValueError:  # salt 非 hex / 长度不对
        return False
    return hmac.compare_digest(calc, token_hash)


def login_local(username: str | None, password: str | None) -> tuple[str, dict]:
    """用户名 + 口令登录（首次使用自动注册）。返回 (明文 token, user dict)。"""
    username = (username or "").strip()
    password = (password or "").strip()
    if not USERNAME_RE.match(username):
        raise AuthError("用户名只能是字母/数字/. _ -，长度 2-40", 400)
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthError(f"访问口令至少 {MIN_PASSWORD_LEN} 个字符", 400)

    admin_names = admin_names_from_config()
    user = users_dao.get_by_username(username)

    if user is None:
        # 仅 admins 名单内的用户名可首次登录自举（建首个管理员）；其余一律拒绝
        if username.lower() not in admin_names:
            raise AuthError("账号不存在，请联系管理员创建", 401)
        h, salt = hash_password(password)
        user = users_dao.upsert_user(
            username=username,
            name=username,
            role="admin",
            token_hash=h,
            token_salt=salt,
            auth_source="local",
        )
        users_dao.insert_audit(user["id"], "register", username)
        return sessions.issue_session(user["id"]), user

    if not user.get("token_hash") or not user.get("token_salt"):
        # 无口令账号（管理员 clear_password 过，或 gitlab 模式创建）：
        # 用本次输入的口令完成绑定，不做校验（等价原 webui/auth.py L95-100）。
        h, salt = hash_password(password)
        users_dao.update_password(user["id"], h, salt)
        user = users_dao.get_by_id(user["id"]) or user
    elif not verify_password(password, user["token_hash"], user["token_salt"]):
        raise AuthError("用户名或访问口令不正确")

    # admins 名单每次登录都生效（后加的名字无需改库）
    if username.lower() in admin_names and user["role"] != "admin":
        users_dao.set_role(user["id"], "admin")
        user = users_dao.get_by_id(user["id"]) or user
    users_dao.insert_audit(user["id"], "login", username)
    return sessions.issue_session(user["id"]), user
