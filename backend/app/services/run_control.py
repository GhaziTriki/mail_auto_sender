"""Run lifecycle control (spec 6, 9.1, 9.4, 9.7, 11)."""
from __future__ import annotations

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from .. import clock
from ..config import get_settings
from ..db import current_user_id, get_db
from ..errors import ConfigLocked, Conflict, NotFound, Unprocessable
from ..services import importer
from ..services.greeting import DEFAULT_GREETING
from ..services.llm_keys import pick_key
from ..services.prepare import prepare_run, rerender_run
from ..services.quota import pick_sender
from ..services.render import ensure_valid_template

PAUSED = ("paused_user", "paused_quota", "paused_llm", "paused_errors")
DEFAULT_TEMPLATE = {
    "subject": "Internship application",
    "body": "{{greeting}}\n\nI am writing to apply for an internship at {{company}}. Please find my CV attached.\n\n"
            "Thank you for your time.\n\nBest regards",
}
LOCKED_FIELDS = {"filters", "recipient", "template", "greeting", "rules", "mode"}


def get_run(run_id) -> dict:
    run = get_db().runs.find_one({"_id": run_id, "user_id": current_user_id()})
    if not run:
        raise NotFound("Run not found")
    return run


def create_run(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise Unprocessable("Name is required", code="invalid_name")
    s = get_settings()
    now = clock.now()
    doc = {
        "user_id": current_user_id(), "name": name, "name_lower": name.lower(), "status": "draft",
        "pause_reason": None, "pause_detail": None, "created_at": now, "updated_at": now, "started_at": None,
        "first_send_at": None, "source_file": None, "columns": [], "row_count": 0, "cv_file": None, "filters": [],
        "recipient": {"email_column": None, "human_name_columns": [], "company_name_columns": []},
        "mode": "rules", "rules": {"kind": "human_if_available"}, "greeting": dict(DEFAULT_GREETING),
        "template": dict(DEFAULT_TEMPLATE), "reply_to": None, "approval": "manual", "sender_ids": [],
        "senders_snapshot": [], "llm_key_ids": [], "delay_min_s": s.send_delay_min_s, "delay_max_s": s.send_delay_max_s,
        "max_retries": s.max_retries, "retry_delays_s": list(s.retry_delays_s), "breaker_threshold": s.breaker_threshold,
        "consecutive_failures": 0, "next_send_at": None, "next_llm_at": None, "tz_hint": None,
    }
    try:
        rid = get_db().runs.insert_one(doc).inserted_id
    except DuplicateKeyError as e:
        raise Conflict("A run with this name already exists", code="name_taken") from e
    return get_db().runs.find_one({"_id": rid})


def _oids(values) -> list:
    out = []
    for v in values or []:
        try:
            out.append(v if isinstance(v, ObjectId) else ObjectId(v))
        except Exception as e:
            raise Unprocessable("Invalid id in list", code="invalid_id") from e
    return out


def patch_run(run: dict, patch: dict) -> dict:
    db = get_db()
    patch = {k: v for k, v in patch.items() if v is not None or k in ("reply_to", "tz_hint")}
    status = run["status"]
    locked = run.get("first_send_at") is not None
    upd: dict = {}
    needs_rerender = False

    touched_locked = LOCKED_FIELDS & set(patch)
    # the only allowed locked-field change is the llm->rules switch handled below
    if locked and touched_locked and not (touched_locked <= {"mode", "rules"} and status == "paused_llm"):
        raise ConfigLocked("Configuration is locked after the first email was sent")

    if "name" in patch:
        name = patch["name"].strip()
        if not name:
            raise Unprocessable("Name is required", code="invalid_name")
        upd["name"], upd["name_lower"] = name, name.lower()

    for f in ("filters", "recipient", "rules"):
        if f in patch:
            if status != "draft":
                raise Conflict("Unprepare the run before changing this setting", code="not_draft")
            upd[f] = patch[f]
    if "recipient" in patch:
        rec = patch["recipient"]
        cols = set(run.get("columns") or [])
        for c in [rec.get("email_column"), *(rec.get("human_name_columns") or []), *(rec.get("company_name_columns") or [])]:
            if c and cols and c not in cols:
                raise Unprocessable(f"Unknown column: {c}", code="unknown_column")
        upd["recipient"] = {"email_column": rec.get("email_column"),
                            "human_name_columns": list(rec.get("human_name_columns") or []),
                            "company_name_columns": list(rec.get("company_name_columns") or [])}
    if "filters" in patch:
        cols = set(run.get("columns") or [])
        for f in patch["filters"]:
            if f.get("column") not in cols:
                raise Unprocessable(f"Unknown filter column: {f.get('column')}", code="unknown_column")
        upd["filters"] = [{"column": f["column"], "values": list(f.get("values") or [])} for f in patch["filters"]]

    if "mode" in patch:
        mode = patch["mode"]
        if mode not in ("llm", "rules"):
            raise Unprocessable("mode must be llm or rules", code="invalid_mode")
        if status == "draft":
            upd["mode"] = mode
        elif status == "paused_llm" and run["mode"] == "llm" and mode == "rules":
            upd["mode"] = "rules"
        elif mode != run["mode"]:
            raise Conflict("The mode can only be switched from llm to rules while paused_llm", code="mode_locked")

    if "greeting" in patch:
        upd["greeting"] = {**DEFAULT_GREETING, **run.get("greeting", {}), **patch["greeting"]}
        needs_rerender = True
    if "template" in patch:
        tpl = {"subject": patch["template"].get("subject", ""), "body": patch["template"].get("body", "")}
        if status != "draft" or run.get("columns"):
            ensure_valid_template(tpl, run.get("columns") or [])
        upd["template"] = tpl
        needs_rerender = True
    if "reply_to" in patch:
        rt = (patch["reply_to"] or "").strip() or None
        if rt and ("\r" in rt or "\n" in rt or "@" not in rt):
            raise Unprocessable("Invalid reply-to address", code="invalid_reply_to")
        upd["reply_to"] = rt
    if "tz_hint" in patch:
        upd["tz_hint"] = patch["tz_hint"]
    if "approval" in patch:
        if patch["approval"] not in ("manual", "auto"):
            raise Unprocessable("approval must be manual or auto", code="invalid_approval")
        upd["approval"] = patch["approval"]
    if "sender_ids" in patch:
        ids = _oids(patch["sender_ids"])
        snap = []
        for sid in ids:
            snd = db.senders.find_one({"_id": sid, "user_id": current_user_id(), "deleted_at": None})
            if not snd:
                raise Unprocessable("Unknown sender", code="unknown_sender")
            snap.append({"id": str(sid), "provider": snd["provider"], "address": snd["address"]})
        upd["sender_ids"], upd["senders_snapshot"] = ids, snap
    if "llm_key_ids" in patch:
        upd["llm_key_ids"] = _oids(patch["llm_key_ids"])
    for f in ("delay_min_s", "delay_max_s", "max_retries", "breaker_threshold"):
        if f in patch:
            if not isinstance(patch[f], int) or patch[f] < 0:
                raise Unprocessable(f"{f} must be a non-negative integer", code="invalid_value")
            upd[f] = patch[f]
    mn, mx = upd.get("delay_min_s", run["delay_min_s"]), upd.get("delay_max_s", run["delay_max_s"])
    if mn > mx:
        raise Unprocessable("delay_min_s must be <= delay_max_s", code="invalid_value")

    if upd:
        upd["updated_at"] = clock.now()
        try:
            db.runs.update_one({"_id": run["_id"]}, {"$set": upd})
        except DuplicateKeyError as e:
            raise Conflict("A run with this name already exists", code="name_taken") from e
    if needs_rerender and status != "draft":
        rerender_run(run["_id"])
    # leaving paused_llm after switching to rules happens through resume
    return db.runs.find_one({"_id": run["_id"]})


def prepare(run: dict) -> dict:
    if run["status"] != "draft":
        raise Conflict("Only a draft can be prepared", code="bad_state")
    prepare_run(run)
    return get_db().runs.find_one({"_id": run["_id"]})


def unprepare(run: dict) -> dict:
    db = get_db()
    if run["status"] != "ready":
        raise Conflict("Only a ready run can be unprepared", code="bad_state")
    if db.run_items.count_documents({"run_id": run["_id"], "status": {"$in": ["sent", "unknown", "sending"]}}):
        raise Conflict("Something was already sent; cannot unprepare", code="already_sent")
    db.run_items.delete_many({"run_id": run["_id"]})
    db.runs.update_one({"_id": run["_id"]}, {"$set": {"status": "draft", "updated_at": clock.now(),
                                                      "pause_reason": None, "pause_detail": None}})
    return db.runs.find_one({"_id": run["_id"]})


def start(run: dict) -> dict:
    db = get_db()
    if run["status"] != "ready":
        raise Conflict("The run must be ready to start", code="bad_state")
    if run.get("approval") == "manual":
        n = db.run_items.count_documents({"run_id": run["_id"], "status": "needs_review"})
        if n:
            raise Conflict(f"Resolve {n} duplicate(s) (Resend or Skip) before starting a manual run",
                           code="needs_review_unresolved", extra={"needs_review": n})
    now = clock.now()
    res = db.runs.update_one({"_id": run["_id"], "status": "ready"}, {"$set": {
        "status": "running", "started_at": now, "consecutive_failures": 0, "next_send_at": None,
        "pause_reason": None, "pause_detail": None, "updated_at": now}})
    if not res.modified_count:
        raise Conflict("The run is no longer ready", code="bad_state")
    return db.runs.find_one({"_id": run["_id"]})


def pause(run: dict) -> dict:
    if run["status"] != "running":
        raise Conflict("Only a running run can be paused", code="bad_state")
    get_db().runs.update_one({"_id": run["_id"], "status": "running"},
                             {"$set": {"status": "paused_user", "updated_at": clock.now()}})
    return get_db().runs.find_one({"_id": run["_id"]})


def resume(run: dict) -> dict:
    db = get_db()
    st = run["status"]
    now = clock.now()
    if st == "paused_user":
        new = {"status": "running"}
    elif st == "paused_quota":
        sender, detail = pick_sender(run.get("sender_ids") or [])
        if sender is None:
            from ..api.util import ser
            raise Conflict("No sender is available yet", code="no_sender_available", extra=ser(detail))
        new = {"status": "running"}
    elif st == "paused_llm":
        if run.get("mode") == "llm" and not get_settings().llm_fake:
            key, detail = pick_key(run.get("llm_key_ids") or [])
            if key is None:
                from ..api.util import ser
                raise Conflict("No Gemini key is available yet", code="no_key_available", extra=ser(detail))
        new = {"status": "preparing", "next_llm_at": None}
    elif st == "paused_errors":
        new = {"status": "running", "consecutive_failures": 0}
    else:
        raise Conflict("The run is not paused", code="bad_state")
    new.update({"pause_reason": None, "pause_detail": None, "updated_at": now})
    db.runs.update_one({"_id": run["_id"], "status": st}, {"$set": new})
    return db.runs.find_one({"_id": run["_id"]})


def delete_run(run: dict) -> None:
    db = get_db()
    if db.run_items.count_documents({"run_id": run["_id"], "status": "sending"}):
        raise Conflict("An email is being sent right now; try again in a moment", code="sending")
    db.run_items.delete_many({"run_id": run["_id"]})
    db.runs.delete_one({"_id": run["_id"]})
    importer.delete_run_files(run["_id"])
    # contact locks and sent_info are intentionally kept


def reopen_if_completed(run_id) -> None:
    get_db().runs.update_one({"_id": run_id, "status": "completed"},
                             {"$set": {"status": "running", "next_send_at": None, "updated_at": clock.now()}})


def counts(run_id) -> dict:
    out = dict.fromkeys(("pending", "sending", "sent", "failed", "no_contact", "needs_review", "skipped_duplicate", "skipped_user", "unknown"), 0)
    for r in get_db().run_items.aggregate([{"$match": {"run_id": run_id}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        out[r["_id"]] = r["n"]
    out["total"] = sum(out.values())
    return out
