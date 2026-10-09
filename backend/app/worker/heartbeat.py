"""Worker heartbeat: one document the API reads to tell whether the worker is alive."""

from __future__ import annotations

import os
import socket

from .. import clock
from ..config import get_settings
from ..db import get_db
from ..logging import get_logger

log = get_logger("worker.heartbeat")
DOC_ID = "worker"


def mark_started() -> None:
    """Record the start of the worker process."""
    now = clock.now()
    _write({"started_at": now, "last_tick_at": now, "last_error": None, "last_stats": None})


def beat(stats: dict | None, error: str | None = None) -> None:
    """Record the end of a tick, successful or not. `error` is an exception class name, never its text."""
    _write({"last_tick_at": clock.now(), "last_error": error, "last_stats": stats})


def read() -> dict | None:
    return get_db().worker_status.find_one({"_id": DOC_ID})


def _write(fields: dict) -> None:
    fields.update({"host": socket.gethostname(), "pid": os.getpid(), "tick_s": get_settings().worker_tick_s})
    try:
        get_db().worker_status.update_one({"_id": DOC_ID}, {"$set": fields}, upsert=True)
    except Exception:
        log.exception("heartbeat not written")
