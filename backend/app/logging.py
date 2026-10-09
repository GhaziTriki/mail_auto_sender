from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

_REDACT_KEYS = {"secret", "secret_enc", "app_password", "password", "api_key", "token", "access_token",
                "refresh_token", "body", "authorization", "contentbytes"}
_PATTERNS = [
    re.compile(r"(?i)(app[_ ]?password|api[_ ]?key|secret|token|password)(\s*[=:]\s*)\S+"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"gAAAA[0-9A-Za-z_\-=]{20,}"),
]


def redact_text(s: str) -> str:
    for p in _PATTERNS:
        if p.groups >= 2:
            s = p.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", s)
        else:
            s = p.sub("[REDACTED]", s)
    return s


def redact(value):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if str(k).lower() in _REDACT_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
        }
        for k in ("run_id", "item_id", "sender_id", "event"):
            if hasattr(record, k):
                data[k] = str(getattr(record, k))
        extra = getattr(record, "extra_data", None)
        if extra:
            data["data"] = redact(extra)
        if record.exc_info:
            data["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(data, default=str)


def setup_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
