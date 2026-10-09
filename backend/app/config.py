from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    v = os.environ.get(name, "").strip()
    return int(v) if v else default


def _str(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v.strip() if v is not None and v.strip() != "" else default


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _int_list(name: str, default: str) -> list[int]:
    raw = _str(name, default)
    return [int(x) for x in raw.split(",") if x.strip()]


@dataclass
class Settings:
    secret_key: str = ""
    mongo_url: str = "mongodb://mongo:27017/applymail"
    data_dir: str = "/data"
    app_base_url: str = "http://localhost:8000"
    docs_dir: str = ""

    gmail_smtp_host: str = "smtp.gmail.com"
    gmail_smtp_port: int = 587
    gmail_smtp_security: str = "starttls"
    gmail_smtp_auth: bool = True
    default_gmail_daily_cap: int = 100
    max_gmail_daily_cap: int = 400

    outlook_client_id: str = ""
    outlook_redirect_uri: str = "http://localhost:8000/api/oauth/outlook/callback"
    default_outlook_daily_cap: int = 100
    max_outlook_daily_cap: int = 250

    gemini_model: str = "gemini-flash-latest"
    default_llm_daily_cap: int = 200
    llm_min_interval_s: int = 6
    llm_batch_size: int = 20
    llm_fake: bool = False

    send_delay_min_s: int = 30
    send_delay_max_s: int = 90
    max_retries: int = 3
    retry_delays_s: list[int] = field(default_factory=lambda: [60, 300, 900])
    breaker_threshold: int = 10
    lease_s: int = 120
    worker_tick_s: int = 2
    max_rows: int = 20000
    max_source_mb: int = 10
    max_cv_mb: int = 3

    @property
    def outlook_enabled(self) -> bool:
        return bool(self.outlook_client_id)


def load_settings() -> Settings:
    return Settings(
        secret_key=_str("SECRET_KEY", ""),
        mongo_url=_str("MONGO_URL", "mongodb://mongo:27017/applymail"),
        data_dir=_str("DATA_DIR", "/data"),
        app_base_url=_str("APP_BASE_URL", "http://localhost:8000"),
        docs_dir=_str("DOCS_DIR", ""),
        gmail_smtp_host=_str("GMAIL_SMTP_HOST", "smtp.gmail.com"),
        gmail_smtp_port=_int("GMAIL_SMTP_PORT", 587),
        gmail_smtp_security=_str("GMAIL_SMTP_SECURITY", "starttls").lower(),
        gmail_smtp_auth=_bool("GMAIL_SMTP_AUTH", True),
        default_gmail_daily_cap=_int("DEFAULT_GMAIL_DAILY_CAP", 100),
        max_gmail_daily_cap=_int("MAX_GMAIL_DAILY_CAP", 400),
        outlook_client_id=_str("OUTLOOK_CLIENT_ID", ""),
        outlook_redirect_uri=_str("OUTLOOK_REDIRECT_URI", "http://localhost:8000/api/oauth/outlook/callback"),
        default_outlook_daily_cap=_int("DEFAULT_OUTLOOK_DAILY_CAP", 100),
        max_outlook_daily_cap=_int("MAX_OUTLOOK_DAILY_CAP", 250),
        gemini_model=_str("GEMINI_MODEL", "gemini-flash-latest"),
        default_llm_daily_cap=_int("DEFAULT_LLM_DAILY_CAP", 200),
        llm_min_interval_s=_int("LLM_MIN_INTERVAL_S", 6),
        llm_batch_size=_int("LLM_BATCH_SIZE", 20),
        llm_fake=_bool("LLM_FAKE", False),
        send_delay_min_s=_int("SEND_DELAY_MIN_S", 30),
        send_delay_max_s=_int("SEND_DELAY_MAX_S", 90),
        max_retries=_int("MAX_RETRIES", 3),
        retry_delays_s=_int_list("RETRY_DELAYS_S", "60,300,900"),
        breaker_threshold=_int("BREAKER_THRESHOLD", 10),
        lease_s=_int("LEASE_S", 120),
        worker_tick_s=_int("WORKER_TICK_S", 2),
        max_rows=_int("MAX_ROWS", 20000),
        max_source_mb=_int("MAX_SOURCE_MB", 10),
        max_cv_mb=_int("MAX_CV_MB", 3),
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_settings(s: Settings | None) -> None:
    """Tests only."""
    global _settings
    _settings = s
