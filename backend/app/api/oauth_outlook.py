from __future__ import annotations

import json
import secrets

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from .. import clock
from ..config import get_settings
from ..crypto import encrypt
from ..db import current_user_id, get_db
from ..errors import Unprocessable
from ..providers.outlook import graph, oauth
from .senders import _validate_cap
from .util import oid

router = APIRouter(prefix="/api/oauth/outlook", tags=["oauth"])


def _require_enabled() -> None:
    if not get_settings().outlook_enabled:
        raise Unprocessable(
            "Outlook is not activated. Follow docs/providers/outlook.md and set OUTLOOK_CLIENT_ID.",
            code="outlook_disabled",
        )


@router.get("/start")
def start(sender_id: str | None = None, display_name: str | None = None, daily_cap: int | None = None):
    _require_enabled()
    verifier, challenge = oauth.make_pkce()
    state = secrets.token_urlsafe(24)
    sid = None
    if sender_id:
        s = get_db().senders.find_one(
            {"_id": oid(sender_id), "user_id": current_user_id(), "provider": "outlook"}
        )
        if not s:
            raise Unprocessable("Unknown Outlook sender", code="unknown_sender")
        sid = s["_id"]
    get_db().oauth_states.insert_one(
        {
            "state": state,
            "code_verifier": verifier,
            "display_name": display_name,
            "daily_cap": daily_cap,
            "sender_id": sid,
            "created_at": clock.now(),
        }
    )
    return {"url": oauth.authorize_url(state, challenge)}


@router.get("/callback")
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    _require_enabled()
    base = "/settings/senders"
    if error:
        return RedirectResponse(f"{base}?error=outlook&detail={(error_description or error)[:120]}")
    if not code or not state:
        raise Unprocessable("Missing code or state", code="invalid_callback")
    db = get_db()
    st = db.oauth_states.find_one_and_delete({"state": state})
    if not st:
        raise Unprocessable("Unknown or expired sign-in attempt. Start again.", code="invalid_state")
    try:
        tokens = oauth.exchange_code(code, st["code_verifier"])
        me = graph.get_me(tokens["access_token"])
    except oauth.OAuthError as e:
        return RedirectResponse(f"{base}?error=outlook&detail={e.code}")
    address = (me.get("mail") or me.get("userPrincipalName") or "").strip().lower()
    if not address:
        return RedirectResponse(f"{base}?error=outlook&detail=no_address")
    enc = encrypt(json.dumps(graph.token_blob(tokens)))
    now = clock.now()
    if st.get("sender_id"):
        db.senders.update_one(
            {"_id": st["sender_id"]},
            {"$set": {"secret_enc": enc, "status": "active", "last_error": None, "updated_at": now}},
        )
    else:
        existing = db.senders.find_one(
            {"user_id": current_user_id(), "provider": "outlook", "address": address}
        )
        if existing:
            db.senders.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "secret_enc": enc,
                        "status": "active",
                        "last_error": None,
                        "deleted_at": None,
                        "updated_at": now,
                    }
                },
            )
        else:
            cap = _validate_cap("outlook", st.get("daily_cap"))
            db.senders.insert_one(
                {
                    "user_id": current_user_id(),
                    "provider": "outlook",
                    "address": address,
                    "display_name": st.get("display_name") or me.get("displayName"),
                    "secret_enc": enc,
                    "daily_cap": cap,
                    "status": "active",
                    "blocked_until": None,
                    "last_error": None,
                    "deleted_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
            )
    return RedirectResponse(f"{base}?connected=outlook")
