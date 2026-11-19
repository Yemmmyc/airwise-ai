"""Pydantic v2 response schemas for the Open-Meteo Air Quality API integration."""

from typing import Literal
from pydantic import BaseModel, Field
from app.schemas.dashboard import AqiBand, LocationOption


AirQualityDataMode = Literal["live_model"]
ValueAvailabilityStatus = Literal["available", "unavailable"]
HourlyPointClassification = Literal["historical_model", "current_model", "hourly_forecast"]


class AirQualityUnits(BaseModel):
    """Normalized measurement units returned by the air quality provider."""

    us_aqi: str = Field(default="US AQI", description="Unit label for US EPA Air Quality Index")
    pm2_5: str = Field(default="µg/m³", description="Unit for fine particulate matter (<2.5 µm)")
    pm10: str = Field(default="µg/m³", description="Unit for coarse particulate matter (<10 µm)")
    nitrogen_dioxide: str = Field(default="µg/m³", description="Unit for nitrogen dioxide (NO2)")
    ozone: str = Field(default="µg/m³", description="Unit for ground-level ozone (O3)")
    sulphur_dioxide: str = Field(default="µg/m³", description="Unit for sulphur dioxide (SO2)")


class PollutantMeasurement(BaseModel):
    """Normalized single pollutant measurement with explicit availability tracking."""

    code: Literal["PM2.5", "PM10", "NO2", "O3", "SO2"] = Field(..., description="Short chemical/particulate code")
    parameter: str = Field(..., description="Open-Meteo parameter key")
    name: str = Field(..., description="Full pollutant name")
    value: float | None = Field(
        default=None,
        ge=0.0,
        description="Normalized non-negative concentration value, or None if unavailable from provider",
    )
    unit: str = Field(..., description="Measurement unit (e.g. µg/m³)")
    status: ValueAvailabilityStatus = Field(
        ...,
        description="Explicit indicator of whether this variable was available or unavailable in the model output",
    )


class AqiMeasurement(BaseModel):
    """US AQI value reported directly by Open-Meteo without synthetic recalculation."""

    value: int | None = Field(
        default=None,
        ge=0,
        le=500,
        description="US AQI integer value provided directly by Open-Meteo, or None if unavailable",
    )
    standard: Literal["US EPA AQI (Open-Meteo Model Output)"] = Field(
        default="US EPA AQI (Open-Meteo Model Output)",
        description="Official AQI scale standard used by the provider",
    )
    unit: str = Field(default="US AQI", description="Unit label for AQI")
    band: AqiBand | None = Field(
        default=None,
        description="Standard US EPA AQI category band corresponding to the provider's us_aqi value",
    )
    status: ValueAvailabilityStatus = Field(
        ...,
        description="Whether us_aqi was available in the Open-Meteo response",
    )


class CurrentModelConditions(BaseModel):
    """Current atmospheric model conditions block from Open-Meteo (`current`)."""

    classification: Literal["current_model"] = Field(
        default="current_model",
        description="Explicitly identifies this block as current model conditions",
    )
    observation_time: str = Field(
        ...,
        description="Provider current model observation/analysis timestamp in location timezone",
    )
    interval_seconds: int | None = Field(
        default=None,
        description="API response aggregation interval in seconds reported by Open-Meteo (interpolated to 3600s)",
    )
    aqi: AqiMeasurement = Field(..., description="Current model US AQI")
    pm2_5: PollutantMeasurement = Field(..., description="Current model PM2.5")
    pm10: PollutantMeasurement = Field(..., description="Current model PM10")
    no2: PollutantMeasurement = Field(..., description="Current model Nitrogen Dioxide (NO2)")
    o3: PollutantMeasurement = Field(..., description="Current model Ozone (O3)")
    so2: PollutantMeasurement = Field(..., description="Current model Sulphur Dioxide (SO2)")


class HourlyModelPoint(BaseModel):
    """Single hourly atmospheric model data point with explicit temporal classification."""

    classification: HourlyPointClassification = Field(
        ...,
        description=(
            "Explicit temporal classification relative to current model observation time: "
            "'historical_model' (< observation_time), 'current_model' (== observation_time), "
            "or 'hourly_forecast' (> observation_time)"
        ),
    )
    time: str = Field(..., description="Hourly model timestamp in the location's configured timezone")
    us_aqi: int | None = Field(default=None, ge=0, le=500, description="Hourly model US AQI")
    pm2_5: float | None = Field(default=None, ge=0.0, description="Hourly model PM2.5")
    pm10: float | None = Field(default=None, ge=0.0, description="Hourly model PM10")
    no2: float | None = Field(default=None, ge=0.0, description="Hourly model NO2")
    o3: float | None = Field(default=None, ge=0.0, description="Hourly model O3")
    so2: float | None = Field(default=None, ge=0.0, description="Hourly model SO2")


class HourlyForecastPoint(HourlyModelPoint):
    """Future-only hourly atmospheric model forecast point (strictly later than observation_time)."""

    classification: Literal["hourly_forecast"] = Field(
        default="hourly_forecast",
        description="Strictly future hourly model forecast point (timestamp > current model observation_time)",
    )


class HourlyForecastSeries(BaseModel):
    """Strictly future hourly atmospheric model forecast series (> current observation_time).

    Historical and current-hour points are never included in `points` so callers are
    never misled into treating past model outputs as future forecasts.
    """

    classification: Literal["hourly_forecast"] = Field(
        default="hourly_forecast",
        description="Explicitly marks this collection as future-only hourly model forecast points",
    )
    hours_returned: int = Field(
        ...,
        ge=0,
        description="Number of future forecast entries (> observation_time) returned",
    )
    points: list[HourlyForecastPoint] = Field(
        default_factory=list,
        description="Chronological future-only hourly model forecast points (> observation_time)",
    )
    historical_hours_count: int = Field(
        default=0,
        ge=0,
        description="Count of earlier same-day hourly model points (< observation_time) excluded from forecasts",
    )
    historical_points: list[HourlyModelPoint] = Field(
        default_factory=list,
        description="Earlier hourly model points (< observation_time) explicitly classified as 'historical_model'",
    )
    current_hour_point: HourlyModelPoint | None = Field(
        default=None,
        description="Hourly series point matching current observation_time classified as 'current_model'",
    )


class CamsGlobalModelMetadata(BaseModel):
    """Scientific metadata describing the CAMS Global atmospheric model domain."""

    domain: str = Field(
        default="cams_global",
        description="Open-Meteo domain identifier for Copernicus Atmosphere Monitoring Service Global",
    )
    spatial_resolution: str = Field(
        default="Approximately 0.4° (~45 km)",
        description="Horizontal spatial grid resolution of CAMS Global",
    )
    source_temporal_resolution: str = Field(
        default="3-hourly underlying atmospheric model output",
        description="Native temporal resolution of the underlying CAMS Global model archive",
    )
    api_timestamp_interval: str = Field(
        default=(
            "1-hourly API response timestamps (interpolated by Open-Meteo from 3-hourly CAMS Global model fields; "
            "not independent hourly physical sensor measurements)"
        ),
        description="Distinction between 1-hourly API response timestamps and 3-hourly native model resolution",
    )
    forecast_availability: str = Field(
        default="Up to 5 days, subject to provider availability",
        description="Maximum forecast horizon offered by the CAMS Global provider",
    )


class DataAttribution(BaseModel):
    """Mandatory data source and scientific attribution for frontend and API consumers."""

    provider_attribution: str = Field(
        default="Weather and air quality data by Open-Meteo.com (https://open-meteo.com/en/docs/air-quality-api)",
        description="Primary API provider attribution statement",
    )
    cams_attribution: str = Field(
        default=(
            "Contains modified Copernicus Atmosphere Monitoring Service (CAMS) information "
            "(https://atmosphere.copernicus.eu/). Neither the European Commission nor ECMWF "
            "is responsible for any use that may be made of the Copernicus information or data it contains."
        ),
        description="Copernicus Atmosphere Monitoring Service (CAMS) attribution notice",
    )
    sources: list[str] = Field(
        default_factory=lambda: [
            "Open-Meteo Air Quality API",
            "Copernicus Atmosphere Monitoring Service (CAMS) Global",
        ],
        description="List of attributed upstream data sources",
    )


class DataProvenance(BaseModel):
    """Detailed provenance, model metadata, and attribution for Open-Meteo model data."""

    data_label: Literal["LIVE PROVIDER DATA — MODEL-BASED ESTIMATE"] = Field(
        default="LIVE PROVIDER DATA — MODEL-BASED ESTIMATE",
        description="Mandatory transparency label distinguishing model output from physical station telemetry",
    )
    provider_name: str = Field(default="Open-Meteo Air Quality API", description="External data provider name")
    endpoint_url: str = Field(
        default="https://air-quality-api.open-meteo.com/v1/air-quality",
        description="Upstream provider endpoint",
    )
    model_domain: str = Field(
        default="cams_global",
        description="Atmospheric model domain queried (Copernicus Atmosphere Monitoring Service Global)",
    )
    spatial_resolution: str = Field(
        default="Approximately 0.4° (~45 km)",
        description="Spatial resolution of CAMS Global",
    )
    source_temporal_resolution: str = Field(
        default="3-hourly underlying atmospheric model output",
        description="Native temporal resolution of CAMS Global",
    )
    api_timestamp_interval: str = Field(
        default=(
            "1-hourly API response timestamps (interpolated from 3-hourly CAMS Global model output; "
            "not hourly independent physical measurements)"
        ),
        description="Explanation of API hourly interval vs native 3-hourly model output",
    )
    forecast_availability: str = Field(
        default="Up to 5 days, subject to provider availability",
        description="Forecast horizon availability for CAMS Global",
    )
    model_metadata: CamsGlobalModelMetadata = Field(
        default_factory=CamsGlobalModelMetadata,
        description="Structured CAMS Global spatial, temporal, and forecast horizon metadata",
    )
    attribution: DataAttribution = Field(
        default_factory=DataAttribution,
        description="Structured attribution for Open-Meteo Air Quality API and Copernicus CAMS",
    )
    methodology: str = Field(
        default=(
            "Global atmospheric composition model reanalysis and forecast from the Copernicus Atmosphere "
            "Monitoring Service (CAMS Global, spatial resolution approximately 0.4° / ~45 km, underlying "
            "source temporal resolution 3-hourly, interpolated to 1-hourly API timestamps, forecast availability "
            "up to 5 days subject to provider availability). Not direct physical roadside monitoring station "
            "measurements and not hourly independent physical sensor readings."
        ),
        description="Scientific methodology description",
    )
    is_physical_station_measurement: Literal[False] = Field(
        default=False,
        description="Always False because Open-Meteo outputs gridded atmospheric model estimates",
    )
    is_demo_data: Literal[False] = Field(
        default=False,
        description="Always False for live provider responses; demo values are never mixed into this payload",
    )
    cache_hit: bool = Field(
        default=False,
        description="True if served from the short-lived in-memory provider response cache",
    )
    provider_latitude: float | None = Field(
        default=None,
        description="Model grid cell center latitude returned by Open-Meteo",
    )
    provider_longitude: float | None = Field(
        default=None,
        description="Model grid cell center longitude returned by Open-Meteo",
    )


class AirQualityResponse(BaseModel):
    """Typed response contract for GET /api/v1/air-quality."""

    location: LocationOption = Field(..., description="Configured urban location metadata")
    provider: str = Field(
        default="Open-Meteo Air Quality API (CAMS Global)",
        description="Provider identifier",
    )
    data_mode: AirQualityDataMode = Field(
        default="live_model",
        description="Explicit data mode distinguishing live model estimates from demo data",
    )
    data_label: Literal["LIVE PROVIDER DATA — MODEL-BASED ESTIMATE"] = Field(
        default="LIVE PROVIDER DATA — MODEL-BASED ESTIMATE",
        description="Top-level transparency banner label",
    )
    observation_time: str = Field(
        ...,
        description="Provider's current model observation/analysis timestamp in the configured location timezone",
    )
    retrieval_time: str = Field(
        ...,
        description="ISO-8601 UTC timestamp when AIRWISE AI retrieved or validated this payload",
    )
    timezone: str = Field(..., description="IANA timezone reported by the provider for the timestamps")
    timezone_abbreviation: str | None = Field(
        default=None,
        description="Timezone abbreviation reported by Open-Meteo (e.g. WAT, EAT, GMT)",
    )
    aqi: AqiMeasurement = Field(
        ...,
        description="US AQI value and standard reported directly by Open-Meteo current model conditions",
    )
    pm2_5: PollutantMeasurement = Field(..., description="Current model PM2.5 concentration")
    pm10: PollutantMeasurement = Field(..., description="Current model PM10 concentration")
    no2: PollutantMeasurement = Field(..., description="Current model Nitrogen Dioxide (NO2) concentration")
    o3: PollutantMeasurement = Field(..., description="Current model Ozone (O3) concentration")
    so2: PollutantMeasurement = Field(..., description="Current model Sulphur Dioxide (SO2) concentration")
    units: AirQualityUnits = Field(..., description="Normalized units for AQI and each pollutant")
    current_conditions: CurrentModelConditions = Field(
        ...,
        description="Structured current model conditions block (classification='current_model')",
    )
    hourly_forecast: HourlyForecastSeries = Field(
        ...,
        description=(
            "Strictly future hourly model forecast series (timestamps > observation_time), with "
            "historical (< observation_time) and current (== observation_time) points explicitly separated"
        ),
    )
    hourly_timeline: list[HourlyModelPoint] = Field(
        default_factory=list,
        description=(
            "Complete chronological hourly model timeline with each point explicitly classified as "
            "'historical_model', 'current_model', or 'hourly_forecast' using timezone-aware comparisons"
        ),
    )
    provenance: DataProvenance = Field(
        ...,
        description="Data provenance, CAMS Global model metadata, and Open-Meteo/CAMS attribution",
    )
    attribution: DataAttribution = Field(
        default_factory=DataAttribution,
        description="Top-level attribution for Open-Meteo Air Quality API and Copernicus CAMS data",
    )
    disclaimer: str = Field(
        default=(
            "LIVE PROVIDER DATA — MODEL-BASED ESTIMATE: These values are atmospheric composition model outputs "
            "from the Open-Meteo Air Quality API using Copernicus Atmosphere Monitoring Service (CAMS Global) data "
            "(spatial resolution ~0.4° / 45 km, native 3-hourly model output interpolated to 1-hourly API timestamps). "
            "They are not direct measurements from physical roadside monitoring stations and are not hourly "
            "independent physical measurements. Unavailable variables are reported as null/unavailable and are "
            "never filled with demo data."
        ),
        description="Explanatory disclaimer regarding model-based estimates, resolution, and attribution",
    )
