"""Deterministic fake LLM (LLM_FAKE=1)."""

from __future__ import annotations

import re

GENERIC = {
    "info",
    "contact",
    "hr",
    "rh",
    "jobs",
    "careers",
    "recrutement",
    "hello",
    "support",
    "admin",
    "office",
    "team",
    "recruitment",
    "sales",
    "jobs-fr",
    "talent",
}
FEMALE = {"sarah", "marie", "emma", "anna", "sophie", "laura", "julia", "sara", "fatma", "amel", "ines"}
MALE = {"john", "paul", "david", "peter", "ahmed", "mohamed", "karim", "mehdi", "youssef", "jean"}


def _title(s: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[\s._-]+", s) if w)


def fake_classify(batch: list[dict]) -> list[dict]:
    out = []
    for it in batch:
        local, _, domain = it["email"].partition("@")
        local_l = local.lower()
        personal = local_l not in GENERIC and bool(
            re.match(r"^[a-z]+([._-][a-z]+)+$|^[a-z]\.[a-z]+$", local_l)
        )
        company = None
        if it.get("company_names"):
            company = " ".join(it["company_names"]).strip() or None
        if company is None:
            label = domain.split(".")[0] if domain else ""
            company = label.capitalize() if label else None
        if personal:
            first = re.split(r"[._-]", local_l)[0]
            name = " ".join(it["person_names"]).strip() if it.get("person_names") else _title(local_l)
            hon = "Ms" if first in FEMALE else "Mr" if first in MALE else None
            out.append({"id": it["id"], "kind": "human", "name": name, "company": None, "honorific": hon})
        else:
            out.append(
                {"id": it["id"], "kind": "company", "name": None, "company": company, "honorific": None}
            )
    return out
