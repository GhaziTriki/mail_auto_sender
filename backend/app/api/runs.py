from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .. import clock
from ..db import current_user_id, get_db
from ..errors import ConfigLocked, Conflict, NotFound, Unprocessable
from ..providers.registry import get_provider
from ..services import filters as flt
from ..services import importer, item_actions, run_control
from ..services.filters import select_rows
from ..services.quota import pick_sender, sender_quota
from ..services.recipients import extract_email
from ..worker.send_step import build_outgoing
from .util import oid, ser

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _run(run_id: str) -> dict:
    return run_control.get_run(oid(run_id))


def run_view(run: dict, with_counts: bool = True) -> dict:
    out = ser(run)
    out.pop("source_file_path", None)
    for f in ("source_file", "cv_file"):
        if out.get(f):
            out[f] = {k: v for k, v in out[f].items() if k != "path"}
    if with_counts:
        out["counts"] = run_control.counts(run["_id"])
    return out


class RunCreate(BaseModel):
    name: str


class RunPatch(BaseModel):
    name: str | None = None
    filters: list[dict] | None = None
    recipient: dict | None = None
    mode: str | None = None
    rules: dict | None = None
    greeting: dict | None = None
    template: dict | None = None
    reply_to: str | None = None
    approval: str | None = None
    sender_ids: list[str] | None = None
    llm_key_ids: list[str] | None = None
    delay_min_s: int | None = None
    delay_max_s: int | None = None
    max_retries: int | None = None
    breaker_threshold: int | None = None
    tz_hint: str | None = None


@router.get("")
def list_runs(from_: str | None = Query(None, alias="from"), to: str | None = None, status: str | None = None,
              q: str | None = None, page: int = 1, page_size: int = 50):
    return _list_runs(from_, to, status, q, page, page_size)


def parse_dt(s: str | None):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise Unprocessable("Invalid date", code="invalid_date") from e
    return clock.as_utc(d)


def _list_runs(from_, to, status, q, page, page_size):
    query: dict = {"user_id": current_user_id()}
    dt_from, dt_to = parse_dt(from_), parse_dt(to)
    if dt_from or dt_to:
        query["created_at"] = {}
        if dt_from:
            query["created_at"]["$gte"] = dt_from
        if dt_to:
            query["created_at"]["$lte"] = dt_to
    if status:
        query["status"] = {"$in": status.split(",")}
    if q:
        query["name_lower"] = {"$regex": re.escape(q.lower())}
    db = get_db()
    total = db.runs.count_documents(query)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    runs = list(db.runs.find(query).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size))
    return {"total": total, "page": page, "items": [run_view(r) for r in runs]}


@router.post("")
def create_run(body: RunCreate):
    return run_view(run_control.create_run(body.name))


@router.get("/{run_id}")
def get_run(run_id: str):
    run = _run(run_id)
    out = run_view(run)
    if run["status"] in ("draft",):
        out["preview_rows"] = _preview_rows(run)
    return out


def _preview_rows(run: dict) -> list[dict]:
    rows = []
    for r in importer.read_parsed(run["_id"]) or []:
        rows.append({k: v for k, v in r.items() if k != "_i"})
        if len(rows) >= 20:
            break
    return rows


@router.patch("/{run_id}")
def patch_run(run_id: str, body: RunPatch):
    run = _run(run_id)
    patch = body.model_dump(exclude_unset=True)
    return run_view(run_control.patch_run(run, patch))


@router.delete("/{run_id}")
def delete_run(run_id: str):
    run_control.delete_run(_run(run_id))
    return {"ok": True}


# ---- files --------------------------------------------------------------------------------------

def _ensure_editable(run: dict) -> None:
    if run.get("first_send_at") is not None:
        raise ConfigLocked("Files are locked after the first email was sent")
    if run["status"] != "draft":
        raise Conflict("Unprepare the run before changing files", code="not_draft")


def _source_response(run_id, updates: dict) -> dict:
    preview = updates.pop("_preview", {})
    run = get_db().runs.find_one({"_id": run_id})
    out = run_view(run)
    out["preview_rows"] = preview.get("rows", [])
    out["sheets"] = preview.get("sheets", [])
    return out


@router.post("/{run_id}/source")
async def upload_source(run_id: str, file: UploadFile = File(...)):
    run = _run(run_id)
    _ensure_editable(run)
    raw = await file.read()
    updates = importer.save_source(run["_id"], file.filename or "contacts.csv", raw)
    set_ = {k: v for k, v in updates.items() if k != "_preview"}
    set_.update({"filters": [], "recipient": {"email_column": None, "human_name_columns": [], "company_name_columns": []},
                 "updated_at": clock.now()})
    get_db().runs.update_one({"_id": run["_id"]}, {"$set": set_})
    return _source_response(run["_id"], updates)


class SourceOptions(BaseModel):
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None


@router.put("/{run_id}/source/options")
def source_options(run_id: str, body: SourceOptions):
    run = _run(run_id)
    _ensure_editable(run)
    sf = run.get("source_file")
    if not sf:
        raise Unprocessable("Upload a contacts file first", code="no_source")
    raw = Path(sf["path"]).read_bytes()
    updates = importer.save_source(run["_id"], sf["original_name"], raw, encoding=body.encoding,
                                   delimiter=body.delimiter, sheet=body.sheet)
    set_ = {k: v for k, v in updates.items() if k != "_preview"}
    set_["updated_at"] = clock.now()
    get_db().runs.update_one({"_id": run["_id"]}, {"$set": set_})
    return _source_response(run["_id"], updates)


@router.post("/{run_id}/cv")
async def upload_cv(run_id: str, file: UploadFile = File(...)):
    run = _run(run_id)
    _ensure_editable(run)
    raw = await file.read()
    cv = importer.save_cv(run["_id"], file.filename or "cv.pdf", raw)
    get_db().runs.update_one({"_id": run["_id"]}, {"$set": {"cv_file": cv, "updated_at": clock.now()}})
    return run_view(get_db().runs.find_one({"_id": run["_id"]}))


@router.get("/{run_id}/files/{which}")
def download_file(run_id: str, which: str):
    run = _run(run_id)
    if which == "source" and run.get("source_file"):
        f = run["source_file"]
        return FileResponse(f["path"], filename=f["original_name"])
    if which == "cv" and run.get("cv_file"):
        f = run["cv_file"]
        return FileResponse(f["path"], filename=f["original_name"], media_type="application/pdf")
    raise NotFound("File not found")


# ---- filters ------------------------------------------------------------------------------------

@router.get("/{run_id}/columns/{col}/values")
def column_values(run_id: str, col: str, q: str | None = None, limit: int = 50, offset: int = 0):
    run = _run(run_id)
    if col not in (run.get("columns") or []):
        raise NotFound("Unknown column")
    rows = list(importer.read_parsed(run["_id"]) or [])
    return flt.unique_values(rows, col, q=q, limit=limit, offset=offset)


class FilterPreview(BaseModel):
    filters: list[dict] | None = None
    email_column: str | None = None


@router.post("/{run_id}/filters/preview")
def filters_preview(run_id: str, body: FilterPreview):
    run = _run(run_id)
    filters = body.filters if body.filters is not None else run.get("filters") or []
    email_col = body.email_column or (run.get("recipient") or {}).get("email_column")
    rows = select_rows(run["_id"], filters)
    valid = sum(1 for r in rows if email_col and extract_email(r.get(email_col))) if email_col else 0
    return {"matching_rows": len(rows), "with_valid_email": valid}


# ---- lifecycle ----------------------------------------------------------------------------------

@router.post("/{run_id}/prepare")
def prepare(run_id: str):
    return run_view(run_control.prepare(_run(run_id)))


@router.post("/{run_id}/unprepare")
def unprepare(run_id: str):
    return run_view(run_control.unprepare(_run(run_id)))


@router.post("/{run_id}/start")
def start(run_id: str):
    return run_view(run_control.start(_run(run_id)))


@router.post("/{run_id}/pause")
def pause(run_id: str):
    return run_view(run_control.pause(_run(run_id)))


@router.post("/{run_id}/resume")
def resume(run_id: str):
    return run_view(run_control.resume(_run(run_id)))


@router.post("/{run_id}/rerender")
def rerender(run_id: str):
    from ..services.prepare import rerender_run
    run = _run(run_id)
    return {"rerendered": rerender_run(run["_id"])}


class TestSend(BaseModel):
    item_id: str | None = None


@router.post("/{run_id}/test-send")
def test_send(run_id: str, body: TestSend | None = None):
    run = _run(run_id)
    db = get_db()
    if body and body.item_id:
        item = db.run_items.find_one({"_id": oid(body.item_id), "run_id": run["_id"]})
    else:
        item = db.run_items.find_one({"run_id": run["_id"], "status": "pending", "classified": True},
                                     sort=[("row_index", 1)])
    if not item:
        raise Unprocessable("There is no prepared email to test with", code="no_item")
    sender, detail = pick_sender(run.get("sender_ids") or [])
    if sender is None:
        raise Conflict("No sender is available", code="no_sender_available", extra=ser(detail))
    email = build_outgoing(run, sender, item, to=sender["address"], subject_prefix="[TEST] ")
    res = get_provider(sender["provider"]).send(sender, email)  # no item/contact/send_log changes
    return {"ok": res.outcome == "sent", "outcome": res.outcome, "detail": res.detail, "to": sender["address"]}


# ---- manual window / items ----------------------------------------------------------------------

@router.get("/{run_id}/next")
def next_item(run_id: str):
    run = _run(run_id)
    db = get_db()
    item = db.run_items.find_one({"run_id": run["_id"], "status": "pending", "classified": True},
                                 sort=[("row_index", 1)])
    sender, detail = pick_sender(run.get("sender_ids") or [])
    sender_info = None
    if sender:
        sender_info = {"id": str(sender["_id"]), "address": sender["address"], "provider": sender["provider"],
                       "quota": ser(sender_quota(sender))}
    remaining = db.run_items.count_documents({"run_id": run["_id"], "status": "pending"})
    return {"item": item_view(item) if item else None, "sender": sender_info, "remaining_pending": remaining,
            "sender_problem": ser(detail) if sender is None else None}


def item_view(item: dict) -> dict:
    out = ser(item)
    out["contact_line"] = {"column": item.get("email_source_column"), "raw": item.get("email_raw"),
                           "email": item.get("email_norm")}
    if item.get("contact_id") is not None and item["status"] in ("needs_review", "skipped_duplicate"):
        c = get_db().contacts.find_one({"_id": item["contact_id"]})
        out["prior_send"] = ser((c or {}).get("sent_info"))
    return out


@router.get("/{run_id}/items")
def list_items(run_id: str, status: str | None = None, q: str | None = None, page: int = 1, page_size: int = 50,
               sort: str = "row_index"):
    run = _run(run_id)
    query: dict = {"run_id": run["_id"]}
    if status:
        query["status"] = {"$in": status.split(",")}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"email_norm": rx}, {"name": rx}, {"company": rx}, {"subject": rx}]
    sort_field = {"row_index": ("row_index", 1), "-row_index": ("row_index", -1), "sent_at": ("sent_at", 1),
                  "-sent_at": ("sent_at", -1), "updated_at": ("updated_at", 1), "-updated_at": ("updated_at", -1)}.get(
        sort, ("row_index", 1))
    db = get_db()
    total = db.run_items.count_documents(query)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    items = list(db.run_items.find(query).sort(*sort_field).skip((page - 1) * page_size).limit(page_size))
    return {"total": total, "page": page, "items": [item_view(i) for i in items]}


class Bulk(BaseModel):
    action: str
    item_ids: list[str] | None = None
    status_filter: str | None = None


@router.post("/{run_id}/items/bulk")
def bulk(run_id: str, body: Bulk):
    run = _run(run_id)
    res = item_actions.bulk_action(run, body.action, body.item_ids, body.status_filter)
    return res


@router.post("/{run_id}/approve-all")
def approve_all(run_id: str):
    """Send window: 'Approve all remaining' switches the run to auto approval."""
    run = _run(run_id)
    get_db().runs.update_one({"_id": run["_id"]}, {"$set": {"approval": "auto", "updated_at": clock.now()}})
    return run_view(get_db().runs.find_one({"_id": run["_id"]}))


@router.get("/{run_id}/export.csv")
def export_csv(run_id: str):
    run = _run(run_id)
    cols = ["row_index", "status", "email", "kind", "name", "company", "decided_by", "subject", "sender", "sent_at",
            "last_error", "warnings"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for it in get_db().run_items.find({"run_id": run["_id"]}).sort("row_index", 1):
        last_err = ""
        if it.get("attempts"):
            last = it["attempts"][-1]
            if last.get("outcome") not in ("sent",):
                last_err = last.get("detail") or ""
        w.writerow([it["row_index"], it["status"], it.get("email_norm") or "", it.get("kind") or "",
                    it.get("name") or "", it.get("company") or "", it.get("decided_by") or "", it.get("subject") or "",
                    it.get("sender_address") or "", it["sent_at"].isoformat() if it.get("sent_at") else "", last_err,
                    ";".join(it.get("warnings") or [])])
    buf.seek(0)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", run["name"])[:60] or "run"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{safe}.csv"'})
