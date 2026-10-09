from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "error"

    def __init__(
        self,
        detail: str,
        code: str | None = None,
        status_code: int | None = None,
        extra: dict[str, Any] | None = None,
    ):
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.extra = extra or {}


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ConfigLocked(Conflict):
    code = "config_locked"


class Unprocessable(AppError):
    status_code = 422
    code = "invalid"


class ConfigError(RuntimeError):
    """Fatal startup configuration problem."""
