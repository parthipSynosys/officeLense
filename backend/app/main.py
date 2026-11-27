"""FastAPI application entry point.

Development:  uvicorn app.main:app --reload
Production:   gunicorn app.main:app -k uvicorn.workers.UvicornWorker -c gunicorn.conf.py
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import cv2
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app import __version__
from app.api.admin import router as admin_router
from app.api.public import router as public_router
from app.bootstrap import ensure_single_admin
from app.config import get_settings
from app.face.engine import load_engine
from app.logging_config import configure_logging

log = logging.getLogger("eventlens")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    settings.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    ensure_single_admin()
    if settings.LOAD_MODELS_ON_STARTUP:
        # Each Gunicorn worker serves several requests concurrently; keep OpenCV
        # from spawning a thread per core in every worker.
        cv2.setNumThreads(2)
        try:
            load_engine()
        except FileNotFoundError as exc:
            # Keep serving (admin, health) so the problem is visible in /api/health.
            log.error("%s", exc)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="EventLens API",
        version=__version__,
        description="Self-hosted face-recognition event photo finder.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        # Uniform error shape: {"detail": {"code", "message", ...}}
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "ERROR", "message": str(exc.detail)}
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo request input back (could contain a password).
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse(
            {"detail": {"code": "VALIDATION_ERROR", "message": "Invalid request", "errors": errors}},
            status_code=422,
        )

    app.include_router(public_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")

    if settings.SERVE_PHOTOS:
        # Dev convenience only — in production nginx serves /photos/ (and blocks _incoming/).
        from fastapi.staticfiles import StaticFiles

        settings.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        app.mount("/photos", StaticFiles(directory=settings.PHOTOS_DIR), name="photos")
    return app


app = create_app()
