"""Prepare a run: create items (spec 9.2) and classification support (spec 9.3)."""

from __future__ import annotations

from .. import clock
from ..db import current_user_id, get_db
from ..errors import Unprocessable
from ..llm.rules import classify_rules
from .filters import select_rows
from .recipients import extract_email
from .render import ensure_valid_template, merged_warnings, render_item


def check_preconditions(run: dict) -> int:
    """Return matching row count or raise 422 with a field-level message."""
    db = get_db()
    errors: dict[str, str] = {}
    if not run.get("source_file"):
        errors["source_file"] = "Upload a contacts file"
    if not run.get("cv_file"):
        errors["cv_file"] = "Upload a CV (PDF)"
    rec = run.get("recipient") or {}
    cols = run.get("columns") or []
    if not rec.get("email_column"):
        errors["recipient.email_column"] = "Choose the email column"
    elif rec["email_column"] not in cols:
        errors["recipient.email_column"] = "The email column does not exist in the file"
    if not run.get("sender_ids"):
        errors["sender_ids"] = "Choose at least one sender"
    else:
        live = db.senders.count_documents({"_id": {"$in": run["sender_ids"]}, "deleted_at": None})
        if live == 0:
            errors["sender_ids"] = "None of the chosen senders exists any more"
    tpl = run.get("template") or {}
    terrs = []
    if not errors.get("source_file"):
        from .render import validate_template

        terrs = validate_template(tpl, cols)
    if terrs:
        errors["template"] = "; ".join(terrs)
    if run.get("mode") == "llm":
        from ..config import get_settings

        if not get_settings().llm_fake:
            live = db.llm_keys.count_documents(
                {"_id": {"$in": run.get("llm_key_ids") or []}, "deleted_at": None}
            )
            if live == 0:
                errors["llm_key_ids"] = "LLM mode needs at least one Gemini key"
    matching = 0
    if not errors:
        matching = len(select_rows(run["_id"], run.get("filters") or []))
        if matching == 0:
            errors["filters"] = "No rows match the filters"
    if errors:
        raise Unprocessable(
            "; ".join(f"{k}: {v}" for k, v in errors.items()),
            code="prepare_preconditions",
            extra={"fields": errors},
        )
    return matching


def build_items(run: dict, rows: list[dict]) -> list[dict]:
    """Create item docs (with contact upserts) following spec 9.2, preserving file order."""
    db = get_db()
    now = clock.now()
    email_col = run["recipient"]["email_column"]
    seen: dict[str, object] = {}
    docs: list[dict] = []
    from bson import ObjectId

    for r in rows:
        idx = r["_i"]
        row = {k: v for k, v in r.items() if k != "_i"}
        raw = (row.get(email_col) or "").strip()
        email = extract_email(raw)
        item = {
            "_id": ObjectId(),
            "run_id": run["_id"],
            "contact_id": None,
            "row_index": idx,
            "row": row,
            "email_source_column": email_col,
            "email_raw": raw,
            "email_norm": email,
            "classified": False,
            "kind": None,
            "name": None,
            "company": None,
            "honorific": None,
            "decided_by": None,
            "llm_key_id": None,
            "llm_attempts": 0,
            "greeting_text": "",
            "subject": "",
            "body": "",
            "edited": False,
            "warnings": [],
            "class_warnings": [],
            "status": "pending",
            "approved": False,
            "override_duplicate": False,
            "duplicate_of_item_id": None,
            "duplicate_reason": None,
            "attempt_count": 0,
            "next_attempt_at": None,
            "lease_until": None,
            "attempts": [],
            "sender_id": None,
            "sender_address": None,
            "sender_provider": None,
            "attempted_at": None,
            "message_id": None,
            "sent_at": None,
            "created_at": now,
            "updated_at": now,
        }
        if email is None:
            item["status"] = "no_contact"
            item["classified"] = True  # nothing to classify
        elif email in seen:
            item["status"] = "skipped_duplicate"
            item["duplicate_reason"] = "duplicate_in_run"
            item["duplicate_of_item_id"] = seen[email]
            item["classified"] = True
        else:
            contact = db.contacts.find_one_and_update(
                {"user_id": current_user_id(), "email_norm": email},
                {
                    "$setOnInsert": {
                        "user_id": current_user_id(),
                        "email_norm": email,
                        "first_seen_at": now,
                        "sent_item_id": None,
                        "sent_info": None,
                    }
                },
                upsert=True,
                return_document=True,
            )
            item["contact_id"] = contact["_id"]
            seen[email] = item["_id"]
            if contact.get("sent_item_id") is not None:
                item["status"] = "needs_review"
                item["duplicate_reason"] = "already_sent"
                item["duplicate_of_item_id"] = contact["sent_item_id"]
        docs.append(item)
    return docs


def prepare_run(run: dict) -> int:
    db = get_db()
    ensure_valid_template(run.get("template") or {}, run.get("columns") or [])
    check_preconditions(run)
    rows = select_rows(run["_id"], run.get("filters") or [])
    docs = build_items(run, rows)
    for i in range(0, len(docs), 500):
        db.run_items.insert_many(docs[i : i + 500])
    db.runs.update_one(
        {"_id": run["_id"]},
        {
            "$set": {
                "status": "preparing",
                "pause_reason": None,
                "pause_detail": None,
                "next_llm_at": None,
                "updated_at": clock.now(),
            }
        },
    )
    return len(docs)


def apply_classification(run: dict, item: dict, result: dict, key_id=None) -> None:
    """Persist a classification result on an item and render its email."""
    db = get_db()
    fields = {
        "kind": result["kind"],
        "name": result.get("name"),
        "company": result.get("company"),
        "honorific": result.get("honorific"),
        "decided_by": result["decided_by"],
        "classified": True,
        "class_warnings": list(result.get("warnings") or []),
        "llm_key_id": key_id,
        "updated_at": clock.now(),
    }
    merged = {**item, **fields}
    rendered = render_item(run, merged)
    fields.update(
        {
            "greeting_text": rendered["greeting_text"],
            "subject": rendered["subject"],
            "body": rendered["body"],
            "warnings": merged_warnings(merged, rendered["render_warnings"]),
        }
    )
    db.run_items.update_one({"_id": item["_id"], "classified": False}, {"$set": fields})


def rules_result(run: dict, item: dict, extra_warning: str | None = None) -> dict:
    res = classify_rules(
        run.get("rules", {}).get("kind", "human_if_available"),
        run["recipient"],
        item["row"],
        item["email_norm"],
    )
    if extra_warning:
        res["warnings"] = [*res["warnings"], extra_warning]
    return res


def rerender_run(run_id) -> int:
    """Re-render all classified items with edited=false (spec 8.4). Returns the number re-rendered."""
    db = get_db()
    run = db.runs.find_one({"_id": run_id})
    n = 0
    for item in db.run_items.find(
        {
            "run_id": run_id,
            "classified": True,
            "edited": False,
            "email_norm": {"$ne": None},
            "status": {"$in": ["pending", "needs_review", "failed"]},
        }
    ):
        rendered = render_item(run, item)
        db.run_items.update_one(
            {"_id": item["_id"], "edited": False},
            {
                "$set": {
                    "greeting_text": rendered["greeting_text"],
                    "subject": rendered["subject"],
                    "body": rendered["body"],
                    "warnings": merged_warnings(item, rendered["render_warnings"]),
                    "updated_at": clock.now(),
                }
            },
        )
        n += 1
    return n
