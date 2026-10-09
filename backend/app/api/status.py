"""System status in one call: API, database, worker heartbeat and the queue. Feeds the Status page."""

from __future__ import annotations

import platform
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import clock
from ..config import get_settings
from ..db import current_user_id, get_db
from ..providers.registry import list_providers
from ..services.quota import sender_quota
from ..worker import heartbeat

router = APIRouter(prefix="/api", tags=["meta"])

RUN_STATUSES = (
    "draft",
    "preparing",
    "ready",
    "running",
    "paused_user",
    "paused_quota",
    "paused_llm",
    "paused_errors",
    "completed",
)
ITEM_STATUSES = ("pending", "sending", "failed", "needs_review", "unknown")
# A tick can take a few seconds (one provider call); beyond three ticks of silence the worker is stale.
STALE_GRACE_S = 5

_STARTED_AT = datetime.now(UTC)
_STARTED_MONO = time.monotonic()


def _version() -> str:
    try:
        return version("applymail")
    except PackageNotFoundError:
        return "unknown"


def _api() -> dict:
    return {
        "version": _version(),
        "python": platform.python_version(),
        "started_at": _STARTED_AT.isoformat(),
        "uptime_s": int(time.monotonic() - _STARTED_MONO),
    }


def _database() -> dict:
    t0 = time.perf_counter()
    db = get_db()
    db.command("ping")
    return {
        "ok": True,
        "name": db.name,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        "error": None,
    }


def _worker_unknown(state: str) -> dict:
    return {
        "ok": False,
        "state": state,
        "last_tick_at": None,
        "age_s": None,
        "started_at": None,
        "tick_s": get_settings().worker_tick_s,
        "host": None,
        "last_error": None,
    }


def _worker(now: datetime) -> dict:
    doc = heartbeat.read()
    if not doc:
        return _worker_unknown("never")
    last = clock.as_utc(doc.get("last_tick_at"))
    started = clock.as_utc(doc.get("started_at"))
    age = max(0, int((now - last).total_seconds())) if last else None
    tick_s = int(doc.get("tick_s") or get_settings().worker_tick_s)
    alive = age is not None and age <= 3 * tick_s + STALE_GRACE_S
    return {
        "ok": alive,
        "state": "alive" if alive else "stale",
        "last_tick_at": last.isoformat() if last else None,
        "age_s": age,
        "started_at": started.isoformat() if started else None,
        "tick_s": tick_s,
        "host": doc.get("host"),
        "last_error": doc.get("last_error"),
    }


def _queue() -> dict:
    db = get_db()
    uid = current_user_id()
    by_status = dict.fromkeys(RUN_STATUSES, 0)
    for g in db.runs.aggregate(
        [{"$match": {"user_id": uid}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    ):
        if g["_id"] in by_status:
            by_status[g["_id"]] = g["n"]
    items = dict.fromkeys(ITEM_STATUSES, 0)
    for g in db.run_items.aggregate(
        [
            {"$match": {"status": {"$in": list(ITEM_STATUSES)}}},
            {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        ]
    ):
        items[g["_id"]] = g["n"]
    senders = {"total": 0, "available": 0, "exhausted": 0, "idle": 0, "auth_failed": 0}
    for s in db.senders.find({"user_id": uid, "deleted_at": None}):
        senders["total"] += 1
        state = sender_quota(s)["state"]
        key = "available" if state == "active" else state
        if key in senders:
            senders[key] += 1
    active = by_status["preparing"] + by_status["running"]
    return {"runs": {"by_status": by_status, "active": active}, "items": items, "senders": senders}


@router.get("/status")
def status():
    """Overall status is `ok`, `degraded` (worker silent or its last tick failed) or `error` (database down, 503)."""
    s = get_settings()
    now = clock.now()
    body: dict = {
        "status": "ok",
        "checked_at": now.isoformat(),
        "api": _api(),
        "providers": {p["name"]: p["enabled"] for p in list_providers()},
        "llm": {"model": s.gemini_model, "fake": s.llm_fake},
    }
    try:
        body["database"] = _database()
    except Exception as e:
        body["database"] = {"ok": False, "name": None, "latency_ms": None, "error": type(e).__name__}
        body["worker"] = _worker_unknown("unknown")
        body["status"] = "error"
        return JSONResponse(body, status_code=503)
    body["worker"] = _worker(now)
    body.update(_queue())
    if not body["worker"]["ok"] or body["worker"]["last_error"]:
        body["status"] = "degraded"
    return body
