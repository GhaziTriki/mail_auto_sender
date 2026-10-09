from __future__ import annotations

from datetime import UTC

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

from .config import get_settings

_client = None
_db: Database | None = None
USER_ID = "local"


def current_user_id() -> str:
    """Single place that defines the user scope (D1)."""
    return USER_ID


def get_db() -> Database:
    global _client, _db
    if _db is None:
        s = get_settings()
        _client = MongoClient(s.mongo_url, tz_aware=True, tzinfo=UTC, serverSelectionTimeoutMS=10000)
        _db = _client.get_default_database(default="applymail")
    return _db


def set_db(db) -> None:
    """Tests only: inject a database object."""
    global _db
    _db = db


def ensure_indexes(db: Database | None = None) -> None:
    db = db if db is not None else get_db()
    db.senders.create_index(
        [("user_id", ASCENDING), ("provider", ASCENDING), ("address", ASCENDING)], unique=True
    )
    db.send_log.create_index([("sender_id", ASCENDING), ("at", ASCENDING)])
    db.send_log.create_index("at", expireAfterSeconds=3 * 24 * 3600)
    db.llm_keys.create_index([("user_id", ASCENDING)])
    db.contacts.create_index([("user_id", ASCENDING), ("email_norm", ASCENDING)], unique=True)
    db.runs.create_index("name_lower", unique=True)
    db.runs.create_index([("user_id", ASCENDING), ("created_at", ASCENDING)])
    db.run_items.create_index([("run_id", ASCENDING), ("status", ASCENDING), ("row_index", ASCENDING)])
    db.run_items.create_index([("run_id", ASCENDING), ("email_norm", ASCENDING)])
    db.run_items.create_index([("contact_id", ASCENDING)])
    db.run_items.create_index([("status", ASCENDING), ("lease_until", ASCENDING)])
    db.oauth_states.create_index("created_at", expireAfterSeconds=600)
    db.oauth_states.create_index("state", unique=True)
