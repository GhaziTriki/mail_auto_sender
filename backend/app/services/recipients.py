"""Recipient extraction (spec 8.3)."""
from __future__ import annotations

import re

from email_validator import EmailNotValidError, validate_email

CANDIDATE_RE = re.compile(r"[^\s,;<>()\[\]\"']+@[^\s,;<>()\[\]\"']+")


def extract_email(cell: str | None) -> str | None:
    """Return the normalised (lowercase) first valid address in the cell, else None."""
    if not cell:
        return None
    for m in CANDIDATE_RE.finditer(cell):
        cand = m.group(0).rstrip(".,;:")
        if "\r" in cand or "\n" in cand:
            continue
        try:
            v = validate_email(cand, check_deliverability=False)
        except EmailNotValidError:
            continue
        return v.normalized.lower()
    return None


def has_crlf(*values) -> bool:
    return any(isinstance(v, str) and ("\r" in v or "\n" in v) for v in values)
