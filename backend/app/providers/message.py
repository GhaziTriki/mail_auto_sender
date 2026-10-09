from __future__ import annotations

from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from ..errors import Unprocessable
from .base import OutgoingEmail


def has_crlf(*values: str | None) -> bool:
    return any(v is not None and ("\r" in v or "\n" in v) for v in values)


def build_message(email: OutgoingEmail) -> EmailMessage:
    if has_crlf(email.to, email.subject, email.from_name, email.from_address, email.reply_to):
        raise Unprocessable("Header fields must not contain line breaks", code="header_injection")
    msg = EmailMessage()
    msg["From"] = formataddr((email.from_name or "", email.from_address)) if email.from_name else email.from_address
    msg["To"] = email.to
    msg["Reply-To"] = email.reply_to or email.from_address
    msg["Subject"] = email.subject
    msg["Date"] = formatdate(localtime=False)
    domain = email.from_address.split("@", 1)[-1]
    msg["Message-ID"] = make_msgid(domain=domain)
    msg.set_content(email.body_text, subtype="plain", charset="utf-8")
    msg.add_attachment(email.attachment_bytes, maintype="application", subtype="pdf",
                       filename=email.attachment_name)
    return msg
