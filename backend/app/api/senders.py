from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import clock
from ..config import get_settings
from ..crypto import encrypt
from ..db import current_user_id, get_db
from ..errors import Conflict, NotFound, Unprocessable
from ..providers.registry import get_provider
from ..services.quota import sender_quota
from .util import oid, ser

router = APIRouter(prefix="/api/senders", tags=["senders"])


def sender_view(s: dict) -> dict:
    q = sender_quota(s)
    out = ser(s)
    out.pop("blocked_until", None)
    out["has_secret"] = bool(s.get("secret_enc"))
    out["quota"] = ser(q)
    return out


def _get_sender(sid: str) -> dict:
    s = get_db().senders.find_one({"_id": oid(sid), "user_id": current_user_id(), "deleted_at": None})
    if not s:
        raise NotFound("Sender not found")
    return s


def cap_limits(provider: str) -> tuple[int, int]:
    st = get_settings()
    if provider == "outlook":
        return st.default_outlook_daily_cap, st.max_outlook_daily_cap
    return st.default_gmail_daily_cap, st.max_gmail_daily_cap


def _validate_cap(provider: str, cap: int | None) -> int:
    default, maximum = cap_limits(provider)
    if cap is None:
        return default
    if cap < 1 or cap > maximum:
        raise Unprocessable(f"daily_cap must be between 1 and {maximum}", code="invalid_cap")
    return cap


class GmailIn(BaseModel):
    address: str
    display_name: str | None = None
    app_password: str = Field(min_length=1)
    daily_cap: int | None = None


class SenderPatch(BaseModel):
    daily_cap: int | None = None
    display_name: str | None = None
    status: str | None = None
    app_password: str | None = None


@router.get("")
def list_senders(provider: str | None = None):
    q = {"user_id": current_user_id(), "deleted_at": None}
    if provider:
        q["provider"] = provider
    return [sender_view(s) for s in get_db().senders.find(q).sort("created_at", 1)]


def _norm_address(address: str) -> str:
    from email_validator import EmailNotValidError, validate_email

    try:
        return validate_email(address.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as e:
        raise Unprocessable(f"Invalid email address: {e}", code="invalid_address") from e


@router.post("/gmail")
def add_gmail(body: GmailIn):
    db = get_db()
    address = _norm_address(body.address)
    pw = body.app_password.replace(" ", "")
    cap = _validate_cap("gmail", body.daily_cap)
    now = clock.now()
    existing = db.senders.find_one({"user_id": current_user_id(), "provider": "gmail", "address": address})
    if existing and not existing.get("deleted_at"):
        raise Conflict("This Gmail account already exists. Edit it instead.", code="sender_exists")
    fields = {
        "display_name": body.display_name,
        "secret_enc": encrypt(pw),
        "daily_cap": cap,
        "status": "active",
        "blocked_until": None,
        "last_error": None,
        "deleted_at": None,
        "updated_at": now,
    }
    if existing:  # undelete and replace the secret
        db.senders.update_one({"_id": existing["_id"]}, {"$set": fields})
        sid = existing["_id"]
    else:
        doc = {
            "user_id": current_user_id(),
            "provider": "gmail",
            "address": address,
            "created_at": now,
            **fields,
        }
        sid = db.senders.insert_one(doc).inserted_id
    return sender_view(db.senders.find_one({"_id": sid}))


@router.post("")
def add_sender(body: dict):
    if body.get("provider", "gmail") != "gmail":
        raise Unprocessable(
            "Outlook accounts are connected through OAuth (/api/oauth/outlook/start)", code="use_oauth"
        )
    return add_gmail(GmailIn(**{k: v for k, v in body.items() if k != "provider"}))


@router.patch("/{sid}")
def patch_sender(sid: str, body: SenderPatch):
    s = _get_sender(sid)
    upd: dict = {"updated_at": clock.now()}
    if body.daily_cap is not None:
        upd["daily_cap"] = _validate_cap(s["provider"], body.daily_cap)
    if body.display_name is not None:
        upd["display_name"] = body.display_name
    if body.status is not None:
        if body.status not in ("active", "idle"):
            raise Unprocessable("status must be active or idle", code="invalid_status")
        upd["status"] = body.status
    if body.app_password is not None:
        if s["provider"] != "gmail":
            raise Unprocessable("Only Gmail senders have an app password", code="invalid")
        upd["secret_enc"] = encrypt(body.app_password.replace(" ", ""))
        upd["last_error"] = None
        if s.get("status") == "auth_failed" and body.status is None:
            upd["status"] = "active"
    get_db().senders.update_one({"_id": s["_id"]}, {"$set": upd})
    return sender_view(get_db().senders.find_one({"_id": s["_id"]}))


@router.post("/{sid}/check")
def check_sender(sid: str):
    s = _get_sender(sid)
    res = get_provider(s["provider"]).check(s)
    upd: dict = {"updated_at": clock.now()}
    if res.ok:
        upd["last_error"] = None
        if s.get("status") == "auth_failed":
            upd["status"] = "active"
    else:
        upd["last_error"] = res.detail[:500]
        if res.auth_failed:
            upd["status"] = "auth_failed"
    get_db().senders.update_one({"_id": s["_id"]}, {"$set": upd})
    return {
        "ok": res.ok,
        "detail": res.detail,
        "sender": sender_view(get_db().senders.find_one({"_id": s["_id"]})),
    }


@router.delete("/{sid}")
def delete_sender(sid: str):
    s = _get_sender(sid)
    get_db().senders.update_one(
        {"_id": s["_id"]}, {"$set": {"deleted_at": clock.now(), "updated_at": clock.now()}}
    )
    return {"ok": True}
