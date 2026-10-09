from __future__ import annotations

import smtplib
import socket
import ssl

from ...config import get_settings
from ...crypto import decrypt
from ..base import CheckResult, OutgoingEmail, SendResult
from ..message import build_message

QUOTA_MARKERS = ("5.4.5", "daily user sending", "sending limit")


def _text(resp) -> str:
    if isinstance(resp, bytes):
        return resp.decode("utf-8", "replace")
    return str(resp)


def _is_quota(text: str) -> bool:
    t = text.lower()
    return any(m in t for m in QUOTA_MARKERS)


def map_smtp_error(exc: BaseException, phase: str) -> SendResult:
    """Pure mapping from an SMTP exception + phase to a SendResult (spec 10.1)."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return SendResult("auth", f"{exc.smtp_code} {_text(exc.smtp_error)}")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        for _addr, (code, msg) in exc.recipients.items():
            return _map_code(code, _text(msg), phase="rcpt")
        return SendResult("permanent", "recipient refused", recipient_specific=True)
    if isinstance(exc, smtplib.SMTPResponseException):
        return _map_code(exc.smtp_code, _text(exc.smtp_error), phase)
    if isinstance(exc, (smtplib.SMTPServerDisconnected, socket.timeout, TimeoutError, ConnectionError)):
        if phase == "data":
            return SendResult("unknown", f"connection lost during data: {exc}")
        return SendResult("transient", f"connection problem ({phase}): {exc}")
    if isinstance(exc, (ssl.SSLError, OSError, smtplib.SMTPException)):
        if phase == "data":
            return SendResult("unknown", f"error during data: {exc}")
        return SendResult("transient", f"{type(exc).__name__} ({phase}): {exc}")
    return SendResult("transient", f"{type(exc).__name__}: {exc}")


def _map_code(code: int, text: str, phase: str) -> SendResult:
    detail = f"{code} {text}"
    if _is_quota(text):
        return SendResult("quota", detail)
    if code in (534, 535) and phase in ("auth", "connect"):
        return SendResult("auth", detail)
    if 400 <= code < 500:
        return SendResult("transient", detail)
    if phase == "rcpt" and (code in (550, 551, 553) or "5.1." in text):
        return SendResult("permanent", detail, recipient_specific=True)
    if 500 <= code < 600:
        return SendResult("permanent", detail)
    return SendResult("transient", detail)


class GmailProvider:
    name = "gmail"

    def _connect(self, sender: dict):
        s = get_settings()
        sec = s.gmail_smtp_security
        if sec == "ssl":
            smtp = smtplib.SMTP_SSL(s.gmail_smtp_host, s.gmail_smtp_port, timeout=30,
                                    context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(s.gmail_smtp_host, s.gmail_smtp_port, timeout=30)
        smtp.ehlo()
        if sec == "starttls":
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        return smtp

    def _login(self, smtp, sender: dict) -> None:
        if get_settings().gmail_smtp_auth:
            smtp.login(sender["address"], decrypt(sender["secret_enc"]))

    def check(self, sender: dict) -> CheckResult:
        phase = "connect"
        smtp = None
        try:
            smtp = self._connect(sender)
            phase = "auth"
            self._login(smtp, sender)
            return CheckResult(True, "Login OK")
        except Exception as e:
            r = map_smtp_error(e, phase)
            return CheckResult(False, r.detail, auth_failed=(r.outcome == "auth"))
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    print()

    def send(self, sender: dict, email: OutgoingEmail) -> SendResult:
        phase = "connect"
        smtp = None
        try:
            msg = build_message(email)
            message_id = str(msg["Message-ID"])
            smtp = self._connect(sender)
            phase = "auth"
            self._login(smtp, sender)
            phase = "rcpt"
            code, resp = smtp.mail(email.from_address)
            if code >= 400:
                raise smtplib.SMTPResponseException(code, resp)
            code, resp = smtp.rcpt(email.to)
            if code >= 400:
                raise smtplib.SMTPResponseException(code, resp)
            phase = "data"
            code, resp = smtp.data(msg.as_bytes())
            if code >= 400:
                raise smtplib.SMTPResponseException(code, resp)
            return SendResult("sent", f"{code} {_text(resp)}", message_id=message_id)
        except Exception as e:
            from ...errors import AppError
            if isinstance(e, AppError):
                return SendResult("permanent", e.detail, recipient_specific=True)
            return map_smtp_error(e, phase)
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    try:
                        smtp.close()
                    except Exception:
                        print()
