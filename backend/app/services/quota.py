"""Derived sender quota (spec 5.1). Never stored: always computed from send_log."""

from __future__ import annotations

from datetime import datetime, timedelta

from .. import clock
from ..db import get_db

WINDOW = timedelta(hours=24)


def _aware(dt: datetime | None) -> datetime | None:
    return clock.as_utc(dt)


def sender_quota(sender: dict, now: datetime | None = None) -> dict:
    now = now or clock.now()
    db = get_db()
    since = now - WINDOW
    ats = sorted(
        _aware(d["at"])
        for d in db.send_log.find({"sender_id": sender["_id"], "at": {"$gte": since}}, {"at": 1})
    )
    used = len(ats)
    cap = int(sender.get("daily_cap") or 0)
    blocked_until = _aware(sender.get("blocked_until"))
    blocked = blocked_until is not None and blocked_until > now
    cap_reached = used >= cap
    exhausted = cap_reached or blocked
    resets_at = None
    candidates = []
    if blocked:
        candidates.append(blocked_until)
    if cap_reached:
        idx = used - cap
        if 0 <= idx < len(ats):
            candidates.append(ats[idx] + WINDOW)
    if candidates:
        resets_at = max(candidates)
    status = sender.get("status", "active")
    if sender.get("deleted_at"):
        state = "deleted"
    elif status == "idle":
        state = "idle"
    elif status == "auth_failed":
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
        "resets_at": resets_at,
        "state": state,
    }


def sender_unavailable_reason(sender: dict, quota: dict | None = None) -> str | None:
    """Return None when the sender can send now, else idle|auth_failed|cap|blocked|deleted."""
    if sender.get("deleted_at"):
        return "deleted"
    st = sender.get("status")
    if st == "idle":
        return "idle"
    if st == "auth_failed":
        return "auth_failed"
    q = quota or sender_quota(sender)
    if q["blocked"]:
        return "blocked"
    if q["cap_reached"]:
        return "cap"
    return None


def pick_sender(sender_ids: list) -> tuple[dict | None, dict]:
    """Fill-first selection. Returns (sender or None, pause_detail-like summary)."""
    db = get_db()
    reasons = []
    earliest: datetime | None = None
    for sid in sender_ids:
        s = db.senders.find_one({"_id": sid})
        if s is None:
            reasons.append({"id": str(sid), "address": None, "reason": "deleted"})
            continue
        q = sender_quota(s)
        r = sender_unavailable_reason(s, q)
        if r is None:
            return s, {}
        reasons.append({"id": str(sid), "address": s.get("address"), "reason": r})
        if (
            r in ("cap", "blocked")
            and q["resets_at"] is not None
            and (earliest is None or q["resets_at"] < earliest)
        ):
            earliest = q["resets_at"]
    return None, {"earliest_reset_at": earliest, "senders": reasons}
