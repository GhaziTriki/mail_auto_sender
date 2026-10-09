"""Microsoft identity platform: auth-code + PKCE for a public client (spec 10.2). No client secret."""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

from ...config import get_settings

AUTHORITY = "https://login.microsoftonline.com/common/oauth2/v2.0/"
SCOPES = "https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/User.Read offline_access"

_client_factory = lambda: httpx.Client(timeout=30)  # noqa: E731


def set_client_factory(factory) -> None:
    """Tests only."""
    global _client_factory
    _client_factory = factory or (lambda: httpx.Client(timeout=30))


class OAuthError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def make_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def authorize_url(state: str, challenge: str) -> str:
    s = get_settings()
    q = {"client_id": s.outlook_client_id, "response_type": "code", "redirect_uri": s.outlook_redirect_uri,
         "response_mode": "query", "scope": SCOPES, "state": state, "code_challenge": challenge,
         "code_challenge_method": "S256", "prompt": "select_account"}
    return AUTHORITY + "authorize?" + urlencode(q)


def _token_request(data: dict) -> dict:
    with _client_factory() as c:
        r = c.post(AUTHORITY + "token", data=data)
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {}
    if r.status_code != 200 or "access_token" not in body:
        raise OAuthError(body.get("error", f"http_{r.status_code}"), body.get("error_description", r.text[:200]))
    return body


def exchange_code(code: str, verifier: str) -> dict:
    s = get_settings()
    return _token_request({"client_id": s.outlook_client_id, "grant_type": "authorization_code", "code": code,
                           "redirect_uri": s.outlook_redirect_uri, "code_verifier": verifier, "scope": SCOPES})


def refresh(refresh_token: str) -> dict:
    s = get_settings()
    return _token_request({"client_id": s.outlook_client_id, "grant_type": "refresh_token",
                           "refresh_token": refresh_token, "scope": SCOPES})
