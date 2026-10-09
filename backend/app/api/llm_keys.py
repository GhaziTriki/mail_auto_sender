from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import clock
from ..config import get_settings
from ..crypto import decrypt, encrypt
from ..db import current_user_id, get_db
from ..errors import NotFound, Unprocessable
from ..llm.gemini import check_key
from ..services.llm_keys import key_quota, mark_auth_failed, record_request, refresh_day, today_pt
from .util import oid, ser

router = APIRouter(prefix="/api/llm-keys", tags=["llm-keys"])


def key_view(k: dict) -> dict:
    q = key_quota(k)
    out = ser(k)
    out.pop("blocked_until", None)
    out["has_secret"] = bool(k.get("secret_enc"))
    out["quota"] = ser(q)
    return out


def _get(kid: str) -> dict:
    k = get_db().llm_keys.find_one({"_id": oid(kid), "user_id": current_user_id(), "deleted_at": None})
    if not k:
        raise NotFound("Key not found")
    return k


class KeyIn(BaseModel):
    label: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    daily_cap: int | None = None


class KeyPatch(BaseModel):
    label: str | None = None
    daily_cap: int | None = None
    status: str | None = None
    api_key: str | None = None


@router.get("")
def list_keys():
    return [
        key_view(k)
        for k in get_db()
        .llm_keys.find({"user_id": current_user_id(), "deleted_at": None})
        .sort("created_at", 1)
    ]


@router.post("")
def add_key(body: KeyIn):
    cap = body.daily_cap if body.daily_cap is not None else get_settings().default_llm_daily_cap
    if cap < 1:
        raise Unprocessable("daily_cap must be at least 1", code="invalid_cap")
    now = clock.now()
    doc = {
        "user_id": current_user_id(),
        "provider": "gemini",
        "label": body.label.strip(),
        "secret_enc": encrypt(body.api_key.strip()),
        "daily_cap": cap,
        "used_today": 0,
        "day_key": today_pt(now),
        "status": "active",
        "blocked_until": None,
        "last_error": None,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }
    kid = get_db().llm_keys.insert_one(doc).inserted_id
    return key_view(get_db().llm_keys.find_one({"_id": kid}))


@router.patch("/{kid}")
def patch_key(kid: str, body: KeyPatch):
    k = _get(kid)
    upd: dict = {"updated_at": clock.now()}
    if body.label is not None:
        upd["label"] = body.label.strip()
    if body.daily_cap is not None:
        if body.daily_cap < 1:
            raise Unprocessable("daily_cap must be at least 1", code="invalid_cap")
        upd["daily_cap"] = body.daily_cap
    if body.status is not None:
        if body.status not in ("active", "idle"):
            raise Unprocessable("status must be active or idle", code="invalid_status")
        upd["status"] = body.status
    if body.api_key is not None:
        upd["secret_enc"] = encrypt(body.api_key.strip())
        upd["last_error"] = None
        if k.get("status") == "auth_failed" and body.status is None:
            upd["status"] = "active"
    get_db().llm_keys.update_one({"_id": k["_id"]}, {"$set": upd})
    return key_view(get_db().llm_keys.find_one({"_id": k["_id"]}))


@router.delete("/{kid}")
def delete_key(kid: str):
    k = _get(kid)
    get_db().llm_keys.update_one({"_id": k["_id"]}, {"$set": {"deleted_at": clock.now()}})
    return {"ok": True}


@router.post("/{kid}/check")
def check(kid: str):
    k = refresh_day(_get(kid))
    ok, detail, auth_failed = check_key(decrypt(k["secret_enc"]))
    if not get_settings().llm_fake:
        record_request(k["_id"])
    upd: dict = {"updated_at": clock.now()}
    if ok:
        upd["last_error"] = None
        if k.get("status") == "auth_failed":
            upd["status"] = "active"
    else:
        upd["last_error"] = detail[:300]
    get_db().llm_keys.update_one({"_id": k["_id"]}, {"$set": upd})
    if auth_failed:
        mark_auth_failed(k["_id"], detail)
    return {"ok": ok, "detail": detail, "key": key_view(get_db().llm_keys.find_one({"_id": k["_id"]}))}
