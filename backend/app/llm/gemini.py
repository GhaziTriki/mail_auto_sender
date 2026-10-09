from __future__ import annotations

import json
from dataclasses import dataclass

from ..config import get_settings

SYSTEM_INSTRUCTION = (
    "Decide whether each email address belongs to a specific person or to a company/generic mailbox. "
    'Personal patterns (firstname.lastname@, initials) -> "human". Generic mailboxes (info@, contact@, hr@, '
    'rh@, jobs@, careers@, recrutement@, hello@, support@) -> "company" even if a person name column is filled. '
    'Return a cleaned person name (proper case) for humans.'
    "Return a cleaned company name for companies, derive from the email domain when it's not mentionned explicitly."
    "Return honorific \"Mr\" or \"Ms\" only when the first "
    "name is unambiguous; otherwise null. Never invent data."
)

RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "kind": {"type": "string", "enum": ["human", "company"]},
            "name": {"type": "string", "nullable": True},
            "company": {"type": "string", "nullable": True},
            "honorific": {"type": "string", "enum": ["Mr", "Ms"], "nullable": True},
        },
        "required": ["id", "kind"],
    },
}


class LLMError(Exception):
    """kind: quota | auth | transient"""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


@dataclass
class GeminiResponse:
    items: list


def classify_exception(exc: BaseException) -> LLMError:
    """Map an SDK/HTTP exception to quota/auth/transient (spec 8.6)."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    if code == 429 or "resource_exhausted" in low or "429" in low and "quota" in low:
        return LLMError("quota", text[:300])
    if code in (400, 401, 403) or "api key not valid" in low or "api_key_invalid" in low or "permission_denied" in low:
        return LLMError("auth", text[:300])
    return LLMError("transient", text[:300])


def call_gemini(api_key: str, payload: list[dict]) -> list:
    """One request. Raises LLMError. Returns the parsed JSON list."""
    try:
        from google import genai
        from google.genai import types
    except Exception as e:  # noqa: BLE001
        raise LLMError("transient", f"google-genai not available: {e}") from e
    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=get_settings().gemini_model,
            contents=json.dumps(payload, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
            ),
        )
        text = resp.text or "[]"
    except Exception as e:  # noqa: BLE001
        raise classify_exception(e) from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError("transient", f"Gemini returned invalid JSON: {e}") from e
    if not isinstance(data, list):
        raise LLMError("transient", "Gemini returned a non-list JSON value")
    return data


def check_key(api_key: str) -> tuple[bool, str, bool]:
    """Returns (ok, detail, auth_failed). Counts as one request against the key."""
    if get_settings().llm_fake:
        return True, "Fake LLM mode: key accepted", False
    try:
        call_gemini(api_key, [{"id": "check", "email": "jane.doe@example.com", "person_names": [], "company_names": []}])
        return True, "Key works", False
    except LLMError as e:
        return False, f"{e.kind}: {e.detail}", e.kind == "auth"
