from __future__ import annotations

import io
import smtplib
from datetime import timedelta

import pytest
from openpyxl import Workbook

from app import clock
from app.errors import Unprocessable
from app.providers.gmail.smtp import map_smtp_error
from app.providers.outlook.graph import map_response
from app.services import filters as flt
from app.services import importer
from app.services.greeting import build_greeting
from app.services.quota import sender_quota
from app.services.recipients import extract_email
from app.services.render import render_item, validate_template
from tests.helpers import add_sender


# 1 --------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "cell,expected",
    [
        ("Jane.Doe@Example.COM", "jane.doe@example.com"),
        ("contact: bob+tag@x.org, other@y.org", "bob+tag@x.org"),
        ("<a@b.com>.", "a@b.com"),
        ("junk;;; not-an-email; @@; c@d.io;", "c@d.io"),
        ("bad@@x.com ok@fine.com", "ok@fine.com"),
        ("see me@site.com.", "me@site.com"),
        ("", None),
        (None, None),
        ("no email here", None),
    ],
)
def test_email_extraction(cell, expected):
    assert extract_email(cell) == expected


# 2 --------------------------------------------------------------------------------------------
def test_filters_and_or_empty_and_accent_search():
    rows = [
        {"_i": 0, "c": "TN", "s": "IT"},
        {"_i": 1, "c": "FR", "s": "IT"},
        {"_i": 2, "c": "TN", "s": ""},
        {"_i": 3, "c": "TN", "s": "Finance"},
    ]
    f = [{"column": "c", "values": ["TN"]}, {"column": "s", "values": ["IT", flt.EMPTY]}]
    assert [r["_i"] for r in rows if flt.row_matches(r, f)] == [0, 2]
    assert flt.row_matches(rows[1], [{"column": "c", "values": []}])  # no values selected = ignored
    assert flt.row_matches(rows[1], [])
    r = flt.unique_values(rows, "s")
    assert {v["value"]: v["count"] for v in r["values"]} == {"IT": 2, flt.EMPTY: 1, "Finance": 1}
    accent = [{"x": "Société Générale"}, {"x": "Tunisie"}]
    assert [v["value"] for v in flt.unique_values(accent, "x", q="SOCIETE")["values"]] == ["Société Générale"]
    assert [v["value"] for v in flt.unique_values(rows, "s", q="empt")["values"]] == [flt.EMPTY]


# 3 --------------------------------------------------------------------------------------------
def test_importer_encodings_delimiters_headers(settings):
    utf8 = "Nom;Email\nÉlodie;e@x.fr\n".encode()
    p = importer.parse_source(utf8, "csv")
    assert p["delimiter"] == ";" and p["rows"][0]["Nom"] == "Élodie"
    latin = "Nom,Email\nJosé,j@x.es\n".encode("latin-1")
    p = importer.parse_source(latin, "csv")
    assert p["rows"][0]["Nom"] == "José"
    bom = b"\xef\xbb\xbfA,B\n1,2\n"
    assert importer.parse_source(bom, "csv")["columns"] == ["A", "B"]
    p = importer.parse_source(b"A,,A,A\n1,2,3,4\n", "csv")
    assert p["columns"] == ["A", "column_2", "A_2", "A_3"]


def test_importer_xlsx_sheets_and_limits(settings):
    wb = Workbook()
    ws = wb.active
    ws.title = "First"
    ws.append(["Email", "N"])
    ws.append(["a@b.com", 5])
    ws2 = wb.create_sheet("Second")
    ws2.append(["Mail"])
    ws2.append(["z@z.com"])
    buf = io.BytesIO()
    wb.save(buf)
    raw = buf.getvalue()
    p = importer.parse_source(raw, "xlsx")
    assert (
        p["sheet"] == "First"
        and p["rows"][0] == {"Email": "a@b.com", "N": "5"}
        and p["sheets"] == ["First", "Second"]
    )
    assert importer.parse_source(raw, "xlsx", sheet="Second")["columns"] == ["Mail"]
    settings.max_rows = 2
    with pytest.raises(Unprocessable):
        importer.parse_source(b"A\n1\n2\n3\n", "csv")
    settings.max_source_mb = 0
    with pytest.raises(Unprocessable):
        importer.parse_source(b"A\n1\n", "csv")
    with pytest.raises(Unprocessable):
        importer.save_cv("x", "cv.pdf", b"not a pdf")
    settings.max_cv_mb = 0
    with pytest.raises(Unprocessable):
        importer.save_cv("x", "cv.pdf", b"%PDF-1.4 tiny")


# 4 --------------------------------------------------------------------------------------------
GREETING = {
    "salutation": "Dear",
    "use_honorific": True,
    "company_template": "{salutation} {company} team,",
    "human_template": "{salutation} {honorific} {name},",
    "fallback_template": "{salutation} Hiring Team,",
}


def test_greetings():
    assert build_greeting(GREETING, "company", None, "Acme", None) == "Dear Acme team,"
    assert build_greeting(GREETING, "human", "Jane Doe", None, "Ms") == "Dear Ms Jane Doe,"
    assert build_greeting(GREETING, "human", "Jane Doe", None, None) == "Dear Jane Doe,"  # no double space
    assert build_greeting({**GREETING, "use_honorific": False}, "human", "Jane", None, "Ms") == "Dear Jane,"
    assert build_greeting(GREETING, "company", None, None, None) == "Dear Hiring Team,"
    assert build_greeting(GREETING, "human", None, "Acme", None) == "Dear Hiring Team,"
    assert (
        build_greeting({**GREETING, "salutation": "Hello"}, "company", None, "Acme", None)
        == "Hello Acme team,"
    )


def test_template_validation_and_render():
    cols = ["Country"]
    assert validate_template({"subject": "S {{company}}", "body": "{{greeting}} {{col:Country}}"}, cols) == []
    assert validate_template({"subject": "S {{nope}}", "body": "x"}, cols)
    assert validate_template({"subject": "S", "body": "{{col:Missing}}"}, cols)
    assert validate_template({"subject": "", "body": "x"}, cols)
    run = {
        "greeting": GREETING,
        "template": {"subject": "Hi {{company}}", "body": "{{greeting}}|{{col:Country}}|{{email}}"},
    }
    item = {
        "kind": "company",
        "company": "Acme",
        "name": None,
        "honorific": None,
        "email_norm": "a@b.com",
        "row": {"Country": ""},
    }
    r = render_item(run, item)
    assert r["subject"] == "Hi Acme" and r["body"] == "Dear Acme team,||a@b.com"
    assert "empty:Country" in r["render_warnings"]


# 5 --------------------------------------------------------------------------------------------
def _log(db, sid, at):
    db.send_log.insert_one({"sender_id": sid, "item_id": None, "at": at})


def test_quota_rolling_window_and_resets(db, frozen):
    sid = add_sender(cap=3)
    now = clock.now()
    _log(db, sid, now - timedelta(hours=25))  # outside the window
    _log(db, sid, now - timedelta(hours=10))
    _log(db, sid, now - timedelta(hours=5))
    q = sender_quota(db.senders.find_one({"_id": sid}))
    assert q["used"] == 2 and not q["exhausted"] and q["resets_at"] is None
    _log(db, sid, now - timedelta(hours=1))
    q = sender_quota(db.senders.find_one({"_id": sid}))
    assert q["used"] == 3 and q["exhausted"]
    assert q["resets_at"] == now - timedelta(hours=10) + timedelta(hours=24)  # sorted_at[used-cap] + 24h
    clock.advance(hours=15)  # the oldest entry rolls out
    assert not sender_quota(db.senders.find_one({"_id": sid}))["exhausted"]


def test_quota_blocked_until_and_resets_max(db, frozen):
    sid = add_sender(cap=1)
    now = clock.now()
    _log(db, sid, now - timedelta(hours=2))
    db.senders.update_one({"_id": sid}, {"$set": {"blocked_until": now + timedelta(hours=30)}})
    q = sender_quota(db.senders.find_one({"_id": sid}))
    assert q["exhausted"] and q["blocked"] and q["resets_at"] == now + timedelta(hours=30)
    db.senders.update_one({"_id": sid}, {"$set": {"blocked_until": now + timedelta(hours=1), "daily_cap": 5}})
    q = sender_quota(db.senders.find_one({"_id": sid}))
    assert q["exhausted"] and q["resets_at"] == now + timedelta(hours=1)


# 16 -------------------------------------------------------------------------------------------
def test_smtp_mapping():
    auth = smtplib.SMTPAuthenticationError(535, b"5.7.8 bad")
    assert map_smtp_error(auth, "auth").outcome == "auth"
    assert (
        map_smtp_error(
            smtplib.SMTPAuthenticationError(534, b"5.7.9 Application-specific password required"), "auth"
        ).outcome
        == "auth"
    )
    r = map_smtp_error(smtplib.SMTPResponseException(550, b"5.1.1 no such user"), "rcpt")
    assert r.outcome == "permanent" and r.recipient_specific
    assert map_smtp_error(smtplib.SMTPResponseException(553, b"bad"), "rcpt").recipient_specific
    r = map_smtp_error(smtplib.SMTPResponseException(554, b"5.7.1 blocked"), "data")
    assert r.outcome == "permanent" and not r.recipient_specific
    assert (
        map_smtp_error(
            smtplib.SMTPResponseException(550, b"5.4.5 Daily user sending quota exceeded"), "data"
        ).outcome
        == "quota"
    )
    assert (
        map_smtp_error(smtplib.SMTPResponseException(452, b"Daily user sending limit"), "rcpt").outcome
        == "quota"
    )
    assert (
        map_smtp_error(smtplib.SMTPResponseException(550, b"You hit the sending limit"), "data").outcome
        == "quota"
    )
    assert map_smtp_error(smtplib.SMTPResponseException(421, b"try later"), "connect").outcome == "transient"
    assert map_smtp_error(smtplib.SMTPResponseException(451, b"temp"), "data").outcome == "transient"
    # phase logic for disconnects
    assert map_smtp_error(smtplib.SMTPServerDisconnected("gone"), "connect").outcome == "transient"
    assert map_smtp_error(smtplib.SMTPServerDisconnected("gone"), "rcpt").outcome == "transient"
    assert map_smtp_error(smtplib.SMTPServerDisconnected("gone"), "data").outcome == "unknown"
    assert map_smtp_error(TimeoutError("t"), "data").outcome == "unknown"
    assert map_smtp_error(TimeoutError("t"), "auth").outcome == "transient"
    assert map_smtp_error(ConnectionResetError("r"), "data").outcome == "unknown"


def test_graph_mapping():
    assert map_response(202, "").outcome == "sent"
    r = map_response(429, "slow down", {"Retry-After": "120"})
    assert r.outcome == "transient" and r.retry_after_s == 120
    assert map_response(503, "x").outcome == "transient"
    assert map_response(504, "x").outcome == "transient"
    assert map_response(403, '{"error":{"code":"ErrorQuotaExceeded"}}').outcome == "quota"
    assert map_response(400, "Message QUOTA exceeded").outcome == "quota"
    assert map_response(400, "bad request").outcome == "permanent"
    assert map_response(404, "nope").outcome == "permanent"
    assert map_response(401, "expired").outcome == "auth"
