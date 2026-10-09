from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass
class OutgoingEmail:
    from_name: str | None
    from_address: str
    to: str
    reply_to: str | None
    subject: str
    body_text: str
    attachment_name: str
    attachment_bytes: bytes


@dataclass
class SendResult:
    outcome: Literal["sent", "transient", "permanent", "auth", "quota", "unknown"]
    detail: str = ""
    message_id: str | None = None
    retry_after_s: int | None = None
    recipient_specific: bool = False


@dataclass
class CheckResult:
    ok: bool
    detail: str = ""
    auth_failed: bool = False


class Provider(Protocol):
    name: str

    def check(self, sender: dict) -> CheckResult: ...

    def send(self, sender: dict, email: OutgoingEmail) -> SendResult: ...
