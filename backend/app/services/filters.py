"""Filters over parsed rows (spec 8.2)."""
from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Iterable

from .importer import read_parsed

EMPTY = "__EMPTY__"


def fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).casefold()


def cell_value(row: dict, column: str) -> str:
    v = (row.get(column) or "").strip()
    return v if v else EMPTY


def unique_values(rows: Iterable[dict], column: str, q: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(int(limit), 200))
    counts: Counter = Counter(cell_value(r, column) for r in rows)
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))
    if q:
        needle = fold(q)
        label_empty = fold("(empty)")
        items = [(v, c) for v, c in items if needle in (label_empty if v == EMPTY else fold(v))]
    total = len(items)
    page = items[offset: offset + limit]
    return {"total": total, "values": [{"value": v, "count": c} for v, c in page], "all_values": [v for v, _ in items] if total <= 5000 else None}


def row_matches(row: dict, filters: list[dict]) -> bool:
    for f in filters:
        vals = f.get("values") or []
        if not vals:
            continue
        if cell_value(row, f["column"]) not in set(vals):
            return False
    return True


def select_rows(run_id, filters: list[dict]) -> list[dict]:
    return [r for r in read_parsed(run_id) if row_matches(r, filters or [])]
