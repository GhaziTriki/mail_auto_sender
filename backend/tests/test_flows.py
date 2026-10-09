from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from app import clock
from app.db import get_db
from app.errors import Unprocessable
from app.providers.base import SendResult
from app.worker.loop import tick
from app.worker.recovery import recover_expired_leases
from app.worker.send_step import send_unit
from tests.helpers import CSV_BASIC, add_sender, api_run, drain, items, prepare_ready

HEADER = "Company,First,Last,Email,Country\n"


def one(email, company="Acme"):
    return HEADER + f"{company},Jane,Doe,{email},TN\n"


def many(n, prefix="p"):
    return HEADER + "".join(f"Co{i},,,{prefix}{i}.x@co{i}.com,TN\n" for i in range(n))


def start(client, rid):
    r = client.post(f"/api/runs/{rid}/start")
    assert r.status_code == 200, r.text
    return r.json()


def contact(email):
    return get_db().contacts.find_one({"email_norm": email})


def ready_started(client, name, csv, **kw):
    rid = api_run(client, name, csv, **kw)
    assert prepare_ready(client, rid) == "ready"
    start(client, rid)
    return rid


# ------------------------------------------------------------------ prepare / classification
def test_prepare_statuses_and_greetings(client, provider):
    rid = api_run(client, "prep", CSV_BASIC)
    assert prepare_ready(client, rid) == "ready"
    by_row = {i["row_index"]: i for i in items(client, rid)}
    assert by_row[0]["status"] == "pending" and by_row[0]["greeting_text"] == "Dear Jane Doe,"
    assert by_row[1]["status"] == "pending" and by_row[1]["kind"] == "company"
    assert by_row[1]["greeting_text"] == "Dear Beta team,"
    assert by_row[3]["status"] == "no_contact" and by_row[3]["email_norm"] is None
    assert by_row[4]["status"] == "skipped_duplicate" and by_row[4]["duplicate_reason"] == "duplicate_in_run"
    assert by_row[4]["duplicate_of_item_id"] == by_row[0]["id"]


def test_prepare_preconditions_422(client):
    rid = client.post("/api/runs", json={"name": "empty"}).json()["id"]
    r = client.post(f"/api/runs/{rid}/prepare")
    assert r.status_code == 422 and r.json()["code"] == "prepare_preconditions"
    assert "source_file" in r.json()["fields"]


def test_duplicate_run_name_conflict(client):
    client.post("/api/runs", json={"name": "Same"})
    r = client.post("/api/runs", json={"name": "same"})
    assert r.status_code == 409


def test_filters_preview_and_prepare_respects_filters(client):
    rid = api_run(client, "flt", CSV_BASIC)
    r = client.get(f"/api/runs/{rid}/columns/Country/values").json()
    assert {v["value"]: v["count"] for v in r["values"]} == {"TN": 4, "FR": 1}
    r = client.post(
        f"/api/runs/{rid}/filters/preview", json={"filters": [{"column": "Country", "values": ["FR"]}]}
    )
    assert r.json() == {"matching_rows": 1, "with_valid_email": 1}
    client.patch(f"/api/runs/{rid}", json={"filters": [{"column": "Country", "values": ["FR"]}]})
    prepare_ready(client, rid)
    assert [i["email_norm"] for i in items(client, rid)] == ["info@beta.com"]


def test_llm_fake_classification_with_honorific(client, provider):
    csv = HEADER + "Acme,,,sarah.smith@acme.com,TN\nAcme,,,info@acme.com,TN\n"
    rid = api_run(client, "llmfake", csv, mode="llm")
    assert prepare_ready(client, rid) == "ready"
    it = {i["email_norm"]: i for i in items(client, rid)}
    assert it["sarah.smith@acme.com"]["kind"] == "human" and it["sarah.smith@acme.com"]["decided_by"] == "llm"
    assert it["sarah.smith@acme.com"]["greeting_text"] == "Dear Ms Sarah Smith,"
    assert it["info@acme.com"]["kind"] == "company"


def test_rerender_keeps_edited_items(client, provider):
    rid = api_run(client, "rr", many(2))
    prepare_ready(client, rid)
    first = items(client, rid)[0]
    r = client.patch(f"/api/items/{first['id']}", json={"subject": "Custom subject"})
    assert r.json()["edited"] is True
    client.patch(
        f"/api/runs/{rid}", json={"template": {"subject": "New {{company}}", "body": "{{greeting}} v2"}}
    )
    got = items(client, rid)
    assert got[0]["subject"] == "Custom subject"
    assert got[1]["subject"] == "New Co1" and got[1]["body"].endswith("v2")


# ------------------------------------------------------------------ 6, 7 send-once and locking
def test_send_once_two_runs_sequential(client, provider):
    a = api_run(client, "A", one("same@x.com"))
    b = api_run(client, "B", one("same@x.com"))
    prepare_ready(client, a)
    prepare_ready(client, b)  # both pending: lock not yet taken
    assert items(client, b)[0]["status"] == "pending"
    start(client, a)
    start(client, b)
    drain(client, a)
    drain(client, b)
    assert len(provider.calls) == 1
    assert items(client, a)[0]["status"] == "sent"
    nb = items(client, b)[0]
    assert nb["status"] == "needs_review" and nb["duplicate_reason"] == "already_sent"
    assert nb["duplicate_of_item_id"] == items(client, a)[0]["id"]


def test_send_once_threaded_race(client, provider):
    runs = []
    for n in range(4):
        rid = api_run(client, f"race{n}", one("racer@x.com"))
        prepare_ready(client, rid)
        runs.append(rid)
    for rid in runs:
        start(client, rid)
    docs = [get_db().runs.find_one({"_id": __import__("bson").ObjectId(r)}) for r in runs]
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(send_unit, docs))
    assert len(provider.calls) == 1
    sts = sorted(items(client, r)[0]["status"] for r in runs)
    assert sts == ["needs_review", "needs_review", "needs_review", "sent"]


@pytest.mark.parametrize(
    "outcome,expect_status,lock_kept",
    [
        (SendResult("sent", "ok", message_id="<m@x>"), "sent", True),
        (SendResult("unknown", "lost"), "unknown", True),
        (SendResult("permanent", "bad", recipient_specific=True), "failed", False),
        (SendResult("transient", "421"), "pending", False),
        (SendResult("auth", "535"), "pending", False),
        (SendResult("quota", "5.4.5"), "pending", False),
    ],
)
def test_lock_release_and_keep(client, provider, outcome, expect_status, lock_kept):
    email = f"lock{expect_status}{lock_kept}{outcome.outcome}@x.com".lower()
    rid = ready_started(client, f"lk-{outcome.outcome}", one(email))
    provider.queue.append(outcome)
    tick()
    it = items(client, rid)[0]
    assert it["status"] == expect_status
    assert (contact(email)["sent_item_id"] is not None) is lock_kept
    if lock_kept:
        assert contact(email)["sent_info"]["uncertain"] is (outcome.outcome == "unknown")
        assert get_db().send_log.count_documents({}) == 1  # kept for sent/unknown
    else:
        assert get_db().send_log.count_documents({}) == 0  # deleted otherwise
    if outcome.outcome == "auth":
        assert get_db().senders.find_one()["status"] == "auth_failed"
    if outcome.outcome == "quota":
        assert get_db().senders.find_one()["blocked_until"] > clock.now()
    assert it["attempt_count"] == (1 if outcome.outcome == "transient" else 0)


def test_override_duplicate_bypasses_lock(client, provider):
    a = ready_started(client, "ovA", one("ov@x.com"))
    drain(client, a)
    b = api_run(client, "ovB", one("ov@x.com"))
    prepare_ready(client, b)
    it = items(client, b)[0]
    assert it["status"] == "needs_review" and it["prior_send"]["run_name"] == "ovA"
    start(client, b)  # auto: allowed, stays unsent
    drain(client, b)
    assert len(provider.calls) == 1
    r = client.post(f"/api/runs/{b}/items/bulk", json={"action": "resend", "item_ids": [it["id"]]})
    assert r.json()["changed"] == 1
    drain(client, b)
    assert len(provider.calls) == 2 and items(client, b)[0]["status"] == "sent"
    assert contact("ov@x.com")["sent_item_id"] == __import__("bson").ObjectId(items(client, a)[0]["id"])


# ------------------------------------------------------------------ 8 recovery
def test_expired_lease_becomes_unknown_never_resent(client, provider):
    rid = ready_started(client, "crash", one("crash@x.com"))
    it = get_db().run_items.find_one({"run_id": __import__("bson").ObjectId(rid)})
    get_db().contacts.update_one({"_id": it["contact_id"]}, {"$set": {"sent_item_id": it["_id"]}})
    get_db().run_items.update_one(
        {"_id": it["_id"]},
        {
            "$set": {
                "status": "sending",
                "lease_until": clock.now() - timedelta(seconds=5),
                "sender_address": "a@gmail.com",
            }
        },
    )
    assert recover_expired_leases() == 1
    cur = items(client, rid)[0]
    assert cur["status"] == "unknown" and cur["attempts"][-1]["detail"] == "lease expired"
    assert contact("crash@x.com")["sent_info"]["uncertain"] is True
    for _ in range(5):
        tick()
        clock.advance(seconds=5)
    assert provider.calls == []  # never auto-resent
    assert get_db().runs.find_one()["status"] == "completed"


# ------------------------------------------------------------------ 9 sender rotation
def test_fill_first_rotation_and_paused_quota(client, provider):
    idle = add_sender("idle@gmail.com", status="idle")
    a = add_sender("a@gmail.com", cap=2)
    rid = api_run(client, "rot", many(5), sender_ids=[idle, a])
    prepare_ready(client, rid)
    start(client, rid)
    assert drain(client, rid) == "paused_quota"
    sent = items(client, rid, "sent")
    assert len(sent) == 2 and {i["sender_address"] for i in sent} == {"a@gmail.com"}  # idle never used
    run = client.get(f"/api/runs/{rid}").json()
    assert run["pause_detail"]["senders"][0]["reason"] == "idle"
    assert {s["reason"] for s in run["pause_detail"]["senders"]} == {"idle", "cap"}
    for _ in range(3):  # no auto-resume
        tick()
        clock.advance(minutes=1)
    assert client.get(f"/api/runs/{rid}").json()["status"] == "paused_quota"
    r = client.post(f"/api/runs/{rid}/resume")
    assert (
        r.status_code == 409 and r.json()["code"] == "no_sender_available" and r.json()["earliest_reset_at"]
    )
    b = add_sender("b@gmail.com", cap=10)
    r = client.patch(f"/api/runs/{rid}", json={"sender_ids": [str(idle), str(a), str(b)]})
    assert r.status_code == 200
    assert client.post(f"/api/runs/{rid}/resume").json()["status"] == "running"
    assert drain(client, rid) == "completed"
    by_sender = {}
    for i in items(client, rid, "sent"):
        by_sender[i["sender_address"]] = by_sender.get(i["sender_address"], 0) + 1
    assert by_sender == {"a@gmail.com": 2, "b@gmail.com": 3}


def test_quota_shared_across_runs_and_survives_run_deletion(client, provider):
    a = add_sender("shared@gmail.com", cap=2)
    r1 = ready_started(client, "q1", many(2, "q1"), sender_ids=[a])
    assert drain(client, r1) == "completed"
    assert client.delete(f"/api/runs/{r1}").status_code == 200
    r2 = api_run(client, "q2", many(2, "q2"), sender_ids=[a])
    prepare_ready(client, r2)
    start(client, r2)
    assert drain(client, r2) == "paused_quota"
    assert len(provider.calls) == 2


# ------------------------------------------------------------------ 10 retries / breaker
def test_retry_schedule_then_failed(client, provider):
    rid = ready_started(client, "retry", one("retry@x.com"))
    provider.queue += [SendResult("transient", "421")] * 3
    tick()
    it = items(client, rid)[0]
    assert it["status"] == "pending" and it["attempt_count"] == 1
    assert clock.as_utc(
        __import__("dateutil.parser", fromlist=["x"]).isoparse(it["next_attempt_at"])
    ) == clock.now() + timedelta(seconds=60)
    tick()  # not due yet: nothing sent
    assert len(provider.calls) == 1
    clock.advance(seconds=61)
    tick()
    it = items(client, rid)[0]
    assert it["attempt_count"] == 2 and it["status"] == "pending"
    clock.advance(seconds=301)
    tick()
    it = items(client, rid)[0]
    assert it["status"] == "failed" and it["attempt_count"] == 3 and len(provider.calls) == 3
    assert get_db().runs.find_one()["consecutive_failures"] == 1
    assert contact("retry@x.com")["sent_item_id"] is None


def test_breaker_pauses_and_ignores_recipient_specific(client, provider):
    rid = ready_started(client, "brk", many(5, "b"), extra=None)
    client.patch(f"/api/runs/{rid}", json={"breaker_threshold": 2})
    provider.queue += [SendResult("permanent", "boom")] * 5
    assert drain(client, rid) == "paused_errors"
    assert len(items(client, rid, "failed")) == 2
    assert client.get(f"/api/runs/{rid}").json()["pause_detail"]["last_errors"]
    r = client.post(f"/api/runs/{rid}/resume")
    assert r.json()["status"] == "running" and r.json()["consecutive_failures"] == 0

    rid2 = ready_started(client, "brk2", many(5, "c"))
    client.patch(f"/api/runs/{rid2}", json={"breaker_threshold": 2})
    provider.queue += [SendResult("permanent", "bad address", recipient_specific=True)] * 5
    assert drain(client, rid2) == "completed"
    assert len(items(client, rid2, "failed")) == 5


def test_auth_failed_sender_skipped_item_not_failed(client, provider):
    s1, s2 = add_sender("one@gmail.com"), add_sender("two@gmail.com")
    rid = ready_started(client, "authfail", many(2, "af"), sender_ids=[s1, s2])
    provider.queue.append(SendResult("auth", "535 bad"))
    assert drain(client, rid) == "completed"
    assert get_db().senders.find_one({"_id": s1})["status"] == "auth_failed"
    its = items(client, rid)
    assert [i["status"] for i in its] == ["sent", "sent"] and all(
        i["sender_address"] == "two@gmail.com" for i in its
    )
    assert its[0]["attempts"][0]["outcome"] == "auth" and its[0]["attempt_count"] == 0


# ------------------------------------------------------------------ 11 LLM
def _llm_run(client, name, csv, n_keys=2):
    key_ids = []
    for n in range(n_keys):
        r = client.post("/api/llm-keys", json={"label": f"k{n}", "api_key": f"AIzaKEY{n}" + "x" * 20})
        key_ids.append(r.json()["id"])
    rid = api_run(client, name, csv, mode="llm", extra={"llm_key_ids": key_ids})
    return rid, key_ids


def test_llm_partial_results_retried_then_rules_fallback(client, provider, settings, monkeypatch):
    settings.llm_fake = False
    from app.llm import gemini

    calls = []

    def fake_call(api_key, payload):
        calls.append(len(payload))
        ids = [p["id"] for p in payload]
        if len(calls) == 1:  # return only the first id, plus junk entries
            return [
                {"id": ids[0], "kind": "company", "name": None, "company": "Z", "honorific": None},
                {"id": ids[1], "kind": "bogus"},
                "junk",
                {"id": "unknown-id", "kind": "human"},
            ]
        return []  # always empty afterwards -> fallback to rules

    monkeypatch.setattr(gemini, "call_gemini", fake_call)
    rid, _ = _llm_run(client, "llmpartial", many(4, "l"))
    assert prepare_ready(client, rid) == "ready"
    its = items(client, rid)
    assert its[0]["decided_by"] == "llm" and its[0]["company"] == "Z"
    for i in its[1:]:
        assert i["decided_by"] == "rules" and "llm_failed" in i["warnings"]
    assert calls[0] == 4 and calls[1] < calls[0]  # retries use a smaller batch


def test_llm_key_rotation_on_429_and_paused_llm_and_switch_to_rules(client, provider, settings, monkeypatch):
    settings.llm_fake = False
    from app.llm import gemini
    from app.llm.gemini import LLMError

    mode = {"fail": "quota"}
    used = []

    def fake_call(api_key, payload):
        used.append(api_key)
        if api_key.startswith("AIzaKEY0"):
            raise LLMError("quota", "429 RESOURCE_EXHAUSTED")
        if mode["fail"] == "quota":
            raise LLMError("quota", "429 RESOURCE_EXHAUSTED")
        return [
            {"id": p["id"], "kind": "company", "name": None, "company": "C", "honorific": None}
            for p in payload
        ]

    monkeypatch.setattr(gemini, "call_gemini", fake_call)
    rid, keys = _llm_run(client, "llmrot", many(2, "r"))
    client.post(f"/api/runs/{rid}/prepare")
    for _ in range(3):
        tick()
    run = client.get(f"/api/runs/{rid}").json()
    assert run["status"] == "paused_llm" and len(run["pause_detail"]["keys"]) == 2
    assert run["pause_detail"]["earliest_reset_at"]
    ks = {k["id"]: k for k in client.get("/api/llm-keys").json()}
    assert all(k["quota"]["exhausted"] for k in ks.values()) and used[:2] == [used[0], used[1]]
    r = client.post(f"/api/runs/{rid}/resume")
    assert r.status_code == 409 and r.json()["code"] == "no_key_available"
    # switch to rules, resume, continue
    assert client.patch(f"/api/runs/{rid}", json={"mode": "rules"}).status_code == 200
    assert client.post(f"/api/runs/{rid}/resume").json()["status"] == "preparing"
    for _ in range(3):
        tick()
    assert client.get(f"/api/runs/{rid}").json()["status"] == "ready"
    assert all(i["decided_by"] == "rules" for i in items(client, rid))
    # a second run on a new Pacific day: key 1 works after reset
    clock.advance(hours=25)
    mode["fail"] = "none"
    rid2, _ = _llm_run(client, "llmrot2", many(2, "s"), n_keys=0)
    client.patch(f"/api/runs/{rid2}", json={"llm_key_ids": [keys[1]]})
    assert prepare_ready(client, rid2) == "ready"
    assert all(i["decided_by"] == "llm" for i in items(client, rid2))


def test_llm_auth_error_marks_key_and_transient_keeps_state(client, provider, settings, monkeypatch):
    settings.llm_fake = False
    from app.llm import gemini
    from app.llm.gemini import LLMError

    state = {"n": 0}

    def fake_call(api_key, payload):
        state["n"] += 1
        if api_key.startswith("AIzaKEY0"):
            raise LLMError("auth", "400 API key not valid")
        if state["n"] == 2:
            raise LLMError("transient", "503")
        return [
            {"id": p["id"], "kind": "company", "name": None, "company": "C", "honorific": None}
            for p in payload
        ]

    monkeypatch.setattr(gemini, "call_gemini", fake_call)
    rid, keys = _llm_run(client, "llmauth", many(2, "t"))
    assert prepare_ready(client, rid) == "ready"
    ks = {k["id"]: k for k in client.get("/api/llm-keys").json()}
    assert ks[keys[0]]["status"] == "auth_failed" and ks[keys[1]]["status"] == "active"
    assert all(i["decided_by"] == "llm" for i in items(client, rid))


# ------------------------------------------------------------------ 12 dedup
def test_manual_run_start_blocked_until_duplicates_resolved(client, provider):
    a = ready_started(client, "dA", one("dup@x.com"))
    drain(client, a)
    b = api_run(client, "dB", one("dup@x.com"), approval="manual")
    prepare_ready(client, b)
    r = client.post(f"/api/runs/{b}/start")
    assert r.status_code == 409 and r.json()["code"] == "needs_review_unresolved"
    nr = items(client, b, "needs_review")[0]
    client.post(f"/api/runs/{b}/items/bulk", json={"action": "skip", "item_ids": [nr["id"]]})
    assert items(client, b)[0]["status"] == "skipped_duplicate"
    assert client.post(f"/api/runs/{b}/start").status_code == 200
    drain(client, b)
    assert len(provider.calls) == 1  # skip is final


# ------------------------------------------------------------------ manual approval
def test_manual_approval_flow_next_and_test_send(client, provider):
    rid = api_run(client, "man", many(3, "m"), approval="manual")
    prepare_ready(client, rid)
    start(client, rid)
    for _ in range(3):
        tick()
    assert provider.calls == []  # nothing without approval
    nxt = client.get(f"/api/runs/{rid}/next").json()
    assert (
        nxt["item"]["contact_line"]["email"] == "m0.x@co0.com" and nxt["sender"]["address"] == "a@gmail.com"
    )
    t = client.post(f"/api/runs/{rid}/test-send", json={}).json()
    assert t["ok"] and provider.calls[-1][1] == "a@gmail.com" and provider.calls[-1][2].startswith("[TEST] ")
    assert items(client, rid, "pending")[0]["status"] == "pending"
    assert get_db().send_log.count_documents({}) == 0 and contact("m0.x@co0.com")["sent_item_id"] is None
    provider.calls.clear()
    client.post(f"/api/runs/{rid}/items/bulk", json={"action": "approve", "item_ids": [nxt["item"]["id"]]})
    tick()
    assert [c[1] for c in provider.calls] == ["m0.x@co0.com"]
    tick()
    assert len(provider.calls) == 1  # next one is not approved
    client.post(f"/api/runs/{rid}/approve-all")
    assert drain(client, rid) == "completed" and len(provider.calls) == 3


# ------------------------------------------------------------------ 13 reruns
def test_rerun_failed_mark_sent_and_completed_reopens(client, provider):
    rid = ready_started(client, "rr1", many(3, "z"))
    provider.queue += [SendResult("permanent", "bad", recipient_specific=True), SendResult("unknown", "lost")]
    assert drain(client, rid) == "completed"
    assert items(client, rid, "failed")
    unknown = items(client, rid, "unknown")[0]
    r = client.post(f"/api/runs/{rid}/items/bulk", json={"action": "mark_sent", "item_ids": [unknown["id"]]})
    assert r.json()["changed"] == 1
    cur = items(client, rid, "sent")
    assert len(cur) == 2 and contact(unknown["email_norm"])["sent_info"]["uncertain"] is False
    r = client.post(f"/api/runs/{rid}/items/bulk", json={"action": "rerun", "status_filter": "failed"})
    assert r.json()["changed"] == 1
    assert client.get(f"/api/runs/{rid}").json()["status"] == "running"  # completed -> running
    assert drain(client, rid) == "completed"
    assert len(items(client, rid, "sent")) == 3

    rid2 = ready_started(client, "rr2", one("unk@x.com"))
    provider.queue.append(SendResult("unknown", "lost"))
    drain(client, rid2)
    u = items(client, rid2, "unknown")[0]
    client.post(f"/api/runs/{rid2}/items/bulk", json={"action": "rerun", "item_ids": [u["id"]]})
    assert contact("unk@x.com")["sent_item_id"] is None
    assert drain(client, rid2) == "completed" and items(client, rid2)[0]["status"] == "sent"


# ------------------------------------------------------------------ 14 locks
def test_config_lock_and_delete_keeps_contact_lock(client, provider):
    rid = ready_started(client, "cfg", one("cfg@x.com"))
    drain(client, rid)
    r = client.patch(f"/api/runs/{rid}", json={"template": {"subject": "x", "body": "y"}})
    assert r.status_code == 409 and r.json()["code"] == "config_locked"
    r = client.post(f"/api/runs/{rid}/cv", files={"file": ("cv.pdf", b"%PDF-1", "application/pdf")})
    assert r.status_code == 409 and r.json()["code"] == "config_locked"
    assert (
        client.patch(f"/api/runs/{rid}", json={"approval": "manual"}).status_code == 200
    )  # controls stay allowed
    assert client.delete(f"/api/runs/{rid}").status_code == 200
    c = contact("cfg@x.com")
    assert c["sent_item_id"] is not None and c["sent_info"]["run_name"] == "cfg"
    r2 = api_run(client, "cfg-again", one("cfg@x.com"))
    prepare_ready(client, r2)
    assert items(client, r2)[0]["status"] == "needs_review"


def test_unprepare_and_status_guards(client, provider):
    rid = api_run(client, "unp", many(2, "u"))
    assert client.post(f"/api/runs/{rid}/start").status_code == 409
    prepare_ready(client, rid)
    assert client.post(f"/api/runs/{rid}/unprepare").json()["status"] == "draft"
    assert items(client, rid) == []
    prepare_ready(client, rid)
    start(client, rid)
    assert client.post(f"/api/runs/{rid}/pause").json()["status"] == "paused_user"
    tick()
    assert provider.calls == []
    assert client.post(f"/api/runs/{rid}/resume").json()["status"] == "running"
    assert client.post(f"/api/runs/{rid}/resume").status_code == 409


# ------------------------------------------------------------------ 15 secrets
def test_secrets_never_in_responses_or_logs(client, provider, caplog):
    from app.logging import JsonFormatter

    secret_pw, secret_key = "SUPERSECRETPASSWORD12", "AIzaSyFAKEKEYFAKEKEYFAKEKEY1234"
    caplog.set_level(logging.DEBUG)
    r = client.post(
        "/api/senders/gmail",
        json={"address": "leak@gmail.com", "display_name": "L", "app_password": secret_pw, "daily_cap": 10},
    )
    assert r.status_code == 200 and r.json()["has_secret"] is True
    sid = r.json()["id"]
    k = client.post("/api/llm-keys", json={"label": "k", "api_key": secret_key}).json()
    texts = [r.text, str(k)]
    texts.append(client.get("/api/senders").text)
    texts.append(client.get("/api/llm-keys").text)
    texts.append(client.patch(f"/api/senders/{sid}", json={"app_password": secret_pw + "2"}).text)
    texts.append(client.post(f"/api/senders/{sid}/check").text)
    texts.append(client.post(f"/api/llm-keys/{k['id']}/check").text)
    texts.append(client.get("/api/dashboard/summary").text)
    texts.append(client.get("/api/config").text)
    rid = api_run(client, "leak", many(2, "k"), sender_ids=[__import__("bson").ObjectId(sid)])
    prepare_ready(client, rid)
    start(client, rid)
    drain(client, rid)
    texts.append(client.get(f"/api/runs/{rid}").text)
    texts.append(client.get(f"/api/runs/{rid}/items").text)
    texts.append(client.get(f"/api/runs/{rid}/export.csv").text)
    texts.append(client.get(f"/api/runs/{rid}/next").text)
    logs = JsonFormatter()
    texts += [logs.format(rec) for rec in caplog.records]
    texts.append(caplog.text)
    blob = "\n".join(texts)
    for s in (secret_pw, secret_pw + "2", secret_key):
        assert s not in blob
    assert "secret_enc" not in blob
    # redaction helper itself
    from app.logging import redact_text

    assert secret_key not in redact_text(f"error with key {secret_key} and app_password={secret_pw}")
    assert secret_pw not in redact_text(f"app_password={secret_pw}")


def test_secret_key_required_to_start(settings, db):
    from app.crypto import reset, validate_secret_key
    from app.errors import ConfigError

    reset()
    with pytest.raises(ConfigError):
        validate_secret_key("")
    with pytest.raises(ConfigError):
        validate_secret_key("not-a-key")


def test_header_injection_rejected(client, provider):
    rid = ready_started(client, "inj", one("inj@x.com"))
    it = items(client, rid)[0]
    r = client.patch(f"/api/items/{it['id']}", json={"subject": "a\r\nBcc: evil@x.com"})
    assert r.status_code == 422
    from app.providers.base import OutgoingEmail
    from app.providers.message import build_message

    with pytest.raises(Unprocessable):
        build_message(
            OutgoingEmail("N", "a@b.com", "x@y.com\nBcc: e@e.com", None, "s", "b", "cv.pdf", b"%PDF")
        )
