from __future__ import annotations


from app import clock
from app.crypto import encrypt
from app.db import get_db
from app.worker.loop import tick

CSV_BASIC = (
    "Company,First,Last,Email,Country\n"
    "Acme,Jane,Doe,jane.doe@acme.com,TN\n"
    "Beta,,,info@beta.com,FR\n"
    "Gamma,Karim,B,karim.b@gamma.tn,TN\n"
    "Delta,,,,TN\n"
    "Acme2,Jane,Doe,JANE.DOE@acme.com,TN\n"
)
PDF = b"%PDF-1.4\n%fake\n"


def add_sender(address="a@gmail.com", cap=100, status="active", provider="gmail"):
    now = clock.now()
    existing = get_db().senders.find_one({"user_id": "local", "provider": provider, "address": address})
    if existing:
        return existing["_id"]
    return get_db().senders.insert_one({
        "user_id": "local", "provider": provider, "address": address, "display_name": "Tester",
        "secret_enc": encrypt("pw"), "daily_cap": cap, "status": status, "blocked_until": None, "last_error": None,
        "deleted_at": None, "created_at": now, "updated_at": now}).inserted_id


def api_run(client, name="r1", csv=CSV_BASIC, sender_ids=None, approval="auto", mode="rules", extra=None):
    r = client.post("/api/runs", json={"name": name})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    r = client.post(f"/api/runs/{rid}/source", files={"file": ("c.csv", csv.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/runs/{rid}/cv", files={"file": ("cv.pdf", PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    patch = {"recipient": {"email_column": "Email", "human_name_columns": ["First", "Last"],
                           "company_name_columns": ["Company"]},
             "mode": mode, "approval": approval,
             "sender_ids": [str(s) for s in (sender_ids or [add_sender()])],
             "template": {"subject": "Hello {{company}}", "body": "{{greeting}}\n\nCV attached. {{col:Country}}"}}
    patch.update(extra or {})
    r = client.patch(f"/api/runs/{rid}", json=patch)
    assert r.status_code == 200, r.text
    return rid


def prepare_ready(client, rid):
    r = client.post(f"/api/runs/{rid}/prepare")
    assert r.status_code == 200, r.text
    for _ in range(50):
        tick()
        st = client.get(f"/api/runs/{rid}").json()["status"]
        if st not in ("preparing",):
            return st
    raise AssertionError("never left preparing")


def drain(client, rid, max_ticks=100):
    for _ in range(max_ticks):
        tick()
        clock.advance(seconds=1)
        st = client.get(f"/api/runs/{rid}").json()["status"]
        if st != "running":
            return st
    return "running"


def items(client, rid, status=None):
    url = f"/api/runs/{rid}/items?page_size=200" + (f"&status={status}" if status else "")
    return client.get(url).json()["items"]
