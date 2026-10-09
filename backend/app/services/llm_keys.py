"""Gemini key pool state (spec 5.3, 8.6). Fill-first, lazy daily reset at midnight Pacific."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import clock
from ..db import get_db

PT = ZoneInfo("America/Los_Angeles")


def today_pt(now: datetime | None = None) -> str:
    return (now or clock.now()).astimezone(PT).strftime("%Y-%m-%d")


def next_midnight_pt(now: datetime | None = None) -> datetime:
    local = (now or clock.now()).astimezone(PT)
    nxt = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.astimezone(clock.UTC)


def refresh_day(key: dict) -> dict:
    """Lazily reset used_today when the Pacific day changed. Returns the fresh doc."""
    today = today_pt()
    if key.get("day_key") != today:
        get_db().llm_keys.update_one({"_id": key["_id"]}, {"$set": {"day_key": today, "used_today": 0}})
        key = {**key, "day_key": today, "used_today": 0}
    return key


def key_quota(key: dict) -> dict:
    key = refresh_day(key)
    now = clock.now()
    blocked_until = clock.as_utc(key.get("blocked_until"))
    blocked = blocked_until is not None and blocked_until > now
    cap = int(key.get("daily_cap") or 0)
    used = int(key.get("used_today") or 0)
    cap_reached = used >= cap
    exhausted = blocked or cap_reached
    st = key.get("status", "active")
    if key.get("deleted_at"):
        state = "deleted"
    elif st == "idle":
        state = "idle"
    elif st == "auth_failed":
        state = "auth_failed"
    elif exhausted:
        state = "exhausted"
    else:
        state = "active"
    return {
        "used": used,
        "cap": cap,
        "exhausted": exhausted,
        "cap_reached": cap_reached,
        "blocked": blocked,
        "resets_at": next_midnight_pt(),
        "state": state,
    }


def unavailable_reason(key: dict) -> str | None:
    if key.get("deleted_at"):
        return "deleted"
    if key.get("status") == "idle":
        return "idle"
    if key.get("status") == "auth_failed":
        return "auth_failed"
    q = key_quota(key)
    if q["blocked"]:
        return "blocked"
    if q["cap_reached"]:
        return "cap"
    return None


def pick_key(key_ids: list, skip: set | None = None) -> tuple[dict | None, dict]:
    db = get_db()
    reasons = []
    skip = skip or set()
    for kid in key_ids:
        k = db.llm_keys.find_one({"_id": kid})
        if k is None:
            reasons.append({"id": str(kid), "reason": "deleted"})
            continue
        if kid in skip:
            reasons.append({"id": str(kid), "reason": "failed_this_tick"})
            continue
        r = unavailable_reason(k)
        if r is None:
            return refresh_day(k), {}
        reasons.append({"id": str(kid), "reason": r})
    return None, {"earliest_reset_at": next_midnight_pt(), "keys": reasons}


def record_request(key_id) -> None:
    """Every request attempt that reached Google increments used_today."""
    get_db().llm_keys.update_one({"_id": key_id}, {"$inc": {"used_today": 1}})


def mark_quota(key_id, detail: str) -> None:
    get_db().llm_keys.update_one(
        {"_id": key_id},
        {
            "$set": {
                "blocked_until": next_midnight_pt(),
                "last_error": detail[:300],
                "updated_at": clock.now(),
            }
        },
    )


def mark_auth_failed(key_id, detail: str) -> None:
    get_db().llm_keys.update_one(
        {"_id": key_id},
        {"$set": {"status": "auth_failed", "last_error": detail[:300], "updated_at": clock.now()}},
    )
