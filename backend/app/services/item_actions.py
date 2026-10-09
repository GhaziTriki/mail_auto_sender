"""Item actions (spec 9.8)."""

from __future__ import annotations

from .. import clock
from ..db import get_db
from ..errors import Conflict, NotFound, Unprocessable
from ..services import locking
from ..services.render import merged_warnings, render_item
from .run_control import reopen_if_completed

EDITABLE_STATUSES = ("pending", "needs_review", "failed")
VALID_ACTIONS = ("approve", "skip", "rerun", "resend", "mark_sent")


def _select(run: dict, item_ids, status_filter) -> list[dict]:
    db = get_db()
    q: dict = {"run_id": run["_id"]}
    if item_ids:
        from ..api.util import oid

        q["_id"] = {"$in": [oid(i) for i in item_ids]}
    elif status_filter:
        q["status"] = status_filter
    else:
        raise Unprocessable("Provide item_ids or status_filter", code="invalid")
    return list(db.run_items.find(q))


def bulk_action(run: dict, action: str, item_ids=None, status_filter=None) -> dict:
    if action not in VALID_ACTIONS:
        raise Unprocessable(f"Unknown action {action}", code="invalid_action")
    db = get_db()
    now = clock.now()
    items = _select(run, item_ids, status_filter)
    changed = 0
    created_pending = False
    for it in items:
        st = it["status"]
        if action == "approve":
            if run.get("approval") == "manual" and st == "pending":
                db.run_items.update_one(
                    {"_id": it["_id"], "status": "pending"}, {"$set": {"approved": True, "updated_at": now}}
                )
                changed += 1
                created_pending = True
        elif action == "skip":
            if st in ("pending", "failed"):
                new = "skipped_user"
            elif st == "needs_review":
                new = "skipped_duplicate"
            else:
                continue
            res = db.run_items.update_one(
                {"_id": it["_id"], "status": st}, {"$set": {"status": new, "updated_at": now}}
            )
            changed += res.modified_count
        elif action == "rerun":
            if st == "failed":
                res = db.run_items.update_one(
                    {"_id": it["_id"], "status": "failed"},
                    {
                        "$set": {
                            "status": "pending",
                            "attempt_count": 0,
                            "next_attempt_at": None,
                            "updated_at": now,
                            "approved": True
                            if run.get("approval") == "manual"
                            else it.get("approved", False),
                        }
                    },
                )
            elif st == "unknown":
                if it.get("contact_id") is not None:
                    locking.release(it["contact_id"], it["_id"])
                    get_db().contacts.update_one({"_id": it["contact_id"]}, {"$set": {"sent_info": None}})
                res = db.run_items.update_one(
                    {"_id": it["_id"], "status": "unknown"},
                    {
                        "$set": {
                            "status": "pending",
                            "attempt_count": 0,
                            "next_attempt_at": None,
                            "updated_at": now,
                            "approved": True
                            if run.get("approval") == "manual"
                            else it.get("approved", False),
                        }
                    },
                )
            else:
                continue
            if res.modified_count:
                changed += 1
                created_pending = True
        elif action == "resend":
            if st == "needs_review":
                res = db.run_items.update_one(
                    {"_id": it["_id"], "status": "needs_review"},
                    {
                        "$set": {
                            "status": "pending",
                            "override_duplicate": True,
                            "updated_at": now,
                            "approved": True
                            if run.get("approval") == "manual"
                            else it.get("approved", False),
                        }
                    },
                )
                if res.modified_count:
                    changed += 1
                    created_pending = True
        elif action == "mark_sent" and st == "unknown":
            res = db.run_items.update_one(
                {"_id": it["_id"], "status": "unknown"},
                {"$set": {"status": "sent", "sent_at": it.get("attempted_at") or now, "updated_at": now}},
            )
            if res.modified_count and it.get("contact_id") is not None:
                db.contacts.update_one(
                    {"_id": it["contact_id"]},
                    {
                        "$set": {
                            "sent_info": {
                                "run_id": run["_id"],
                                "run_name": run.get("name"),
                                "sender_address": it.get("sender_address"),
                                "sent_at": it.get("attempted_at") or now,
                                "subject": it.get("subject"),
                                "uncertain": False,
                            }
                        }
                    },
                )
            changed += res.modified_count
    if created_pending:
        reopen_if_completed(run["_id"])
    return {"action": action, "changed": changed, "selected": len(items)}


def get_item(item_id) -> dict:
    it = get_db().run_items.find_one({"_id": item_id})
    if not it:
        raise NotFound("Item not found")
    return it


def edit_item(item: dict, patch: dict) -> dict:
    db = get_db()
    if item["status"] not in EDITABLE_STATUSES:
        raise Conflict("This email can no longer be edited", code="not_editable")
    allowed = {"subject", "body", "greeting_text", "kind", "name", "company"}
    upd = {k: v for k, v in patch.items() if k in allowed}
    if not upd:
        raise Unprocessable("Nothing to change", code="invalid")
    if "kind" in upd and upd["kind"] not in ("human", "company"):
        raise Unprocessable("kind must be human or company", code="invalid")
    if "subject" in upd and ("\r" in upd["subject"] or "\n" in upd["subject"]):
        raise Unprocessable("Subject must be a single line", code="header_injection")
    run = db.runs.find_one({"_id": item["run_id"]})
    upd["edited"] = True
    class_changed = any(k in upd for k in ("kind", "name", "company"))
    if class_changed:
        upd["decided_by"] = "user"
        merged = {**item, **upd}
        if not any(k in patch for k in ("subject", "body", "greeting_text")):
            r = render_item(run, merged)
            upd.update(
                {
                    "greeting_text": r["greeting_text"],
                    "subject": r["subject"],
                    "body": r["body"],
                    "warnings": merged_warnings(merged, r["render_warnings"]),
                }
            )
    upd["updated_at"] = clock.now()
    db.run_items.update_one({"_id": item["_id"], "status": {"$in": list(EDITABLE_STATUSES)}}, {"$set": upd})
    return db.run_items.find_one({"_id": item["_id"]})
