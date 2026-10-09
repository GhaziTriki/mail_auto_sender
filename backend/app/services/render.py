"""Template rendering by regex substitution only (spec 8.4). No eval, no Jinja."""
from __future__ import annotations

import re

from ..errors import Unprocessable
from .greeting import build_greeting

PLACEHOLDER_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.S)
BUILTINS = {"greeting", "name", "company", "email"}


def find_placeholders(text: str) -> list[str]:
    return [m.group(1) for m in PLACEHOLDER_RE.finditer(text or "")]


def validate_template(template: dict, columns: list[str]) -> list[str]:
    """Return a list of error strings (empty = valid)."""
    errors: list[str] = []
    subject = (template or {}).get("subject") or ""
    body = (template or {}).get("body") or ""
    if not subject.strip():
        errors.append("subject is empty")
    if not body.strip():
        errors.append("body is empty")
    if "\r" in subject or "\n" in subject:
        errors.append("subject must be a single line")
    for field, text in (("subject", subject), ("body", body)):
        for p in find_placeholders(text):
            if p in BUILTINS:
                continue
            if p.startswith("col:"):
                col = p[4:]
                if col not in columns:
                    errors.append(f"{field}: unknown column in placeholder '{{{{{p}}}}}'")
                continue
            errors.append(f"{field}: unknown placeholder '{{{{{p}}}}}'")
    return errors


def ensure_valid_template(template: dict, columns: list[str]) -> None:
    errs = validate_template(template, columns)
    if errs:
        raise Unprocessable("Invalid template: " + "; ".join(errs), code="invalid_template")


def substitute(text: str, values: dict[str, str], row: dict, warnings: list[str]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key in BUILTINS:
            v = values.get(key) or ""
            if not v and key != "greeting":
                warnings.append(f"empty:{key}")
            return v
        if key.startswith("col:"):
            col = key[4:]
            v = (row.get(col) or "").strip()
            if not v:
                warnings.append(f"empty:{col}")
            return v
        return m.group(0)  # unknown (blocked at prepare); leave as-is

    return PLACEHOLDER_RE.sub(repl, text or "")


def render_item(run: dict, item: dict) -> dict:
    """Render greeting/subject/body for an item from its classification fields."""
    warnings: list[str] = []
    greeting = build_greeting(run["greeting"], item.get("kind"), item.get("name"), item.get("company"),
                              item.get("honorific"))
    values = {"greeting": greeting, "name": item.get("name") or "", "company": item.get("company") or "",
              "email": item.get("email_norm") or ""}
    tpl = run["template"]
    row = item.get("row") or {}
    subject = substitute(tpl.get("subject", ""), values, row, warnings)
    subject = re.sub(r"[\r\n]+", " ", subject).strip()
    body = substitute(tpl.get("body", ""), values, row, warnings)
    seen: list[str] = []
    for w in warnings:
        if w not in seen:
            seen.append(w)
    return {"greeting_text": greeting, "subject": subject, "body": body, "render_warnings": seen}


def merged_warnings(item: dict, render_warnings: list[str]) -> list[str]:
    out: list[str] = []
    for w in list(item.get("class_warnings") or []) + render_warnings:
        if w not in out:
            out.append(w)
    return out
