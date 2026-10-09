from __future__ import annotations

import base64
import json
import socket
import threading
from datetime import timedelta

import httpx
import pytest

from app import clock
from app.crypto import decrypt, encrypt
from app.db import get_db
from app.providers.base import OutgoingEmail
from app.providers.gmail import GmailProvider
from app.providers.outlook import oauth
from app.providers.registry import get_provider, list_providers
from tests.helpers import PDF, add_sender


# ---------------------------------------------------------------- tiny fake SMTP server
class FakeSMTP:
    def __init__(self, rcpt_reply=b"250 OK", data_mode="ok"):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.messages: list[bytes] = []
        self.rcpt_reply, self.data_mode = rcpt_reply, data_mode
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        f = conn.makefile("rwb")
        f.write(b"220 fake\r\n")
        f.flush()
        while True:
            line = f.readline()
            if not line:
                return
            cmd = line.strip().upper()
            if cmd.startswith(b"EHLO") or cmd.startswith(b"HELO"):
                f.write(b"250 fake\r\n")
            elif cmd.startswith(b"MAIL"):
                f.write(b"250 OK\r\n")
            elif cmd.startswith(b"RCPT"):
                f.write(self.rcpt_reply + b"\r\n")
            elif cmd == b"DATA":
                f.write(b"354 go\r\n")
                f.flush()
                buf = b""
                while True:
                    line = f.readline()
                    if line == b".\r\n":
                        break
                    buf += line
                if self.data_mode == "drop":
                    conn.close()
                    return
                self.messages.append(buf)
                f.write(b"250 queued\r\n")
            elif cmd == b"QUIT":
                f.write(b"221 bye\r\n")
                f.flush()
                conn.close()
                return
            else:
                f.write(b"250 OK\r\n")
            f.flush()


def _email(to="rcpt@example.com"):
    return OutgoingEmail("Faf", "sender@gmail.com", to, None, "Hello", "Body text é", "My CV.pdf", PDF)


@pytest.fixture()
def smtp_settings(settings):
    settings.gmail_smtp_host, settings.gmail_smtp_security, settings.gmail_smtp_auth = (
        "127.0.0.1",
        "none",
        False,
    )
    return settings


def test_gmail_send_builds_message_and_maps_sent(smtp_settings, db, frozen):
    srv = FakeSMTP()
    smtp_settings.gmail_smtp_port = srv.port
    sender = db.senders.find_one({"_id": add_sender("sender@gmail.com")})
    res = GmailProvider().send(sender, _email())
    assert res.outcome == "sent" and res.message_id.startswith("<") and res.message_id.endswith("@gmail.com>")
    import email as emaillib

    msg = emaillib.message_from_bytes(srv.messages[0])
    assert msg["To"] == "rcpt@example.com" and msg["Reply-To"] == "sender@gmail.com" and "Faf" in msg["From"]
    assert msg["Message-ID"] == res.message_id
    parts = list(msg.walk())
    assert any(p.get_content_type() == "application/pdf" and p.get_filename() == "My CV.pdf" for p in parts)
    text = next(p for p in parts if p.get_content_type() == "text/plain").get_payload(decode=True).decode()
    assert "Body text é" in text


def test_gmail_rcpt_refused_is_recipient_specific_permanent(smtp_settings, db, frozen):
    srv = FakeSMTP(rcpt_reply=b"550 5.1.1 no such user")
    smtp_settings.gmail_smtp_port = srv.port
    sender = db.senders.find_one({"_id": add_sender("sender@gmail.com")})
    res = GmailProvider().send(sender, _email())
    assert res.outcome == "permanent" and res.recipient_specific and srv.messages == []


def test_gmail_disconnect_during_data_is_unknown(smtp_settings, db, frozen):
    srv = FakeSMTP(data_mode="drop")
    smtp_settings.gmail_smtp_port = srv.port
    sender = db.senders.find_one({"_id": add_sender("sender@gmail.com")})
    assert GmailProvider().send(sender, _email()).outcome == "unknown"


def test_gmail_connect_failure_is_transient(smtp_settings, db, frozen):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    smtp_settings.gmail_smtp_port = port
    sender = db.senders.find_one({"_id": add_sender("sender@gmail.com")})
    assert GmailProvider().send(sender, _email()).outcome == "transient"


def test_gmail_crlf_rejected(smtp_settings, db, frozen):
    sender = db.senders.find_one({"_id": add_sender("sender@gmail.com")})
    res = GmailProvider().send(sender, _email(to="a@b.com\r\nBcc: x@y.com"))
    assert res.outcome == "permanent" and res.recipient_specific


def test_gmail_check_login(smtp_settings, db, frozen):
    srv = FakeSMTP()
    smtp_settings.gmail_smtp_port = srv.port
    sender = db.senders.find_one({"_id": add_sender("sender@gmail.com")})
    assert GmailProvider().check(sender).ok


# ---------------------------------------------------------------- registry / senders API
def test_registry_outlook_disabled_by_default(settings, db):
    assert {p["name"]: p["enabled"] for p in list_providers()} == {"gmail": True, "outlook": False}
    from app.errors import Unprocessable

    with pytest.raises(Unprocessable):
        get_provider("outlook")


def test_senders_api_add_cap_limits_and_undelete(client):
    r = client.post(
        "/api/senders/gmail", json={"address": "X@Gmail.com", "app_password": "abcd efgh ijkl mnop"}
    )
    assert r.status_code == 200 and r.json()["address"] == "x@gmail.com" and r.json()["daily_cap"] == 100
    sid = r.json()["id"]
    assert decrypt(get_db().senders.find_one()["secret_enc"]) == "abcdefghijklmnop"
    assert (
        client.post("/api/senders/gmail", json={"address": "x@gmail.com", "app_password": "z"}).status_code
        == 409
    )
    assert client.patch(f"/api/senders/{sid}", json={"daily_cap": 401}).status_code == 422
    assert (
        client.patch(f"/api/senders/{sid}", json={"daily_cap": 400, "status": "idle"}).json()["status"]
        == "idle"
    )
    assert client.delete(f"/api/senders/{sid}").status_code == 200
    assert client.get("/api/senders").json() == []
    r = client.post(
        "/api/senders/gmail", json={"address": "x@gmail.com", "app_password": "newpw", "daily_cap": 50}
    )
    assert r.json()["id"] == sid and r.json()["status"] == "active" and r.json()["daily_cap"] == 50
    assert decrypt(get_db().senders.find_one()["secret_enc"]) == "newpw"


def test_sender_check_endpoint_sets_auth_failed(client, provider):
    from app.providers.base import CheckResult

    sid = client.post("/api/senders/gmail", json={"address": "c@gmail.com", "app_password": "pw"}).json()[
        "id"
    ]
    provider.check_result = CheckResult(False, "535 bad", auth_failed=True)
    r = client.post(f"/api/senders/{sid}/check").json()
    assert not r["ok"] and r["sender"]["status"] == "auth_failed"
    provider.check_result = CheckResult(True, "ok")
    assert client.post(f"/api/senders/{sid}/check").json()["sender"]["status"] == "active"


def test_llm_key_check_and_daily_reset(client, settings, monkeypatch):
    settings.llm_fake = False
    from app.llm import gemini

    monkeypatch.setattr(gemini, "call_gemini", lambda k, p: [])
    k = client.post("/api/llm-keys", json={"label": "a", "api_key": "AIzaK", "daily_cap": 2}).json()
    r = client.post(f"/api/llm-keys/{k['id']}/check").json()
    assert r["ok"] and r["key"]["quota"]["used"] == 1
    client.post(f"/api/llm-keys/{k['id']}/check")
    assert client.get("/api/llm-keys").json()[0]["quota"]["exhausted"]
    clock.advance(hours=25)  # next Pacific day: lazy reset
    q = client.get("/api/llm-keys").json()[0]["quota"]
    assert q["used"] == 0 and not q["exhausted"]


def test_gemini_error_mapping():
    from app.llm.gemini import classify_exception

    class E(Exception):
        def __init__(self, code, msg):
            super().__init__(msg)
            self.code = code

    assert classify_exception(E(429, "RESOURCE_EXHAUSTED")).kind == "quota"
    assert classify_exception(E(400, "API key not valid")).kind == "auth"
    assert classify_exception(E(403, "denied")).kind == "auth"
    assert classify_exception(E(500, "boom")).kind == "transient"
    assert classify_exception(ConnectionError("net")).kind == "transient"


# ---------------------------------------------------------------- Outlook with mocked Graph / login
@pytest.fixture()
def outlook(settings, db, frozen):
    settings.outlook_client_id = "client-123"
    calls = []
    state = {"sendmail": [202], "tokens": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        url = str(request.url)
        if url.endswith("/oauth2/v2.0/token"):
            data = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            state["tokens"] += 1
            if data.get("grant_type") == "refresh_token" and data["refresh_token"] == "revoked":
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "expired"})
            return httpx.Response(
                200,
                json={
                    "access_token": f"at{state['tokens']}",
                    "refresh_token": f"rt{state['tokens']}",
                    "expires_in": 3600,
                },
            )
        if url.endswith("/v1.0/me"):
            return httpx.Response(200, json={"mail": "Me@Outlook.com", "displayName": "Me"})
        if url.endswith("/me/sendMail"):
            code = state["sendmail"].pop(0) if state["sendmail"] else 202
            hdr = {"Retry-After": "30"} if code == 429 else {}
            body = '{"error":{"code":"ErrorQuotaExceeded"}}' if code == 403 else ""
            state["last_payload"] = json.loads(request.content)
            state["last_auth"] = request.headers["authorization"]
            return httpx.Response(code, text=body, headers=hdr)
        return httpx.Response(404)

    oauth.set_client_factory(lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    yield state, calls
    oauth.set_client_factory(None)


def _outlook_sender(db, access="at0", refresh="rt0", expires_in=3600):
    blob = {
        "refresh_token": refresh,
        "access_token": access,
        "expires_at": (clock.now() + timedelta(seconds=expires_in)).isoformat(),
    }
    sid = add_sender("me@outlook.com", provider="outlook")
    db.senders.update_one({"_id": sid}, {"$set": {"secret_enc": encrypt(json.dumps(blob))}})
    return sid


def test_outlook_oauth_flow_and_tab_enabled(client, outlook):
    clock.freeze()  # mongomock applies the 10-minute TTL against the real clock
    assert client.get("/api/providers").json()[1] == {
        "name": "outlook",
        "enabled": True,
        "setup_doc": "/docs-static/providers/outlook.md",
    }
    url = client.get("/api/oauth/outlook/start").json()["url"]
    assert (
        "code_challenge_method=S256" in url
        and "client_id=client-123" in url
        and "prompt=select_account" in url
    )
    assert "Mail.Send" in url and "offline_access" in url and "client_secret" not in url
    state = get_db().oauth_states.find_one()["state"]
    r = client.get(f"/api/oauth/outlook/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/settings/senders?connected=outlook"
    s = get_db().senders.find_one({"provider": "outlook"})
    assert s["address"] == "me@outlook.com" and s["daily_cap"] == 100 and s["status"] == "active"
    blob = json.loads(decrypt(s["secret_enc"]))
    assert blob["refresh_token"] == "rt1" and "client_secret" not in json.dumps(blob)
    assert "rt1" not in client.get("/api/senders").text
    r = client.get(f"/api/oauth/outlook/callback?code=abc&state={state}")  # state is single-use
    assert r.status_code == 422


def test_outlook_start_disabled_returns_422(client):
    r = client.get("/api/oauth/outlook/start")
    assert r.status_code == 422 and r.json()["code"] == "outlook_disabled"


def test_outlook_send_success_payload(outlook, db):
    state, _calls = outlook
    s = db.senders.find_one({"_id": _outlook_sender(db)})
    email = OutgoingEmail("Me", "me@outlook.com", "to@x.com", "reply@x.com", "Subj", "Body", "cv.pdf", PDF)
    res = get_provider("outlook").send(s, email)
    assert res.outcome == "sent" and res.message_id is None
    m = state["last_payload"]["message"]
    assert state["last_payload"]["saveToSentItems"] is True and m["body"] == {
        "contentType": "Text",
        "content": "Body",
    }
    assert (
        m["toRecipients"][0]["emailAddress"]["address"] == "to@x.com"
        and m["replyTo"][0]["emailAddress"]["address"] == "reply@x.com"
    )
    att = m["attachments"][0]
    assert (
        att["@odata.type"] == "#microsoft.graph.fileAttachment"
        and base64.b64decode(att["contentBytes"]) == PDF
    )
    assert state["last_auth"] == "Bearer at0"  # token still valid: no refresh


def test_outlook_refresh_when_expiring_stores_rotated_token(outlook, db):
    state, _ = outlook
    s = db.senders.find_one({"_id": _outlook_sender(db, expires_in=60)})
    res = get_provider("outlook").send(
        s, OutgoingEmail("Me", "me@outlook.com", "t@x.com", None, "S", "B", "cv.pdf", PDF)
    )
    assert res.outcome == "sent" and state["last_auth"] == "Bearer at1"
    blob = json.loads(decrypt(db.senders.find_one({"_id": s["_id"]})["secret_enc"]))
    assert blob["refresh_token"] == "rt1" and blob["access_token"] == "at1"


def test_outlook_401_refresh_once_then_retry(outlook, db):
    state, _ = outlook
    state["sendmail"] = [401, 202]
    s = db.senders.find_one({"_id": _outlook_sender(db)})
    res = get_provider("outlook").send(
        s, OutgoingEmail("Me", "me@outlook.com", "t@x.com", None, "S", "B", "cv.pdf", PDF)
    )
    assert res.outcome == "sent" and state["last_auth"] == "Bearer at1"
    state["sendmail"] = [401, 401]
    res = get_provider("outlook").send(
        db.senders.find_one({"_id": s["_id"]}),
        OutgoingEmail("Me", "me@outlook.com", "t@x.com", None, "S", "B", "cv.pdf", PDF),
    )
    assert res.outcome == "auth"


def test_outlook_invalid_grant_is_auth(outlook, db):
    s = db.senders.find_one({"_id": _outlook_sender(db, refresh="revoked", expires_in=10)})
    res = get_provider("outlook").send(
        s, OutgoingEmail("Me", "me@outlook.com", "t@x.com", None, "S", "B", "cv.pdf", PDF)
    )
    assert res.outcome == "auth" and "invalid_grant" in res.detail


@pytest.mark.parametrize(
    "codes,expected", [([429], "transient"), ([503], "transient"), ([403], "quota"), ([404], "permanent")]
)
def test_outlook_status_mapping_through_send(outlook, db, codes, expected):
    state, _ = outlook
    state["sendmail"] = list(codes)
    s = db.senders.find_one({"_id": _outlook_sender(db)})
    res = get_provider("outlook").send(
        s, OutgoingEmail("Me", "me@outlook.com", "t@x.com", None, "S", "B", "cv.pdf", PDF)
    )
    assert res.outcome == expected
    if codes == [429]:
        assert res.retry_after_s == 30


def test_outlook_transport_errors(settings, db, frozen):
    settings.outlook_client_id = "c"
    s = db.senders.find_one({"_id": _outlook_sender(db)})
    mail = OutgoingEmail("Me", "me@outlook.com", "t@x.com", None, "S", "B", "cv.pdf", PDF)

    def make(exc):
        def handler(request):
            raise exc

        oauth.set_client_factory(lambda: httpx.Client(transport=httpx.MockTransport(handler)))

    try:
        make(httpx.ConnectError("refused"))
        assert get_provider("outlook").send(s, mail).outcome == "transient"
        make(httpx.ReadTimeout("slow"))
        assert get_provider("outlook").send(s, mail).outcome == "unknown"
    finally:
        oauth.set_client_factory(None)
