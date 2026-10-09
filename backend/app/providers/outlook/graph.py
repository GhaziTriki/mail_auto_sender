"""Microsoft Graph sendMail (spec 10.2)."""
from __future__ import annotations

import base64
import json
from datetime import timedelta

import httpx

from ... import clock
from ...crypto import decrypt, encrypt
from ...db import get_db
from ..base import CheckResult, OutgoingEmail, SendResult
from ..message import has_crlf
from . import oauth

GRAPH = "https://graph.microsoft.com/v1.0"


def _factory():
    return oauth._client_factory()


def get_me(access_token: str) -> dict:
    with _factory() as c:
        r = c.get(f"{GRAPH}/me", headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code != 200:
        raise oauth.OAuthError(f"http_{r.status_code}", r.text[:200])
    return r.json()


def token_blob(tokens: dict) -> dict:
    exp = clock.now() + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    return {"refresh_token": tokens.get("refresh_token"), "access_token": tokens["access_token"],
            "expires_at": exp.isoformat()}


def _load(sender: dict) -> dict:
    return json.loads(decrypt(sender["secret_enc"]))


def _save(sender: dict, blob: dict) -> None:
    enc = encrypt(json.dumps(blob))
    sender["secret_enc"] = enc
    get_db().senders.update_one({"_id": sender["_id"]}, {"$set": {"secret_enc": enc, "updated_at": clock.now()}})


def _refresh(sender: dict, blob: dict) -> dict:
    tokens = oauth.refresh(blob["refresh_token"])
    new = token_blob(tokens)
    if not new.get("refresh_token"):
        new["refresh_token"] = blob["refresh_token"]
    _save(sender, new)
    return new


def _expires_soon(blob: dict) -> bool:
    from datetime import datetime
    try:
        exp = clock.as_utc(datetime.fromisoformat(blob["expires_at"]))
    except Exception:  # noqa: BLE001
        return True
    return exp - clock.now() <= timedelta(seconds=120)


def _payload(email: OutgoingEmail) -> dict:
    msg = {
        "subject": email.subject,
        "body": {"contentType": "Text", "content": email.body_text},
        "toRecipients": [{"emailAddress": {"address": email.to}}],
        "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": email.attachment_name,
                         "contentType": "application/pdf",
                         "contentBytes": base64.b64encode(email.attachment_bytes).decode()}],
    }
    if email.reply_to:
        msg["replyTo"] = [{"emailAddress": {"address": email.reply_to}}]
    return {"message": msg, "saveToSentItems": True}


def map_response(status: int, body_text: str, headers: dict | None = None) -> SendResult:
    """Pure mapping of a Graph response to a SendResult (401 is handled by the caller)."""
    low = (body_text or "").lower()
    detail = f"{status} {body_text[:300]}"
    if status == 202:
        return SendResult("sent", "202 Accepted")
    if status == 401:
        return SendResult("auth", detail)
    if status == 429:
        ra = None
        try:
            ra = int((headers or {}).get("Retry-After") or (headers or {}).get("retry-after"))
        except (TypeError, ValueError):
            ra = None
        return SendResult("transient", detail, retry_after_s=ra)
    if status in (503, 504):
        return SendResult("transient", detail)
    if status in (400, 403) and "quota" in low:
        return SendResult("quota", detail)
    if 400 <= status < 500:
        return SendResult("permanent", detail)
    if status >= 500:
        return SendResult("transient", detail)
    return SendResult("permanent", detail)


class OutlookProvider:
    name = "outlook"

    def check(self, sender: dict) -> CheckResult:
        try:
            blob = _load(sender)
            if _expires_soon(blob):
                blob = _refresh(sender, blob)
            me = get_me(blob["access_token"])
            return CheckResult(True, f"Signed in as {me.get('mail') or me.get('userPrincipalName')}")
        except oauth.OAuthError as e:
            return CheckResult(False, f"{e.code}: {e.detail}", auth_failed=e.code in ("invalid_grant", "http_401",
                                                                                       "interaction_required"))
        except Exception as e:  # noqa: BLE001
            return CheckResult(False, f"{type(e).__name__}: {e}")

    def _post(self, access: str, email: OutgoingEmail):
        with _factory() as c:
            return c.post(f"{GRAPH}/me/sendMail", json=_payload(email),
                          headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"})

    def send(self, sender: dict, email: OutgoingEmail) -> SendResult:
        if has_crlf(email.to, email.subject, email.reply_to):
            return SendResult("permanent", "Header fields must not contain line breaks", recipient_specific=True)
        try:
            blob = _load(sender)
            if _expires_soon(blob):
                blob = _refresh(sender, blob)
        except oauth.OAuthError as e:
            if e.code == "invalid_grant":
                return SendResult("auth", f"{e.code}: {e.detail}")
            return SendResult("transient", f"token refresh failed: {e.code}")
        except httpx.TransportError as e:
            return SendResult("transient", f"token refresh network error: {type(e).__name__}")
        refreshed_once = False
        while True:
            try:
                r = self._post(blob["access_token"], email)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
                return SendResult("transient", f"connection failed before sending: {type(e).__name__}")
            except httpx.TransportError as e:  # request may have reached Graph
                return SendResult("unknown", f"connection lost after sending: {type(e).__name__}")
            if r.status_code == 401 and not refreshed_once:
                refreshed_once = True
                try:
                    blob = _refresh(sender, blob)
                except oauth.OAuthError as e:
                    return SendResult("auth", f"{e.code}: {e.detail}")
                except httpx.TransportError as e:
                    return SendResult("transient", f"token refresh network error: {type(e).__name__}")
                continue
            return map_response(r.status_code, r.text, dict(r.headers))
