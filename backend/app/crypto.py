from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings
from .errors import ConfigError

_fernet: Fernet | None = None


def validate_secret_key(key: str | None = None) -> Fernet:
    key = key if key is not None else get_settings().secret_key
    if not key:
        raise ConfigError("SECRET_KEY is required. Generate one with scripts/gen-secret-key.sh")
    try:
        return Fernet(key.encode())
    except Exception as e:  # noqa: BLE001
        raise ConfigError(f"SECRET_KEY is not a valid Fernet key: {e}") from e


def _get() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = validate_secret_key()
    return _fernet


def reset() -> None:
    global _fernet
    _fernet = None


def encrypt(plain: str) -> str:
    return _get().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _get().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ConfigError("Cannot decrypt a stored secret: SECRET_KEY changed?") from e
