from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from .. import clock
from ..db import current_user_id, get_db
from ..errors import Unprocessable
from ..services.quota import sender_quota
from .runs import parse_dt
from .util import ser

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(from_: str | None = Query(None, alias="from"), to: str | None = None, tz: str = "UTC"):
    try:
        zone = ZoneInfo(tz)
    except Exception as e:
        raise Unprocessable("Unknown time zone", code="invalid_tz") from e
    db = get_db()
    now = clock.now()
    dt_to = parse_dt(to) or now
    dt_from = parse_dt(from_) or (now - timedelta(days=30))
    runs = list(db.runs.find({"user_id": current_user_id(), "created_at": {"$gte": dt_from, "$lte": dt_to}}))
    run_ids = [r["_id"] for r in runs]
    counts = {"sent": 0, "failed": 0, "needs_review": 0, "no_contact": 0, "unknown": 0}
    for g in db.run_items.aggregate(
        [{"$match": {"run_id": {"$in": run_ids}}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    ):
        if g["_id"] in counts:
            counts[g["_id"]] = g["n"]
    per_day: dict[str, int] = {}
    for it in db.run_items.find(
        {"run_id": {"$in": run_ids}, "status": "sent", "sent_at": {"$ne": None}}, {"sent_at": 1}
    ):
        d = clock.as_utc(it["sent_at"]).astimezone(zone).strftime("%Y-%m-%d")
        per_day[d] = per_day.get(d, 0) + 1
    senders = []
    for s in db.senders.find({"user_id": current_user_id(), "deleted_at": None}).sort("created_at", 1):
        senders.append(
            {
                "id": str(s["_id"]),
                "provider": s["provider"],
                "address": s["address"],
                "status": s.get("status"),
                "quota": ser(sender_quota(s)),
            }
        )
    return {
        "from": dt_from.isoformat(),
        "to": dt_to.isoformat(),
        "kpis": {"runs": len(runs), **counts},
        "sent_per_day": [{"date": d, "sent": n} for d, n in sorted(per_day.items())],
        "senders": senders,
    }
