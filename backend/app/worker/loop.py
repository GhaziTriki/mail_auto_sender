"""Worker loop (spec 9.5)."""
from __future__ import annotations

import time

from .. import clock
from ..config import get_settings
from ..db import get_db
from ..logging import get_logger
from .classify_step import classify_unit
from .recovery import recover_expired_leases
from .send_step import send_unit

log = get_logger("worker")


def tick() -> dict:
    """One worker iteration. Returns counters (used by tests)."""
    db = get_db()
    stats = {"recovered": recover_expired_leases(), "classified_runs": 0, "send_units": 0}
    for run in list(db.runs.find({"status": "preparing"})):
        try:
            classify_unit(run)
            stats["classified_runs"] += 1
        except Exception:  # noqa: BLE001
            log.exception("classification unit failed", extra={"run_id": run["_id"]})
    now = clock.now()
    for run in list(db.runs.find({"status": "running", "$or": [{"next_send_at": None}, {"next_send_at": {"$lte": now}}]})):
        try:
            send_unit(run)
            stats["send_units"] += 1
        except Exception:  # noqa: BLE001
            log.exception("send unit failed", extra={"run_id": run["_id"]})
    return stats


def run_forever() -> None:
    tick_s = get_settings().worker_tick_s
    log.info("worker started")
    while True:
        try:
            tick()
        except Exception:  # noqa: BLE001
            log.exception("worker tick failed")
        time.sleep(tick_s)
