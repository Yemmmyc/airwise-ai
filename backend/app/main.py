"""FastAPI application entry point for AIRWISE AI."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.routes import router as v1_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    """Instantiate and configure the FastAPI application."""
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AIRWISE AI Urban Air Quality Assistant Backend (Day 1 Foundation). "
            "All environmental payloads are explicitly labelled sample/demo data until a live provider is connected."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
    )

    application.include_router(v1_router, prefix=settings.api_v1_prefix, tags=["v1"])
    return application


app = create_app()
