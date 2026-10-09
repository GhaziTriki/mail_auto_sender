"""Send-once lock (spec 7). Single-document atomic ops only."""

from __future__ import annotations

from ..db import get_db


def acquire(contact_id, item_id) -> tuple[bool, object | None]:
    """Try to take the lock. Returns (acquired, holder_item_id_if_lost)."""
    db = get_db()
    got = db.contacts.find_one_and_update(
        {"_id": contact_id, "sent_item_id": None}, {"$set": {"sent_item_id": item_id}}
    )
    if got is not None:
        return True, None
    c = db.contacts.find_one({"_id": contact_id})
    if c is not None and c.get("sent_item_id") == item_id:
        return True, None
    return False, (c or {}).get("sent_item_id")


def release(contact_id, item_id) -> None:
    get_db().contacts.update_one(
        {"_id": contact_id, "sent_item_id": item_id}, {"$set": {"sent_item_id": None}}
    )


def set_sent_info(contact_id, info: dict) -> None:
    get_db().contacts.update_one({"_id": contact_id}, {"$set": {"sent_info": info}})


def mark_uncertain(contact_id) -> None:
    get_db().contacts.update_one(
        {"_id": contact_id, "sent_info": {"$ne": None}}, {"$set": {"sent_info.uncertain": True}}
    )
