from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..db import get_db
from ..providers.registry import list_providers

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health():
    try:
        get_db().command("ping")
        return {"status": "ok"}
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "error", "detail": type(e).__name__}, status_code=503)


@router.get("/config")
def config():
    s = get_settings()
    return {
        "limits": {"max_rows": s.max_rows, "max_source_mb": s.max_source_mb, "max_cv_mb": s.max_cv_mb,
                   "max_gmail_daily_cap": s.max_gmail_daily_cap, "max_outlook_daily_cap": s.max_outlook_daily_cap},
        "defaults": {"gmail_daily_cap": s.default_gmail_daily_cap, "outlook_daily_cap": s.default_outlook_daily_cap,
                     "llm_daily_cap": s.default_llm_daily_cap, "delay_min_s": s.send_delay_min_s,
                     "delay_max_s": s.send_delay_max_s, "max_retries": s.max_retries,
                     "llm_batch_size": s.llm_batch_size},
        "providers": {p["name"]: p["enabled"] for p in list_providers()},
        "llm_fake": s.llm_fake,
        "gemini_model": s.gemini_model,
    }


@router.get("/providers")
def providers():
    return list_providers()
