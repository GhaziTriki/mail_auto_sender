from __future__ import annotations

from pymongo.errors import ServerSelectionTimeoutError

from app.worker import heartbeat
from app.worker.loop import tick


def test_heartbeat_survives_a_database_error(db, frozen, monkeypatch, caplog):
    monkeypatch.setattr(
        "app.worker.heartbeat.get_db", lambda: (_ for _ in ()).throw(ServerSelectionTimeoutError("down"))
    )
    heartbeat.beat({"recovered": 0})  # must not raise: the worker keeps running without its heartbeat
    assert "heartbeat not written" in caplog.text
    monkeypatch.undo()
    tick()
    assert heartbeat.read()["last_stats"] == {"recovered": 0, "classified_runs": 0, "send_units": 0}
