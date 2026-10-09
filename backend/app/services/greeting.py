"""Greeting builder (spec 8.4)."""

from __future__ import annotations

import re

DEFAULT_GREETING = {
    "salutation": "Dear",
    "use_honorific": True,
    "company_template": "{salutation} {company} team,",
    "human_template": "{salutation} {honorific} {name},",
    "fallback_template": "{salutation} Hiring Team,",
}


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:!])", r"\1", s)
    return s


def build_greeting(
    cfg: dict, kind: str | None, name: str | None, company: str | None, honorific: str | None
) -> str:
    cfg = {**DEFAULT_GREETING, **(cfg or {})}
    name = (name or "").strip()
    company = (company or "").strip()
    hon = (honorific or "").strip() if cfg.get("use_honorific", True) else ""
    if kind == "human" and name:
        tpl = cfg["human_template"]
    elif kind == "company" and company:
        tpl = cfg["company_template"]
    else:
        tpl = cfg["fallback_template"]
    out = (
        tpl.replace("{salutation}", cfg["salutation"])
        .replace("{honorific}", hon)
        .replace("{name}", name)
        .replace("{company}", company)
    )
    return _clean(out)
