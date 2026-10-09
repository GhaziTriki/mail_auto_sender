"""LLM batch classification with validation, retries and key rotation (spec 8.6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .. import clock
from ..config import get_settings
from ..crypto import decrypt
from ..services import llm_keys as keys
from . import fake, gemini
from .gemini import LLMError

MAX_LLM_ATTEMPTS = 3  # first try + 2 retries (spec: retry up to 2 times, smaller batch)


@dataclass
class BatchOutcome:
    status: str  # "ok" | "paused" | "wait"
    results: dict = field(default_factory=dict)  # item_id(str) -> validated result dict
    pause_detail: dict | None = None
    key_id: object = None
    detail: str = ""


def build_payload(run: dict, items: list[dict]) -> list[dict]:
    rec = run["recipient"]
    out = []
    for it in items:
        row = it.get("row") or {}
        out.append(
            {
                "id": str(it["_id"]),
                "email": it["email_norm"],
                "person_names": [
                    v for c in rec.get("human_name_columns", []) if (v := (row.get(c) or "").strip())
                ],
                "company_names": [
                    v for c in rec.get("company_name_columns", []) if (v := (row.get(c) or "").strip())
                ],
            }
        )
    return out


def validate_response(sent_ids: set[str], data: list) -> dict[str, dict]:
    """Return only valid entries for ids we sent. Anything missing/invalid is simply absent."""
    good: dict[str, dict] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        _id = entry.get("id")
        if not isinstance(_id, str) or _id not in sent_ids or _id in good:
            continue
        kind = entry.get("kind")
        if kind not in ("human", "company"):
            continue
        name, company, hon = entry.get("name"), entry.get("company"), entry.get("honorific")
        if name is not None and not isinstance(name, str):
            continue
        if company is not None and not isinstance(company, str):
            continue
        if hon not in (None, "Mr", "Ms"):
            continue
        good[_id] = {
            "kind": kind,
            "name": (name or "").strip() or None,
            "company": (company or "").strip() or None,
            "honorific": hon,
        }
    return good


def _call(key: dict | None, payload: list[dict]) -> list:
    if get_settings().llm_fake:
        return fake.fake_classify(payload)
    return gemini.call_gemini(decrypt(key["secret_enc"]), payload)


def classify_batch(run: dict, items: list[dict]) -> BatchOutcome:
    """One LLM request for `items`. Handles key rotation. Never raises."""
    s = get_settings()
    payload = build_payload(run, items)
    sent_ids = {p["id"] for p in payload}
    tried: set = set()
    last_pause: dict | None = None
    while True:
        if s.llm_fake:
            key = None
        else:
            key, pause = keys.pick_key(run.get("llm_key_ids") or [], skip=tried)
            if key is None:
                last_pause = pause
                return BatchOutcome("paused", pause_detail=last_pause)
        try:
            data = _call(key, payload)
            if key is not None:
                keys.record_request(key["_id"])
            return BatchOutcome(
                "ok", results=validate_response(sent_ids, data), key_id=key["_id"] if key else None
            )
        except LLMError as e:
            if key is not None:
                keys.record_request(key["_id"])  # the request reached Google
            if e.kind == "quota":
                keys.mark_quota(key["_id"], e.detail)
                tried.add(key["_id"])
                continue
            if e.kind == "auth":
                keys.mark_auth_failed(key["_id"], e.detail)
                tried.add(key["_id"])
                continue
            return BatchOutcome("wait", detail=e.detail)


def min_interval_deadline() -> object:
    return clock.now() + timedelta(seconds=get_settings().llm_min_interval_s)
