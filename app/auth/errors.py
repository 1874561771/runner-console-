"""认证相关公共异常。"""

from __future__ import annotations


class AuthError(Exception):
    """认证失败。status 用于映射 HTTP 状态码（401 默认 / 400 参数错 / 502 上游错）。"""

    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status
