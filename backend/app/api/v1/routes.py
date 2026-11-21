"""API v1 endpoints for health check, demo dashboard, Open-Meteo model air quality, and Gemini AI assistant."""

from fastapi import APIRouter, HTTPException, Query
from app.core.config import get_settings
from app.schemas.air_quality import AirQualityResponse
from app.schemas.assistant import (
    AssistantRequest,
    AssistantResponse,
    AssistantStatusResponse,
)
from app.schemas.dashboard import DashboardResponse, HealthResponse
from app.schemas.history import (
    HistoricalAirQualityResponse,
    HistoricalCityComparisonResponse,
)
from app.schemas.intelligence import PredictiveIntelligenceResponse
from app.services.demo_data import build_demo_dashboard
from app.services.gemini_assistant import (
    GeminiAssistantError,
    ask_airwise_assistant,
    get_assistant_status,
)
from app.services.open_meteo import (
    InvalidLocationError,
    OpenMeteoProviderError,
    fetch_open_meteo_air_quality,
)
from app.services.open_meteo_history import (
    fetch_historical_air_quality,
    fetch_historical_city_comparison,
)
from app.services.predictive_intelligence import fetch_predictive_intelligence

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Returns service operational status and confirms whether default dashboard data mode is demo.",
)
def get_health() -> HealthResponse:
    """Return service health metadata."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        data_mode="demo",
        live_provider_connected=False,
    )


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Get Urban Air Quality Dashboard (Demo Data)",
    description=(
        "Returns clearly labelled sample/demo urban air quality metrics, pollutant cards, "
        "health advisories, daily recommendations, and assistant preview for the selected city."
    ),
)
def get_dashboard(
    location: str = Query(
        default="lagos-ng",
        min_length=2,
        max_length=40,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Location identifier (defaults to lagos-ng for Lagos, Nigeria)",
    ),
) -> DashboardResponse:
    """Return demo dashboard payload for the requested urban location."""
    return build_demo_dashboard(location_id=location)


@router.get(
    "/air-quality",
    response_model=AirQualityResponse,
    summary="Get Open-Meteo Model-Based Air Quality Estimate",
    description=(
        "Fetches and normalizes atmospheric model air quality estimates from the official "
        "Open-Meteo Air Quality API (CAMS Global domain) for the requested configured location. "
        "Explicitly labelled as 'LIVE PROVIDER DATA — MODEL-BASED ESTIMATE'. "
        "Never substitutes demo values."
    ),
)
def get_air_quality(
    location_id: str = Query(
        default="lagos-ng",
        min_length=2,
        max_length=40,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Configured location identifier: lagos-ng, abuja-ng, nairobi-ke, or accra-gh",
    ),
) -> AirQualityResponse:
    """Return normalized Open-Meteo model-based air quality payload or structured error."""
    try:
        return fetch_open_meteo_air_quality(location_id=location_id)
    except OpenMeteoProviderError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error_code": exc.error_code,
                "message": exc.message,
                "location_id": location_id,
                "data_mode": "unavailable",
                "is_demo_data": False,
            },
        ) from exc


@router.get(
    "/air-quality/history",
    response_model=HistoricalAirQualityResponse,
    summary="Get Historical CAMS Global Air Quality Data",
    description=(
        "Retrieves genuine historical Open-Meteo CAMS Global model estimates (7, 14, or 30 days) "
        "with local SQLite persistence, timezone-aware daily aggregations, and strict data-origin "
        "disclosures. Explicitly labelled 'HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE'."
    ),
)
def get_air_quality_history(
    location_id: str = Query(
        default="lagos-ng",
        min_length=2,
        max_length=40,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Canonical location identifier: lagos-ng, abuja-ng, nairobi-ke, or accra-gh",
    ),
    days: int = Query(
        default=7,
        description="Historical range in days: 7, 14, or 30",
    ),
    force_refresh: bool = Query(
        default=False,
        description="Bypass in-memory historical cache and SQLite freshness check to refresh from Open-Meteo",
    ),
) -> HistoricalAirQualityResponse:
    """Return validated historical air-quality hourly records and daily summaries."""
    try:
        return fetch_historical_air_quality(
            location_id=location_id,
            days=days,
            force_refresh=force_refresh,
        )
    except OpenMeteoProviderError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error_code": exc.error_code,
                "message": exc.message,
                "location_id": location_id,
                "days": days,
                "data_mode": "unavailable",
                "is_demo_data": False,
            },
        ) from exc


@router.get(
    "/air-quality/history/compare",
    response_model=HistoricalCityComparisonResponse,
    summary="Compare Historical Air Quality Across All Four Configured Cities",
    description=(
        "Retrieves historical CAMS Global model summaries (7, 14, or 30 days) for Lagos, Abuja, "
        "Nairobi, and Accra. Fault-isolated per city so a single city outage never fails the others."
    ),
)
def get_air_quality_history_compare(
    days: int = Query(
        default=7,
        description="Historical range in days: 7, 14, or 30",
    ),
    force_refresh: bool = Query(
        default=False,
        description="Bypass cache/freshness check to refresh all four cities from Open-Meteo",
    ),
) -> HistoricalCityComparisonResponse:
    """Return fault-isolated historical comparison across all four configured cities."""
    try:
        return fetch_historical_city_comparison(
            days=days,
            force_refresh=force_refresh,
        )
    except OpenMeteoProviderError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error_code": exc.error_code,
                "message": exc.message,
                "days": days,
                "data_mode": "unavailable",
                "is_demo_data": False,
            },
        ) from exc


@router.get(
    "/air-quality/intelligence",
    response_model=PredictiveIntelligenceResponse,
    summary="Get Deterministic Predictive Intelligence & Risk Insights",
    description=(
        "Transforms verified Open-Meteo CAMS Global hourly forecasts into deterministic Peak Forecast Risk, "
        "elevated-risk windows, single-hour spikes, comparatively favorable windows, independent activity "
        "planning guidance, provisional OLS trend signals, and transparent forecast data-quality evidence."
    ),
)
def get_air_quality_intelligence(
    location_id: str = Query(
        default="lagos-ng",
        min_length=2,
        max_length=40,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Canonical location identifier: lagos-ng, abuja-ng, nairobi-ke, or accra-gh",
    ),
) -> PredictiveIntelligenceResponse:
    """Return deterministic predictive intelligence for the requested canonical location."""
    try:
        return fetch_predictive_intelligence(location_id=location_id)
    except OpenMeteoProviderError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error_code": exc.error_code,
                "message": exc.message,
                "location_id": location_id,
                "data_mode": "unavailable",
                "is_demo_data": False,
            },
        ) from exc


@router.get(
    "/assistant/status",
    response_model=AssistantStatusResponse,
    summary="Get AIRWISE AI Gemini Assistant Status",
    description=(
        "Checks whether backend Gemini API credentials are configured without ever exposing secrets."
    ),
)
def get_airwise_assistant_status() -> AssistantStatusResponse:
    """Return safe readiness status for the Gemini assistant."""
    return get_assistant_status()


@router.post(
    "/assistant/ask",
    response_model=AssistantResponse,
    summary="Ask AIRWISE AI (Gemini Grounded in Verified Open-Meteo Data)",
    description=(
        "Answers urban air-quality questions, builds daily activity plans, explains pollutants, "
        "or compares all four configured cities using Google Gemini grounded strictly in verified "
        "Open-Meteo CAMS Global model data. Returns HTTP 503 when GEMINI_API_KEY is not configured."
    ),
)
def post_airwise_assistant_ask(payload: AssistantRequest) -> AssistantResponse:
    """Execute a grounded Gemini assistant request or return a clean structured error."""
    try:
        return ask_airwise_assistant(payload)
    except InvalidLocationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error_code": exc.error_code,
                "message": exc.message,
                "location_id": payload.location_id,
            },
        ) from exc
    except GeminiAssistantError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error_code": exc.error_code,
                "message": exc.message,
                "location_id": payload.location_id,
                "assistant_status": "assistant_unavailable"
                if exc.error_code == "assistant_unavailable"
                else "error",
            },
        ) from exc
