from __future__ import annotations

from pymongo.errors import ServerSelectionTimeoutError

from app.worker import heartbeat
from tests.helpers import add_sender, api_run, prepare_ready


def test_status_without_a_worker_is_degraded(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["database"]["ok"] is True and body["database"]["latency_ms"] >= 0
    assert body["worker"]["state"] == "never" and body["worker"]["ok"] is False
    assert body["api"]["version"] == "1.0.0" and body["api"]["uptime_s"] >= 0
    assert body["providers"] == {"gmail": True, "outlook": False}
    assert set(body["runs"]["by_status"]) == {
        "draft",
        "preparing",
        "ready",
        "running",
        "paused_user",
        "paused_quota",
        "paused_llm",
        "paused_errors",
        "completed",
    }
    assert body["items"] == {"pending": 0, "sending": 0, "failed": 0, "needs_review": 0, "unknown": 0}
    assert body["senders"]["total"] == 0


def test_status_follows_the_worker_heartbeat(client, frozen):
    rid = api_run(client)
    assert prepare_ready(client, rid) == "ready"  # every tick records a heartbeat
    body = client.get("/api/status").json()
    assert body["status"] == "ok"
    assert body["worker"]["state"] == "alive" and body["worker"]["age_s"] == 0
    assert body["worker"]["host"] and body["worker"]["tick_s"] == 2
    assert body["runs"]["by_status"]["ready"] == 1 and body["runs"]["active"] == 0
    assert body["items"]["pending"] == 3 and body["items"]["unknown"] == 0
    assert body["senders"] == {"total": 1, "available": 1, "exhausted": 0, "idle": 0, "auth_failed": 0}

    frozen.advance(seconds=60)
    body = client.get("/api/status").json()
    assert body["status"] == "degraded"
    assert body["worker"]["state"] == "stale" and body["worker"]["age_s"] == 60


def test_status_shows_a_failed_tick_and_the_worker_start(client, frozen):
    heartbeat.mark_started()
    frozen.advance(seconds=2)
    heartbeat.beat(None, error="RuntimeError")
    body = client.get("/api/status").json()
    assert body["status"] == "degraded"
    assert body["worker"]["state"] == "alive" and body["worker"]["last_error"] == "RuntimeError"
    assert body["worker"]["started_at"] == "2026-10-07T12:00:00+00:00"
    add_sender(status="auth_failed")
    assert client.get("/api/status").json()["senders"]["auth_failed"] == 1


def test_status_reports_a_database_failure(client, monkeypatch):
    class Broken:
        name = "applymail"

        def command(self, *_):
            raise ServerSelectionTimeoutError("down")

    monkeypatch.setattr("app.api.status.get_db", Broken)
    r = client.get("/api/status")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "error"
    assert body["database"] == {
        "ok": False,
        "name": None,
        "latency_ms": None,
        "error": "ServerSelectionTimeoutError",
    }
    assert body["worker"]["state"] == "unknown"
