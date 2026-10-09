"""Classification unit for a `preparing` run (spec 9.3)."""

from __future__ import annotations

from datetime import timedelta

from .. import clock
from ..config import get_settings
from ..db import get_db
from ..llm.classify import MAX_LLM_ATTEMPTS, classify_batch
from ..services.prepare import apply_classification, rules_result

UNCLASSIFIED = {
    "classified": False,
    "email_norm": {"$ne": None},
    "status": {"$in": ["pending", "needs_review"]},
}


def _finish_if_done(run: dict) -> None:
    db = get_db()
    if db.run_items.count_documents({"run_id": run["_id"], **UNCLASSIFIED}) == 0:
        db.runs.update_one(
            {"_id": run["_id"], "status": "preparing"},
            {"$set": {"status": "ready", "updated_at": clock.now()}},
        )


def classify_unit(run: dict) -> None:
    db = get_db()
    s = get_settings()
    now = clock.now()
    if run.get("mode") == "rules":
        items = list(
            db.run_items.find({"run_id": run["_id"], **UNCLASSIFIED}).sort("row_index", 1).limit(200)
        )
        for it in items:
            apply_classification(run, it, rules_result(run, it))
        _finish_if_done(run)
        return

    nxt = clock.as_utc(run.get("next_llm_at"))
    if nxt is not None and nxt > now:
        return
    items = list(
        db.run_items.find({"run_id": run["_id"], **UNCLASSIFIED})
        .sort([("llm_attempts", 1), ("row_index", 1)])
        .limit(s.llm_batch_size)
    )
    if not items:
        _finish_if_done(run)
        return
    # items that exhausted their LLM attempts fall back to rules
    exhausted = [i for i in items if i.get("llm_attempts", 0) >= MAX_LLM_ATTEMPTS]
    for it in exhausted:
        apply_classification(run, it, rules_result(run, it, "llm_failed"))
    items = [i for i in items if i.get("llm_attempts", 0) < MAX_LLM_ATTEMPTS]
    if not items:
        return
    attempts = items[0].get("llm_attempts", 0)
    items = [i for i in items if i.get("llm_attempts", 0) == attempts]
    if attempts > 0:  # retry only the missing ones with a smaller batch
        items = items[: max(1, s.llm_batch_size >> attempts)]

    out = classify_batch(run, items)
    if out.status == "paused":
        db.runs.update_one(
            {"_id": run["_id"], "status": "preparing"},
            {
                "$set": {
                    "status": "paused_llm",
                    "pause_reason": "llm_exhausted",
                    "pause_detail": out.pause_detail,
                    "updated_at": clock.now(),
                }
            },
        )
        return
    gap = clock.now() + timedelta(seconds=s.llm_min_interval_s)
    db.runs.update_one({"_id": run["_id"]}, {"$set": {"next_llm_at": gap}})
    if out.status == "wait":
        return  # transient: retry next tick, key state untouched, items untouched
    for it in items:
        res = out.results.get(str(it["_id"]))
        if res is None:
            db.run_items.update_one({"_id": it["_id"]}, {"$inc": {"llm_attempts": 1}})
            continue
        apply_classification(run, it, {**res, "decided_by": "llm", "warnings": []}, key_id=out.key_id)
    _finish_if_done(run)
