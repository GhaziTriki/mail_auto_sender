from __future__ import annotations

from datetime import UTC, datetime, timedelta

_frozen: datetime | None = None


def now() -> datetime:
    return _frozen if _frozen is not None else datetime.now(UTC)


def freeze(at: datetime | None = None) -> datetime:
    """Tests only: freeze the clock."""
    global _frozen
    _frozen = at or datetime.now(UTC)
    return _frozen


def advance(**kwargs) -> datetime:
    global _frozen
    if _frozen is None:
        _frozen = datetime.now(UTC)
    _frozen = _frozen + timedelta(**kwargs)
    return _frozen


def unfreeze() -> None:
    global _frozen
    _frozen = None


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
