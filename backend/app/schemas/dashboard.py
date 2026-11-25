"""Pydantic v2 response schemas for AIRWISE AI endpoints."""

from typing import Literal
from pydantic import BaseModel, Field


DataMode = Literal["demo"]
HealthStatus = Literal["ok", "degraded"]
HealthDataMode = Literal["live_model", "demo"]
HistoryStoreHealthStatus = Literal["ok", "unavailable"]
AqiBand = Literal[
    "Good",
    "Moderate",
    "Unhealthy for Sensitive Groups",
    "Unhealthy",
    "Very Unhealthy",
    "Hazardous",
]
PollutantStatus = Literal["Low", "Moderate", "Elevated", "High"]
PriorityLevel = Literal["High", "Medium", "Informational"]


class HealthResponse(BaseModel):
    """Lightweight runtime health and configuration readiness response schema."""

    status: HealthStatus = Field(
        default="ok",
        description="Overall runtime health status ('ok' or 'degraded')",
    )
    service: str = Field(..., description="Application service name")
    version: str = Field(..., description="API semantic version")
    environment: str = Field(..., description="Runtime environment name")
    data_mode: HealthDataMode = Field(
        default="live_model",
        description="Active configured environmental data mode ('live_model' or 'demo')",
    )
    live_provider_connected: bool = Field(
        default=False,
        description=(
            "True only when live upstream connectivity has been verified. "
            "Always False on lightweight /health checks (which perform no outbound network probes); "
            "use provider_configured to check whether the upstream provider URL is configured."
        ),
    )
    provider_configured: bool = Field(
        default=True,
        description="Authoritative indicator: True when Open-Meteo CAMS Global provider URL is configured",
    )
    provider_name: str = Field(
        default="Open-Meteo (CAMS Global)",
        description="Configured primary atmospheric model provider name",
    )
    assistant_configured: bool = Field(
        default=False,
        description="True when backend Gemini credentials are configured (never exposes secrets)",
    )
    history_store_status: HistoryStoreHealthStatus = Field(
        default="ok",
        description="Local SQLite historical store readiness ('ok' or 'unavailable')",
    )
    supported_locations_count: int = Field(
        default=4,
        ge=0,
        description="Number of configured canonical urban locations",
    )


class LocationOption(BaseModel):
    """Supported urban location descriptor."""

    id: str = Field(..., description="URL-safe location identifier, e.g. lagos-ng")
    city: str = Field(..., description="City name")
    region: str = Field(..., description="State or administrative region")
    country: str = Field(..., description="Country name")
    display_name: str = Field(..., description="Formatted city and country display string")
    latitude: float = Field(..., description="Approximate latitude")
    longitude: float = Field(..., description="Approximate longitude")
    timezone: str = Field(..., description="IANA timezone string")


class AirQualitySummary(BaseModel):
    """Overall urban air quality summary card data (explicitly demo/sample)."""

    aqi_value: int = Field(..., ge=0, le=500, description="Sample US EPA-scale AQI value (demo)")
    aqi_band: AqiBand = Field(..., description="AQI health category band")
    dominant_pollutant: str = Field(..., description="Primary contributing pollutant code")
    summary_statement: str = Field(..., description="Concise plain-language summary of current sample conditions")
    reference_timestamp_label: str = Field(
        ...,
        description="Clear label indicating sample reference scenario rather than live telemetry",
    )
    weather_context: str = Field(..., description="Sample meteorological context affecting dispersion")


class PollutantCard(BaseModel):
    """Individual atmospheric pollutant card data."""

    code: str = Field(..., description="Short pollutant identifier, e.g., PM2.5, PM10, NO2, O3")
    name: str = Field(..., description="Full chemical or particulate name")
    value: float = Field(..., ge=0, description="Sample concentration value")
    unit: str = Field(..., description="Measurement unit, e.g., µg/m³ or ppb")
    status: PollutantStatus = Field(..., description="Relative concentration status")
    who_guideline_ref: str = Field(..., description="Reference benchmark note for context")
    source_hint: str = Field(..., description="Typical urban emission source in this scenario")


class HealthGuidanceGroup(BaseModel):
    """Targeted health guidance for a specific population group."""

    audience: str = Field(..., description="Target population group")
    risk_level: str = Field(..., description="Relative exposure risk in this sample scenario")
    guidance: str = Field(..., description="Actionable protective guidance")


class HealthAdvisoryPanel(BaseModel):
    """Comprehensive health advisory section."""

    headline: str = Field(..., description="Primary health advisory headline")
    general_advice: str = Field(..., description="Overview guidance for all residents")
    groups: list[HealthGuidanceGroup] = Field(..., description="Segmented guidance by sensitivity group")


class DailyRecommendation(BaseModel):
    """Time-window or activity recommendation preview."""

    id: str = Field(..., description="Unique recommendation identifier")
    time_window: str = Field(..., description="Relevant time of day or activity window")
    title: str = Field(..., description="Short actionable recommendation title")
    description: str = Field(..., description="Practical explanation for urban commuters or households")
    priority: PriorityLevel = Field(..., description="Priority classification")
    category: str = Field(..., description="Category such as Commute, Ventilation, Exercise, or Schools")


class AssistantSamplePrompt(BaseModel):
    """Sample prompt and preview response for the AIRWISE AI Assistant preview."""

    id: str = Field(..., description="Prompt identifier")
    question: str = Field(..., description="Sample user question")
    preview_answer: str = Field(..., description="Sample deterministic preview response labelled as demo")


class AssistantPreview(BaseModel):
    """AI Assistant preview state and sample Q&A capabilities."""

    status_label: str = Field(
        default="Preview Mode (Demo Context)",
        description="Current operational status of the AI assistant integration",
    )
    capabilities_summary: str = Field(
        ...,
        description="Explanation of what the assistant does and its current demo status",
    )
    sample_prompts: list[AssistantSamplePrompt] = Field(
        ...,
        description="Pre-populated urban air quality questions for interactive preview",
    )


class DashboardResponse(BaseModel):
    """Top-level response schema for GET /api/v1/dashboard."""

    is_demo_data: Literal[True] = Field(
        default=True,
        description="Always True while serving sample/demo environmental data",
    )
    data_mode: DataMode = Field(
        default="demo",
        description="Explicit data mode discriminator",
    )
    data_source_label: str = Field(
        default="DEMO DATA — Simulated Urban Scenario (No Live Sensor Provider Connected)",
        description="Human-readable banner label requiring clear UI disclosure",
    )
    disclaimer: str = Field(
        ...,
        description="Explicit notice that measurements are illustrative sample values and not real-time AQI telemetry",
    )
    selected_location: LocationOption = Field(..., description="Currently active urban location")
    available_locations: list[LocationOption] = Field(
        ...,
        description="Supported demo locations for the location selector",
    )
    summary: AirQualitySummary = Field(..., description="Headline AQI summary for the selected city")
    pollutants: list[PollutantCard] = Field(..., description="Key urban pollutant breakdowns")
    health_advisory: HealthAdvisoryPanel = Field(..., description="Health guidance panel")
    daily_recommendations: list[DailyRecommendation] = Field(
        ...,
        description="Actionable daily planning recommendations preview",
    )
    assistant_preview: AssistantPreview = Field(
        ...,
        description="AIRWISE AI urban assistant preview module",
    )
