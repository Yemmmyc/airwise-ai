"""FastAPI application entry point for AIRWISE AI."""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routes import router as v1_router
from app.core.config import get_settings
from app.core.logging_config import (
    REQUEST_ID_HEADER,
    configure_logging,
    get_logger,
    reset_request_id,
    resolve_request_id,
    set_request_id,
)

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Instantiate and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AIRWISE AI Urban Air Quality Intelligence Backend. "
            "Provides normalized Open-Meteo CAMS Global air quality estimates, "
            "SQLite-persisted historical trends, deterministic predictive risk intelligence, "
            "explicit demo fallback scenarios, and optional grounded Gemini AI assistance."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    @application.middleware("http")
    async def request_correlation_middleware(request: Request, call_next) -> Response:
        """Assign a validated correlation ID to every request and return it on all responses."""
        req_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = set_request_id(req_id)
        started = time.monotonic()

        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                duration_ms = round((time.monotonic() - started) * 1000.0, 2)
                logger.error(
                    "http_request_exception method=%s path=%s exc_type=%s duration_ms=%.2f",
                    request.method,
                    request.url.path,
                    type(exc).__name__,
                    duration_ms,
                )
                return JSONResponse(
                    status_code=500,
                    content={"detail": "Internal Server Error"},
                    headers={REQUEST_ID_HEADER: req_id},
                )

            duration_ms = round((time.monotonic() - started) * 1000.0, 2)
            response.headers[REQUEST_ID_HEADER] = req_id

            if response.status_code >= 500:
                logger.error(
                    "http_request_completed method=%s path=%s status=%d duration_ms=%.2f",
                    request.method,
                    request.url.path,
                    response.status_code,
                    duration_ms,
                )
            elif response.status_code >= 400:
                logger.warning(
                    "http_request_completed method=%s path=%s status=%d duration_ms=%.2f",
                    request.method,
                    request.url.path,
                    response.status_code,
                    duration_ms,
                )
            else:
                logger.info(
                    "http_request_completed method=%s path=%s status=%d duration_ms=%.2f",
                    request.method,
                    request.url.path,
                    response.status_code,
                    duration_ms,
                )

            return response
        finally:
            reset_request_id(token)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    application.include_router(v1_router, prefix=settings.api_v1_prefix, tags=["v1"])
    return application


app = create_app()
