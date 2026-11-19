"""Pydantic v2 request and response schemas for the AIRWISE AI Gemini Assistant."""

from typing import Literal
from pydantic import BaseModel, Field

from app.schemas.air_quality import DataAttribution, DataProvenance
from app.schemas.dashboard import AqiBand, LocationOption


AssistantMode = Literal[
    "ask",
    "activity_planner",
    "pollutant_education",
    "city_comparison",
]
AssistantStatus = Literal["ok", "assistant_unavailable"]
PollutantCode = Literal["PM2.5", "PM10", "NO2", "O3", "SO2"]


class ConversationTurn(BaseModel):
    """Single prior conversation turn for multi-turn context."""

    role: Literal["user", "assistant"] = Field(..., description="Speaker role")
    content: str = Field(..., min_length=1, max_length=1200, description="Turn message content")


class AssistantRequest(BaseModel):
    """Request payload for POST /api/v1/assistant/ask."""

    location_id: str = Field(
        default="lagos-ng",
        min_length=2,
        max_length=40,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Selected urban location identifier",
    )
    mode: AssistantMode = Field(
        default="ask",
        description="Assistant capability mode: ask, activity_planner, pollutant_education, or city_comparison",
    )
    question: str = Field(
        ...,
        min_length=2,
        max_length=800,
        description="User question or prompt",
    )
    pollutant_code: PollutantCode | None = Field(
        default=None,
        description="Optional pollutant focus when mode is pollutant_education",
    )
    history: list[ConversationTurn] = Field(
        default_factory=list,
        max_length=6,
        description="Optional recent conversation turns for context (capped at 6)",
    )


class VerifiedPollutantSnapshot(BaseModel):
    """Verified pollutant value passed to Gemini and returned transparently to the UI."""

    code: PollutantCode
    value: float | None = None
    unit: str
    status: Literal["available", "unavailable"]


class VerifiedForecastSummary(BaseModel):
    """Verified summary of future-only forecast hours passed to Gemini."""

    hours_available: int = Field(..., ge=0)
    first_forecast_time: str | None = None
    last_forecast_time: str | None = None
    min_forecast_aqi: int | None = None
    max_forecast_aqi: int | None = None
    lowest_aqi_timestamp: str | None = None
    highest_aqi_timestamp: str | None = None


class VerifiedCitySnapshot(BaseModel):
    """Verified live model air quality snapshot for one configured city."""

    location: LocationOption
    data_status: Literal["available", "unavailable"]
    data_label: str
    observation_time: str | None = None
    retrieval_time: str | None = None
    timezone: str
    us_aqi: int | None = None
    aqi_band: AqiBand | None = None
    pollutants: list[VerifiedPollutantSnapshot] = Field(default_factory=list)
    forecast_summary: VerifiedForecastSummary | None = None
    missing_fields: list[str] = Field(default_factory=list)
    error_notice: str | None = None


class StructuredAssistantSections(BaseModel):
    """Explicitly separated response sections enforcing data integrity."""

    verified_data_summary: str = Field(
        ...,
        description="Factual summary grounded strictly in verified provider data",
    )
    forecast_context: str = Field(
        ...,
        description="Summary grounded strictly in available future hourly forecast points (> observation_time)",
    )
    ai_interpretation: str = Field(
        ...,
        description="Gemini AI interpretation of the verified data and user question",
    )
    general_health_guidance: str = Field(
        ...,
        description="General informational health guidance (never medical diagnosis or treatment)",
    )
    model_limitations_notice: str = Field(
        ...,
        description="Explicit reminder that CAMS Global (~45 km grid, 3-hourly native output) is not a street-level sensor",
    )


class AssistantStatusResponse(BaseModel):
    """Response for GET /api/v1/assistant/status indicating Gemini availability."""

    configured: bool = Field(
        ...,
        description="True only when a backend Gemini API key is configured",
    )
    status: Literal["ready", "assistant_unavailable"] = Field(
        ...,
        description="Operational readiness of the Gemini assistant",
    )
    model: str = Field(..., description="Configured Gemini model identifier")
    sdk: str = Field(default="google-genai", description="Official Google Gen AI SDK package")
    message: str = Field(..., description="Human-readable readiness status (never contains secrets)")


class AssistantResponse(BaseModel):
    """Structured response for POST /api/v1/assistant/ask."""

    status: AssistantStatus = Field(default="ok")
    mode: AssistantMode
    model: str = Field(..., description="Gemini model identifier used to generate the interpretation")
    location: LocationOption = Field(..., description="Primary selected urban location")
    question: str = Field(..., description="Original user question")
    generated_at: str = Field(..., description="ISO-8601 UTC timestamp when response was generated")
    sections: StructuredAssistantSections = Field(
        ...,
        description="Clearly separated verified data, forecast, AI interpretation, and health guidance sections",
    )
    verified_context: VerifiedCitySnapshot = Field(
        ...,
        description="Exact verified provider data snapshot passed to Gemini for the primary city",
    )
    city_comparisons: list[VerifiedCitySnapshot] = Field(
        default_factory=list,
        description="Verified snapshots for all four configured cities when mode is city_comparison",
    )
    provenance: DataProvenance | None = Field(
        default=None,
        description="Open-Meteo CAMS Global provenance when live data was available",
    )
    attribution: DataAttribution = Field(
        default_factory=DataAttribution,
        description="Mandatory Open-Meteo and Copernicus CAMS attribution",
    )
    is_ai_generated: Literal[True] = Field(
        default=True,
        description="Explicitly marks the interpretation as AI-generated",
    )
    disclaimer: str = Field(
        default=(
            "AI INTERPRETATION & GENERAL GUIDANCE: Powered by Google Gemini grounded in Open-Meteo "
            "CAMS Global atmospheric model estimates (~0.4° / ~45 km spatial resolution, 3-hourly native output). "
            "Model data is not physical roadside sensor telemetry and cannot establish precise street-level "
            "or indoor personal exposure. General health guidance is informational only and is not medical "
            "diagnosis, treatment, or medication advice."
        ),
        description="Mandatory AI and medical/spatial scope disclaimer",
    )
