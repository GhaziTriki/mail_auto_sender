"""Crash recovery (spec 9.5 step 1): expired leases become `unknown`, never resent automatically."""

from __future__ import annotations

from .. import clock
from ..db import get_db
from ..logging import get_logger

log = get_logger("worker.recovery")


def recover_expired_leases() -> int:
    db = get_db()
    now = clock.now()
    n = 0
    for item in db.run_items.find({"status": "sending", "lease_until": {"$lt": now}}):
        res = db.run_items.update_one(
            {"_id": item["_id"], "status": "sending", "lease_until": {"$lt": now}},
            {
                "$set": {"status": "unknown", "lease_until": None, "updated_at": now},
                "$push": {
                    "attempts": {
                        "at": now,
                        "sender_id": item.get("sender_id"),
                        "outcome": "unknown",
                        "detail": "lease expired",
                    }
                },
            },
        )
        if res.modified_count:
            n += 1
            if item.get("contact_id") is not None:
                run = db.runs.find_one({"_id": item["run_id"]}) or {}
                db.contacts.update_one(
                    {"_id": item["contact_id"], "sent_item_id": item["_id"]},
                    {
                        "$set": {
                            "sent_info": {
                                "run_id": item["run_id"],
                                "run_name": run.get("name"),
                                "sender_address": item.get("sender_address"),
                                "sent_at": None,
                                "subject": item.get("subject"),
                                "uncertain": True,
                            }
                        }
                    },
                )
            log.warning(
                "lease expired; item marked unknown", extra={"item_id": item["_id"], "run_id": item["run_id"]}
            )
    return n
