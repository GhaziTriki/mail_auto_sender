"""Rules-mode classification (spec 8.5)."""
from __future__ import annotations

import re

FREE_MAIL = {"gmail", "outlook", "hotmail", "yahoo", "icloud", "proton", "protonmail", "live"}


def _first_nonempty(row: dict, columns: list[str]) -> str:
    for c in columns or []:
        v = (row.get(c) or "").strip()
        if v:
            return v
    return ""


def company_from_domain(email: str) -> str | None:
    domain = email.split("@", 1)[-1].lower()
    parts = [p for p in domain.split(".") if p]
    if len(parts) < 2:
        return None
    label = parts[-2]
    # co.uk / com.tn style second-level suffixes
    if len(parts) >= 3 and label in ("co", "com", "org", "net", "gov", "edu", "ac"):
        label = parts[-3]
    if label in FREE_MAIL:
        return None
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", label) if w) or None


def classify_rules(rule_kind: str, recipient: dict, row: dict, email: str) -> dict:
    """Returns {kind, name, company, honorific, decided_by, warnings}."""
    warnings: list[str] = []
    kind = "company"
    name = None
    if rule_kind == "human_if_available":
        names = [(row.get(c) or "").strip() for c in recipient.get("human_name_columns") or []]
        names = [n for n in names if n]
        if names:
            kind = "human"
            name = " ".join(names).strip()
    company = None
    if kind == "company":
        company = _first_nonempty(row, recipient.get("company_name_columns") or [])
        if not company:
            company = company_from_domain(email)
            if company:
                warnings.append("company_from_domain")
    else:
        company = _first_nonempty(row, recipient.get("company_name_columns") or []) or None
    return {"kind": kind, "name": name, "company": company or None, "honorific": None, "decided_by": "rules",
            "warnings": warnings}
