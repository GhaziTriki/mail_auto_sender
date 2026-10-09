from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import dashboard, items, llm_keys, meta, oauth_outlook, runs, senders, status
from .config import get_settings
from .crypto import validate_secret_key
from .db import ensure_indexes
from .errors import AppError, ConfigError
from .logging import get_logger, setup_logging

log = get_logger("api")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    try:
        validate_secret_key(get_settings().secret_key)  # refuse to start without a valid key
    except ConfigError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        raise
    ensure_indexes()
    yield


app = FastAPI(title="ApplyMail", lifespan=lifespan)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    body = {"detail": exc.detail, "code": exc.code}
    body.update(exc.extra)
    return JSONResponse(body, status_code=exc.status_code)


@app.exception_handler(ConfigError)
async def config_error_handler(_: Request, exc: ConfigError):
    return JSONResponse({"detail": str(exc), "code": "config_error"}, status_code=500)


for r in (
    meta.router,
    senders.router,
    llm_keys.router,
    oauth_outlook.router,
    runs.router,
    items.router,
    dashboard.router,
    status.router,
):
    app.include_router(r)

_docs = get_settings().docs_dir
if _docs and Path(_docs).is_dir():
    app.mount("/docs-static", StaticFiles(directory=_docs), name="docs-static")

if STATIC.is_dir():
    if (STATIC / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/") or path.startswith("docs-static/"):
            return JSONResponse({"detail": "Not found", "code": "not_found"}, status_code=404)
        candidate = (STATIC / path).resolve()
        if path and candidate.is_file() and STATIC.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(STATIC / "index.html")
