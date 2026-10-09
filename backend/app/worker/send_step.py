"""Send unit (spec 9.6)."""

from __future__ import annotations

import random
from datetime import timedelta
from pathlib import Path

from .. import clock
from ..config import get_settings
from ..db import get_db
from ..logging import get_logger
from ..providers.base import OutgoingEmail, SendResult
from ..providers.registry import get_provider
from ..services import locking
from ..services.quota import pick_sender

log = get_logger("worker.send")


def build_outgoing(
    run: dict, sender: dict, item: dict, to: str | None = None, subject_prefix: str = ""
) -> OutgoingEmail:
    cv = run["cv_file"]
    return OutgoingEmail(
        from_name=sender.get("display_name"),
        from_address=sender["address"],
        to=to or item["email_norm"],
        reply_to=run.get("reply_to") or None,
        subject=subject_prefix + item["subject"],
        body_text=item["body"],
        attachment_name=cv.get("original_name") or "cv.pdf",
        attachment_bytes=Path(cv["path"]).read_bytes(),
    )


def _pause_quota(run: dict, detail: dict) -> None:
    get_db().runs.update_one(
        {"_id": run["_id"], "status": "running"},
        {
            "$set": {
                "status": "paused_quota",
                "pause_reason": "no_sender",
                "pause_detail": detail,
                "updated_at": clock.now(),
            }
        },
    )


def _claim(run: dict):
    now = clock.now()
    q = {
        "run_id": run["_id"],
        "status": "pending",
        "classified": True,
        "$or": [{"next_attempt_at": None}, {"next_attempt_at": {"$lte": now}}],
    }
    if run.get("approval") == "manual":
        q["approved"] = True
    return get_db().run_items.find_one_and_update(
        q,
        {
            "$set": {
                "status": "sending",
                "lease_until": now + timedelta(seconds=get_settings().lease_s),
                "updated_at": now,
            }
        },
        sort=[("row_index", 1)],
        return_document=True,
    )


def send_unit(run: dict) -> str:
    """Run one send unit. Returns a short tag describing what happened (used by tests)."""
    db = get_db()
    sender, detail = pick_sender(run.get("sender_ids") or [])
    if sender is None:
        busy = db.run_items.count_documents({"run_id": run["_id"], "status": {"$in": ["pending", "sending"]}})
        if busy == 0:  # nothing left to send: finishing beats pausing (documented implementation note)
            db.runs.update_one(
                {"_id": run["_id"], "status": "running"},
                {"$set": {"status": "completed", "updated_at": clock.now()}},
            )
            return "completed"
        _pause_quota(run, detail)
        return "paused_quota"

    item = _claim(run)
    if item is None:
        busy = db.run_items.count_documents({"run_id": run["_id"], "status": {"$in": ["pending", "sending"]}})
        if busy == 0:
            db.runs.update_one(
                {"_id": run["_id"], "status": "running"},
                {"$set": {"status": "completed", "updated_at": clock.now()}},
            )
            return "completed"
        return "idle"

    # --- lock -------------------------------------------------------------
    contact_id = item.get("contact_id")
    locked = False
    if contact_id is not None and not item.get("override_duplicate"):
        ok, holder = locking.acquire(contact_id, item["_id"])
        if not ok:
            db.run_items.update_one(
                {"_id": item["_id"]},
                {
                    "$set": {
                        "status": "needs_review",
                        "lease_until": None,
                        "duplicate_of_item_id": holder,
                        "duplicate_reason": "already_sent",
                        "updated_at": clock.now(),
                    }
                },
            )
            return "needs_review"
        locked = True

    # --- send ---------------------------------------------------------------
    now = clock.now()
    log_id = db.send_log.insert_one(
        {"sender_id": sender["_id"], "item_id": item["_id"], "at": now}
    ).inserted_id
    db.runs.update_one({"_id": run["_id"], "first_send_at": None}, {"$set": {"first_send_at": now}})
    db.run_items.update_one(
        {"_id": item["_id"]},
        {
            "$set": {
                "sender_id": sender["_id"],
                "sender_address": sender["address"],
                "sender_provider": sender["provider"],
                "attempted_at": now,
            }
        },
    )
    try:
        email = build_outgoing(run, sender, item)
        result = get_provider(sender["provider"]).send(sender, email)
    except Exception as e:
        log.exception("provider raised", extra={"item_id": item["_id"], "run_id": run["_id"]})
        result = SendResult("unknown", f"unexpected error: {type(e).__name__}")
    return _handle_outcome(run, sender, item, result, log_id, locked)


def _handle_outcome(run: dict, sender: dict, item: dict, result: SendResult, log_id, locked: bool) -> str:
    db = get_db()
    s = get_settings()
    now = clock.now()
    contact_id = item.get("contact_id")
    attempt = {
        "at": now,
        "sender_id": sender["_id"],
        "outcome": result.outcome,
        "detail": (result.detail or "")[:500],
    }
    set_fields: dict = {"lease_until": None, "updated_at": now}
    run_inc: dict = {}
    run_set: dict = {}
    delay_after = False
    breaker_hit = False

    def release():
        if contact_id is not None and locked:
            locking.release(contact_id, item["_id"])

    if result.outcome == "sent":
        set_fields.update({"status": "sent", "sent_at": now, "message_id": result.message_id})
        if contact_id is not None:
            locking.set_sent_info(
                contact_id,
                {
                    "run_id": run["_id"],
                    "run_name": run.get("name"),
                    "sender_address": sender["address"],
                    "sent_at": now,
                    "subject": item.get("subject"),
                    "uncertain": False,
                },
            )
        run_set["consecutive_failures"] = 0
        delay_after = True
    elif result.outcome == "unknown":
        set_fields["status"] = "unknown"
        if contact_id is not None:
            locking.set_sent_info(
                contact_id,
                {
                    "run_id": run["_id"],
                    "run_name": run.get("name"),
                    "sender_address": sender["address"],
                    "sent_at": None,
                    "subject": item.get("subject"),
                    "uncertain": True,
                },
            )
        delay_after = True
    elif result.outcome == "transient":
        count = item.get("attempt_count", 0) + 1
        set_fields["attempt_count"] = count
        release()
        db.send_log.delete_one({"_id": log_id})
        delays = run.get("retry_delays_s") or s.retry_delays_s
        if count < run.get("max_retries", s.max_retries):
            idx = min(count - 1, len(delays) - 1)
            set_fields.update({"status": "pending", "next_attempt_at": now + timedelta(seconds=delays[idx])})
        else:
            set_fields["status"] = "failed"
            run_inc["consecutive_failures"] = 1
            delay_after = True
    elif result.outcome == "permanent":
        set_fields["status"] = "failed"
        release()
        db.send_log.delete_one({"_id": log_id})
        if not result.recipient_specific:
            run_inc["consecutive_failures"] = 1
        delay_after = True
    elif result.outcome == "auth":
        set_fields.update({"status": "pending"})
        release()
        db.send_log.delete_one({"_id": log_id})
        db.senders.update_one(
            {"_id": sender["_id"]},
            {"$set": {"status": "auth_failed", "last_error": (result.detail or "")[:500], "updated_at": now}},
        )
    elif result.outcome == "quota":
        set_fields.update({"status": "pending"})
        release()
        db.send_log.delete_one({"_id": log_id})
        wait = timedelta(seconds=result.retry_after_s) if result.retry_after_s else timedelta(hours=24)
        db.senders.update_one(
            {"_id": sender["_id"]},
            {
                "$set": {
                    "blocked_until": now + wait,
                    "last_error": (result.detail or "")[:500],
                    "updated_at": now,
                }
            },
        )

    db.run_items.update_one({"_id": item["_id"]}, {"$set": set_fields, "$push": {"attempts": attempt}})

    if delay_after and run.get("approval") != "manual":
        gap = random.uniform(
            run.get("delay_min_s", s.send_delay_min_s), run.get("delay_max_s", s.send_delay_max_s)
        )
        run_set["next_send_at"] = now + timedelta(seconds=gap)
    update: dict = {}
    if run_set:
        update["$set"] = run_set
    if run_inc:
        update["$inc"] = run_inc
    if update:
        db.runs.update_one({"_id": run["_id"]}, update)

    if run_inc:
        fresh = db.runs.find_one({"_id": run["_id"]})
        if fresh["consecutive_failures"] >= fresh.get("breaker_threshold", s.breaker_threshold):
            errs = []
            for it in (
                db.run_items.find({"run_id": run["_id"], "status": "failed"}).sort("updated_at", -1).limit(5)
            ):
                if it.get("attempts"):
                    errs.append(it["attempts"][-1].get("detail"))
            db.runs.update_one(
                {"_id": run["_id"], "status": "running"},
                {
                    "$set": {
                        "status": "paused_errors",
                        "pause_reason": "breaker",
                        "pause_detail": {"last_errors": errs},
                        "updated_at": clock.now(),
                    }
                },
            )
            breaker_hit = True
    return "breaker" if breaker_hit else result.outcome
