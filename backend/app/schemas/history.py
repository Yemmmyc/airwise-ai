"""Pydantic v2 schemas for genuine historical air-quality retrieval, persistence, and city comparison."""

from typing import Literal
from pydantic import BaseModel, Field

from app.schemas.air_quality import (
    AirQualityUnits,
    DataAttribution,
    DataProvenance,
)
from app.schemas.dashboard import AqiBand, LocationOption


HistoricalRangeDays = Literal[7, 14, 30]
HistoricalStorageOrigin = Literal[
    "fresh_provider_retrieval",
    "historical_cache",
    "persisted_database_records",
    "persisted_database_fallback",
]
CityHistoryStatus = Literal["available", "unavailable"]


class HistoricalHourlyRecord(BaseModel):
    """Single historical atmospheric model hourly record (strictly historical_model)."""

    classification: Literal["historical_model"] = Field(
        default="historical_model",
        description="Explicitly marks this record as historical model data (never forecast)",
    )
    timestamp_utc: str = Field(
        ...,
        description="Canonical ISO-8601 UTC timestamp used as the storage/index key",
    )
    local_time: str = Field(
        ...,
        description="Provider timestamp in the location's configured IANA timezone",
    )
    timezone: str = Field(..., description="IANA timezone of the location")
    us_aqi: int | None = Field(default=None, ge=0, le=500, description="US AQI from Open-Meteo (null if unavailable)")
    pm2_5: float | None = Field(default=None, ge=0.0, description="PM2.5 in µg/m³ (null if unavailable)")
    pm10: float | None = Field(default=None, ge=0.0, description="PM10 in µg/m³ (null if unavailable)")
    no2: float | None = Field(default=None, ge=0.0, description="Nitrogen dioxide in µg/m³ (null if unavailable)")
    o3: float | None = Field(default=None, ge=0.0, description="Ground-level ozone in µg/m³ (null if unavailable)")
    so2: float | None = Field(default=None, ge=0.0, description="Sulphur dioxide in µg/m³ (null if unavailable)")
    source: str = Field(
        default="open_meteo_cams_global",
        description="Upstream model source identifier",
    )
    model_domain: str = Field(
        default="cams_global",
        description="Atmospheric model domain",
    )
    retrieval_time: str = Field(
        ...,
        description="ISO-8601 UTC timestamp when this record was retrieved from Open-Meteo",
    )


class DailyHistoricalSummary(BaseModel):
    """Server-computed daily rollup grouped strictly in the selected location's local timezone."""

    date: str = Field(..., description="Local calendar date (YYYY-MM-DD) in the location's timezone")
    timezone: str = Field(..., description="Location IANA timezone used for calendar-day grouping")
    avg_us_aqi: float | None = Field(default=None, ge=0.0, le=500.0)
    max_us_aqi: int | None = Field(default=None, ge=0, le=500)
    min_us_aqi: int | None = Field(default=None, ge=0, le=500)
    dominant_aqi_band: AqiBand | None = Field(
        default=None,
        description="US EPA AQI band corresponding to avg_us_aqi (rounded) when available",
    )
    avg_pm2_5: float | None = Field(default=None, ge=0.0)
    max_pm2_5: float | None = Field(default=None, ge=0.0)
    avg_pm10: float | None = Field(default=None, ge=0.0)
    avg_no2: float | None = Field(default=None, ge=0.0)
    avg_o3: float | None = Field(default=None, ge=0.0)
    avg_so2: float | None = Field(default=None, ge=0.0)
    valid_hours: int = Field(..., ge=0, description="Count of hourly records with at least one valid measurement")
    expected_hours: int = Field(default=24, ge=1, description="Expected hourly slots for this local calendar day")
    missing_hours: int = Field(..., ge=0, description="Missing or fully-null hourly slots for this day")
    completeness_percent: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Percentage of expected hourly slots with valid data",
    )


class HistoricalPeriodSummary(BaseModel):
    """Aggregate statistics across the requested historical window (7, 14, or 30 days)."""

    days_requested: HistoricalRangeDays
    days_with_data: int = Field(..., ge=0)
    total_valid_hours: int = Field(..., ge=0)
    total_expected_hours: int = Field(..., ge=0)
    total_missing_hours: int = Field(..., ge=0)
    completeness_percent: float = Field(..., ge=0.0, le=100.0)
    avg_us_aqi: float | None = Field(default=None, ge=0.0, le=500.0)
    max_us_aqi: int | None = Field(default=None, ge=0, le=500)
    min_us_aqi: int | None = Field(default=None, ge=0, le=500)
    peak_aqi_timestamp: str | None = Field(
        default=None,
        description="Local timestamp of the highest US AQI observed in the historical period",
    )
    avg_pm2_5: float | None = Field(default=None, ge=0.0)
    max_pm2_5: float | None = Field(default=None, ge=0.0)
    avg_pm10: float | None = Field(default=None, ge=0.0)
    avg_no2: float | None = Field(default=None, ge=0.0)
    avg_o3: float | None = Field(default=None, ge=0.0)
    avg_so2: float | None = Field(default=None, ge=0.0)
    days_by_aqi_band: dict[str, int] = Field(
        default_factory=dict,
        description="Count of local calendar days grouped by US EPA AQI category band",
    )


class HistoricalDataOriginMetadata(BaseModel):
    """Explicit transparency metadata distinguishing fresh fetch, cache, and persisted SQLite records."""

    storage_origin: HistoricalStorageOrigin = Field(
        ...,
        description="Distinguishes fresh upstream retrieval, in-memory historical cache, or persisted SQLite records",
    )
    cache_hit: bool = Field(default=False, description="True only when served from the in-memory historical TTL cache")
    served_from_persistence: bool = Field(
        default=False,
        description="True when records were loaded from local SQLite persistence",
    )
    persisted_to_database: bool = Field(
        default=False,
        description="True when freshly retrieved records were successfully persisted to SQLite",
    )
    fallback_reason: str | None = Field(
        default=None,
        description="Populated if upstream refresh failed and valid persisted records were served instead",
    )


class HistoricalAirQualityResponse(BaseModel):
    """Response schema for GET /api/v1/air-quality/history."""

    location: LocationOption
    provider: str = Field(default="Open-Meteo Air Quality API (CAMS Global)")
    data_mode: Literal["historical_model"] = Field(default="historical_model")
    data_label: Literal["HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE"] = Field(
        default="HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE",
    )
    range_days: HistoricalRangeDays
    start_date: str = Field(..., description="First local calendar date (YYYY-MM-DD) in the window")
    end_date: str = Field(..., description="Last local calendar date (YYYY-MM-DD) in the window")
    timezone: str
    retrieval_time: str = Field(..., description="ISO-8601 UTC timestamp of the underlying data retrieval")
    units: AirQualityUnits = Field(default_factory=AirQualityUnits)
    hourly_records: list[HistoricalHourlyRecord] = Field(default_factory=list)
    daily_summaries: list[DailyHistoricalSummary] = Field(default_factory=list)
    period_summary: HistoricalPeriodSummary
    data_completeness_percent: float = Field(..., ge=0.0, le=100.0)
    origin: HistoricalDataOriginMetadata
    provenance: DataProvenance
    attribution: DataAttribution = Field(default_factory=DataAttribution)
    is_demo_data: Literal[False] = Field(default=False)
    disclaimer: str = Field(
        default=(
            "HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE: These historical time series are "
            "atmospheric composition model outputs from the Open-Meteo Air Quality API using Copernicus "
            "Atmosphere Monitoring Service (CAMS Global) data (spatial resolution ~0.4° / ~45 km, "
            "3-hourly native model output interpolated to 1-hourly API timestamps). They are not physical "
            "roadside monitoring station measurements, do not establish causal explanations for spikes, "
            "and preserve null/missing measurements without zero-filling or demo substitution."
        ),
    )


class CityHistoricalComparisonItem(BaseModel):
    """Per-city summary entry inside GET /api/v1/air-quality/history/compare."""

    location: LocationOption
    status: CityHistoryStatus
    data_label: str = Field(
        ...,
        description="Either 'HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE' or 'DATA UNAVAILABLE'",
    )
    retrieval_time: str | None = None
    origin: HistoricalDataOriginMetadata | None = None
    period_summary: HistoricalPeriodSummary | None = None
    daily_summaries: list[DailyHistoricalSummary] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    is_demo_data: Literal[False] = Field(default=False)


class HistoricalCityComparisonResponse(BaseModel):
    """Response schema for GET /api/v1/air-quality/history/compare."""

    range_days: HistoricalRangeDays
    data_mode: Literal["historical_model"] = Field(default="historical_model")
    data_label: Literal["HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE"] = Field(
        default="HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE",
    )
    generated_at: str = Field(..., description="ISO-8601 UTC timestamp when comparison response was assembled")
    cities_available: int = Field(..., ge=0)
    cities_unavailable: int = Field(..., ge=0)
    cities: list[CityHistoricalComparisonItem]
    units: AirQualityUnits = Field(default_factory=AirQualityUnits)
    attribution: DataAttribution = Field(default_factory=DataAttribution)
    is_demo_data: Literal[False] = Field(default=False)
    disclaimer: str = Field(
        default=(
            "HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE: Multi-city historical comparison uses "
            "Open-Meteo CAMS Global (~0.4° / ~45 km, 3-hourly native resolution) model outputs aggregated "
            "in each city's configured local timezone. Unavailable cities are explicitly flagged and are "
            "never replaced with demo data."
        ),
    )
