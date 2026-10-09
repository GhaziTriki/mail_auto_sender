from __future__ import annotations

from ..config import get_settings
from ..errors import Unprocessable
from .base import Provider

_overrides: dict[str, Provider] = {}


def set_override(name: str, provider: Provider | None) -> None:
    """Tests only: install a fake provider."""
    if provider is None:
        _overrides.pop(name, None)
    else:
        _overrides[name] = provider


def get_provider(name: str) -> Provider:
    if name in _overrides:
        return _overrides[name]
    if name == "gmail":
        from .gmail import GmailProvider
        return GmailProvider()
    if name == "outlook":
        if not get_settings().outlook_enabled:
            raise Unprocessable("Outlook is not activated. See docs/providers/outlook.md", code="outlook_disabled")
        from .outlook import OutlookProvider
        return OutlookProvider()
    raise Unprocessable(f"Unknown provider {name}", code="unknown_provider")


def list_providers() -> list[dict]:
    s = get_settings()
    return [
        {"name": "gmail", "enabled": True, "setup_doc": "/docs-static/providers/gmail.md"},
        {"name": "outlook", "enabled": s.outlook_enabled, "setup_doc": "/docs-static/providers/outlook.md"},
    ]
