from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

from app import clock, crypto, db as dbmod
from app.config import Settings, set_settings
from app.providers import registry
from app.providers.base import CheckResult, SendResult

REAL_MONGO = os.environ.get("MONGO_URL", "")
USING_REAL_MONGO = bool(REAL_MONGO) and "mongomock" not in REAL_MONGO and os.environ.get("USE_REAL_MONGO") == "1"


class FakeProvider:
    """Records calls; results are popped from `queue` (default: sent)."""

    name = "gmail"

    def __init__(self):
        self.calls: list = []
        self.queue: list[SendResult] = []
        self.check_result = CheckResult(True, "ok")

    def send(self, sender, email):
        self.calls.append((sender["address"], email.to, email.subject))
        if self.queue:
            return self.queue.pop(0)
        return SendResult("sent", "250 ok", message_id=f"<{uuid.uuid4()}@test>")

    def check(self, sender):
        return self.check_result


@pytest.fixture()
def settings(tmp_path):
    s = Settings(secret_key=Fernet.generate_key().decode(), data_dir=str(tmp_path / "data"), llm_fake=True,
                 send_delay_min_s=0, send_delay_max_s=0, llm_min_interval_s=0, docs_dir="")
    set_settings(s)
    crypto.reset()
    return s


@pytest.fixture()
def db(settings):
    if USING_REAL_MONGO:
        from pymongo import MongoClient
        client = MongoClient(REAL_MONGO, tz_aware=True, tzinfo=timezone.utc)
        database = client.get_default_database(default="applymail_test")
        client.drop_database(database.name)
    else:
        import mongomock
        client = mongomock.MongoClient(tz_aware=True)
        database = client["applymail_test"]
    dbmod.set_db(database)
    dbmod.ensure_indexes(database)
    yield database
    dbmod.set_db(None)


@pytest.fixture()
def frozen(db):
    clock.freeze(datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc))
    yield clock
    clock.unfreeze()


@pytest.fixture()
def provider(frozen):
    p = FakeProvider()
    registry.set_override("gmail", p)
    yield p
    registry.set_override("gmail", None)


@pytest.fixture()
def client(db, provider):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
