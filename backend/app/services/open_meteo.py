"""Dedicated Open-Meteo Air Quality API provider service.

Fetches, validates, normalizes, and caches model-based air quality estimates
from the official Open-Meteo Air Quality API:
https://air-quality-api.open-meteo.com/v1/air-quality

Data Integrity Rules:
- All values are explicitly labelled 'LIVE PROVIDER DATA — MODEL-BASED ESTIMATE'.
- Uses the US AQI ('us_aqi') directly from Open-Meteo; never invents an AQI calculation.
- Uses timezone-aware datetime comparisons to classify hourly points relative to
  the current model observation timestamp:
    * 'historical_model' (< observation_time)
    * 'current_model'    (== observation_time)
    * 'hourly_forecast'  (> observation_time)
- Never classifies historical or current points as future forecasts.
- If no future forecast points exist, returns an empty forecast collection.
- Accurately documents CAMS Global resolution (~0.4° / 45 km, 3-hourly source temporal
  resolution interpolated to 1-hourly API timestamps, up to 5-day forecast horizon)
  and attributes both Open-Meteo Air Quality API and Copernicus CAMS.
- Missing or null variables are reported individually with value=None and status='unavailable'.
- Never substitutes demo values into live provider responses.
- Never caches error responses.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.core.config import Settings, get_settings
from app.core.logging_config import get_logger
from app.schemas.air_quality import (
    AirQualityResponse,
    AirQualityUnits,
    AqiMeasurement,
    CurrentModelConditions,
    DataAttribution,
    DataProvenance,
    HourlyForecastPoint,
    HourlyForecastSeries,
    HourlyModelPoint,
    HourlyPointClassification,
    PollutantMeasurement,
)
from app.schemas.dashboard import AqiBand, LocationOption
from app.services.demo_data import AVAILABLE_LOCATIONS, get_location_by_id

OPEN_METEO_VARIABLES: tuple[str, ...] = (
    "us_aqi",
    "pm2_5",
    "pm10",
    "nitrogen_dioxide",
    "ozone",
    "sulphur_dioxide",
)

logger = get_logger(__name__)

# Known fixed UTC offsets for the configured African IANA timezones as a fallback
# in case the host Python environment lacks the optional tzdata package on Windows.
_FALLBACK_IANA_OFFSETS: dict[str, timezone] = {
    "Africa/Lagos": timezone(timedelta(hours=1), name="WAT"),
    "Africa/Nairobi": timezone(timedelta(hours=3), name="EAT"),
    "Africa/Accra": timezone(timedelta(hours=0), name="GMT"),
    "UTC": timezone.utc,
    "Etc/UTC": timezone.utc,
    "GMT": timezone.utc,
}


class OpenMeteoProviderError(Exception):
    """Structured base exception for Open-Meteo provider failures."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "provider_error",
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code


class InvalidLocationError(OpenMeteoProviderError):
    """Raised when a caller requests an unconfigured location_id."""

    def __init__(self, location_id: str) -> None:
        supported = ", ".join(loc.id for loc in AVAILABLE_LOCATIONS)
        super().__init__(
            f"Unsupported location_id '{location_id}'. Supported locations are: {supported}.",
            error_code="invalid_location_id",
            status_code=404,
        )


class OpenMeteoTimeoutError(OpenMeteoProviderError):
    """Raised when the Open-Meteo API request times out."""

    def __init__(self, timeout_seconds: float) -> None:
        super().__init__(
            f"Open-Meteo Air Quality API request timed out after {timeout_seconds:.1f}s. "
            "No demo values were substituted.",
            error_code="provider_timeout",
            status_code=504,
        )


class OpenMeteoUpstreamHttpError(OpenMeteoProviderError):
    """Raised when Open-Meteo returns a non-200 HTTP response or network error."""

    def __init__(self, message: str, upstream_status: int | None = None) -> None:
        detail = (
            f"Open-Meteo Air Quality API returned HTTP {upstream_status}."
            if upstream_status is not None
            else message
        )
        super().__init__(
            f"{detail} Live model data is currently unavailable; no demo values were substituted.",
            error_code="provider_upstream_http_error",
            status_code=502,
        )


class OpenMeteoValidationError(OpenMeteoProviderError):
    """Raised when the Open-Meteo payload is malformed or missing required structure."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Invalid response payload received from Open-Meteo Air Quality API: {reason}",
            error_code="provider_invalid_payload",
            status_code=502,
        )


class _CacheEntry:
    """In-memory TTL cache entry for validated AirQualityResponse objects."""

    __slots__ = ("expires_at", "response")

    def __init__(self, response: AirQualityResponse, expires_at: float) -> None:
        self.response = response
        self.expires_at = expires_at


_RESPONSE_CACHE: dict[str, _CacheEntry] = {}


def clear_open_meteo_cache() -> None:
    """Clear the in-memory Open-Meteo response cache (useful for deterministic testing)."""
    _RESPONSE_CACHE.clear()


def resolve_timezone(tz_name: str, utc_offset_seconds: int | None = None) -> tzinfo:
    """Resolve an IANA timezone name or Open-Meteo utc_offset_seconds into a tzinfo object."""
    cleaned = (tz_name or "").strip()
    if cleaned:
        try:
            return ZoneInfo(cleaned)
        except ZoneInfoNotFoundError:
            if cleaned in _FALLBACK_IANA_OFFSETS:
                return _FALLBACK_IANA_OFFSETS[cleaned]

    if utc_offset_seconds is not None and not isinstance(utc_offset_seconds, bool):
        try:
            offset_sec = int(utc_offset_seconds)
            return timezone(timedelta(seconds=offset_sec))
        except (TypeError, ValueError):
            pass

    if cleaned in _FALLBACK_IANA_OFFSETS:
        return _FALLBACK_IANA_OFFSETS[cleaned]
    return timezone.utc


def parse_aware_provider_datetime(
    timestamp_str: str,
    default_tz: tzinfo,
    *,
    field_name: str = "time",
) -> datetime:
    """Parse an Open-Meteo ISO-8601 timestamp into a timezone-aware datetime.

    - If the string already includes an explicit offset or 'Z' (e.g. '2026-11-18T20:00Z'
      or '2026-11-18T23:00+03:00'), its explicit timezone is preserved.
    - If the string is naive (e.g. '2026-11-18T21:00' as returned by Open-Meteo when
      `timezone=Africa/Lagos` is requested), `default_tz` is attached.
    """
    if not isinstance(timestamp_str, str) or not timestamp_str.strip():
        raise OpenMeteoValidationError(f"Field '{field_name}' must be a non-empty ISO-8601 timestamp string.")

    raw = timestamp_str.strip()
    normalized = f"{raw[:-1]}+00:00" if raw.endswith(("Z", "z")) else raw

    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise OpenMeteoValidationError(
            f"Field '{field_name}' value '{raw}' is not a valid ISO-8601 timestamp."
        ) from exc

    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=default_tz)
    return dt


def classify_hourly_timestamp(
    point_dt: datetime,
    observation_dt: datetime,
) -> HourlyPointClassification:
    """Classify an hourly timestamp relative to the current model observation timestamp.

    Uses timezone-aware datetime comparison (comparing exact instants in time even if
    the two datetimes carry different timezone offsets):
    - 'historical_model': point_dt < observation_dt
    - 'current_model':    point_dt == observation_dt
    - 'hourly_forecast':  point_dt > observation_dt
    """
    if point_dt.tzinfo is None or observation_dt.tzinfo is None:
        raise ValueError("Timestamp comparison requires timezone-aware datetimes.")

    if point_dt < observation_dt:
        return "historical_model"
    if point_dt == observation_dt:
        return "current_model"
    return "hourly_forecast"


def classify_us_aqi_band(aqi_value: int | None) -> AqiBand | None:
    """Map an official US EPA AQI integer (0-500) to its standard EPA category name.

    Does not calculate AQI; only classifies the integer us_aqi provided by Open-Meteo.
    """
    if aqi_value is None:
        return None
    if aqi_value <= 50:
        return "Good"
    if aqi_value <= 100:
        return "Moderate"
    if aqi_value <= 150:
        return "Unhealthy for Sensitive Groups"
    if aqi_value <= 200:
        return "Unhealthy"
    if aqi_value <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def _normalize_unit(raw_unit: Any, default_unit: str = "µg/m³") -> str:
    """Normalize unit strings from Open-Meteo while preserving standard representation."""
    if not isinstance(raw_unit, str) or not raw_unit.strip():
        return default_unit
    cleaned = raw_unit.strip()
    if cleaned.lower() in {"ug/m3", "μg/m³", "µg/m³", "ug/m^3"}:
        return "µg/m³"
    if cleaned.lower() in {"usaqi", "us aqi", "aqi"}:
        return "US AQI"
    return cleaned


def _parse_optional_float(raw_value: Any, field_name: str) -> float | None:
    """Validate and normalize an optional non-negative float pollutant concentration."""
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        raise OpenMeteoValidationError(f"Field '{field_name}' contained a boolean instead of a number.")
    try:
        numeric = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise OpenMeteoValidationError(
            f"Field '{field_name}' contained a non-numeric value."
        ) from exc

    if not math.isfinite(numeric):
        raise OpenMeteoValidationError(f"Field '{field_name}' contained a non-finite float.")
    if numeric < 0.0:
        raise OpenMeteoValidationError(f"Field '{field_name}' contained a negative concentration.")
    return round(numeric, 2)


def _parse_optional_aqi_int(raw_value: Any, field_name: str = "us_aqi") -> int | None:
    """Validate and normalize the Open-Meteo US AQI value without inventing a calculation."""
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        raise OpenMeteoValidationError(f"Field '{field_name}' contained a boolean instead of an integer.")
    try:
        numeric = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise OpenMeteoValidationError(
            f"Field '{field_name}' contained a non-numeric value."
        ) from exc

    if not math.isfinite(numeric):
        raise OpenMeteoValidationError(f"Field '{field_name}' contained a non-finite number.")
    rounded = int(round(numeric))
    if rounded < 0 or rounded > 500:
        raise OpenMeteoValidationError(
            f"Field '{field_name}' value {rounded} is outside the valid 0-500 US AQI range."
        )
    return rounded


def _build_pollutant_measurement(
    *,
    code: str,
    parameter: str,
    name: str,
    raw_value: Any,
    unit: str,
) -> PollutantMeasurement:
    """Build a typed PollutantMeasurement handling missing/null fields individually."""
    parsed = _parse_optional_float(raw_value, parameter)
    return PollutantMeasurement(
        code=code,  # type: ignore[arg-type]
        parameter=parameter,
        name=name,
        value=parsed,
        unit=unit,
        status="available" if parsed is not None else "unavailable",
    )


def _parse_hourly_series(
    hourly_block: Any,
    *,
    observation_dt: datetime,
    provider_tz: tzinfo,
    max_forecast_hours: int,
) -> tuple[HourlyForecastSeries, list[HourlyModelPoint]]:
    """Parse, validate, and temporally classify the Open-Meteo 'hourly' model series.

    Each hourly timestamp is parsed as a timezone-aware datetime in `provider_tz` (or its
    explicit offset) and compared against `observation_dt`:
      - earlier than observation_dt -> 'historical_model' (never placed in forecast points)
      - equal to observation_dt     -> 'current_model'    (never placed in forecast points)
      - later than observation_dt   -> 'hourly_forecast'  (placed in forecast points, up to max_forecast_hours)
    """
    if hourly_block is None:
        return HourlyForecastSeries(hours_returned=0, points=[]), []

    if not isinstance(hourly_block, dict):
        raise OpenMeteoValidationError("The 'hourly' field must be a JSON object when present.")

    times = hourly_block.get("time")
    if times is None:
        return HourlyForecastSeries(hours_returned=0, points=[]), []
    if not isinstance(times, list) or not all(isinstance(t, str) and t.strip() for t in times):
        raise OpenMeteoValidationError("The 'hourly.time' field must be a list of timestamp strings.")

    def _get_series_value(key: str, idx: int) -> Any:
        series = hourly_block.get(key)
        if series is None:
            return None
        if not isinstance(series, list):
            raise OpenMeteoValidationError(f"The 'hourly.{key}' field must be a list when present.")
        if idx >= len(series):
            return None
        return series[idx]

    future_forecast_points: list[HourlyForecastPoint] = []
    historical_points: list[HourlyModelPoint] = []
    current_hour_point: HourlyModelPoint | None = None
    timeline_points: list[HourlyModelPoint] = []

    max_future = max(0, max_forecast_hours)

    for i, raw_time in enumerate(times):
        clean_time = raw_time.strip()
        point_dt = parse_aware_provider_datetime(
            clean_time,
            provider_tz,
            field_name=f"hourly.time[{i}]",
        )
        classification = classify_hourly_timestamp(point_dt, observation_dt)

        us_aqi_val = _parse_optional_aqi_int(_get_series_value("us_aqi", i), f"hourly.us_aqi[{i}]")
        pm2_5_val = _parse_optional_float(_get_series_value("pm2_5", i), f"hourly.pm2_5[{i}]")
        pm10_val = _parse_optional_float(_get_series_value("pm10", i), f"hourly.pm10[{i}]")
        no2_val = _parse_optional_float(
            _get_series_value("nitrogen_dioxide", i), f"hourly.nitrogen_dioxide[{i}]"
        )
        o3_val = _parse_optional_float(_get_series_value("ozone", i), f"hourly.ozone[{i}]")
        so2_val = _parse_optional_float(
            _get_series_value("sulphur_dioxide", i), f"hourly.sulphur_dioxide[{i}]"
        )

        model_point = HourlyModelPoint(
            classification=classification,
            time=clean_time,
            us_aqi=us_aqi_val,
            pm2_5=pm2_5_val,
            pm10=pm10_val,
            no2=no2_val,
            o3=o3_val,
            so2=so2_val,
        )

        if classification == "historical_model":
            historical_points.append(model_point)
            timeline_points.append(model_point)
        elif classification == "current_model":
            current_hour_point = model_point
            timeline_points.append(model_point)
        else:
            if len(future_forecast_points) < max_future:
                forecast_point = HourlyForecastPoint(
                    classification="hourly_forecast",
                    time=clean_time,
                    us_aqi=us_aqi_val,
                    pm2_5=pm2_5_val,
                    pm10=pm10_val,
                    no2=no2_val,
                    o3=o3_val,
                    so2=so2_val,
                )
                future_forecast_points.append(forecast_point)
                timeline_points.append(model_point)

    forecast_series = HourlyForecastSeries(
        classification="hourly_forecast",
        hours_returned=len(future_forecast_points),
        points=future_forecast_points,
        historical_hours_count=len(historical_points),
        historical_points=historical_points,
        current_hour_point=current_hour_point,
    )
    return forecast_series, timeline_points


def build_query_params(location: LocationOption, settings: Settings) -> dict[str, str | float | int]:
    """Construct Open-Meteo Air Quality API query parameters for a configured location.

    Requests `forecast_days=2` so that even late in the evening local time (e.g. 22:00 WAT),
    genuine future hourly forecast points (> observation_time) are returned by Open-Meteo.
    """
    variables_csv = ",".join(OPEN_METEO_VARIABLES)
    params: dict[str, str | float | int] = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "current": variables_csv,
        "hourly": variables_csv,
        "timezone": location.timezone,
        "domains": settings.open_meteo_domains,
        "forecast_days": 2,
    }
    return params


def normalize_open_meteo_payload(
    payload: Any,
    *,
    location: LocationOption,
    settings: Settings,
    retrieval_time_iso: str | None = None,
    cache_hit: bool = False,
) -> AirQualityResponse:
    """Validate and normalize a raw Open-Meteo JSON dictionary into an AirQualityResponse."""
    if not isinstance(payload, dict):
        raise OpenMeteoValidationError("Root JSON payload must be an object.")

    if payload.get("error") is True:
        reason = payload.get("reason")
        safe_reason = str(reason) if isinstance(reason, str) and reason.strip() else "Upstream API error flag."
        raise OpenMeteoValidationError(safe_reason)

    current_block = payload.get("current")
    if not isinstance(current_block, dict):
        raise OpenMeteoValidationError("Missing or invalid 'current' model conditions object.")

    observation_time = current_block.get("time")
    if not isinstance(observation_time, str) or not observation_time.strip():
        raise OpenMeteoValidationError("Missing or invalid 'current.time' observation timestamp.")
    observation_time = observation_time.strip()

    provider_tz_str = payload.get("timezone")
    resolved_timezone_name = (
        provider_tz_str.strip()
        if isinstance(provider_tz_str, str) and provider_tz_str.strip()
        else location.timezone
    )
    raw_utc_offset = payload.get("utc_offset_seconds")
    utc_offset_seconds = (
        int(raw_utc_offset)
        if isinstance(raw_utc_offset, (int, float)) and not isinstance(raw_utc_offset, bool)
        else None
    )
    provider_tz = resolve_timezone(resolved_timezone_name, utc_offset_seconds=utc_offset_seconds)

    # Parse current.time into a timezone-aware datetime for temporal classification
    observation_dt = parse_aware_provider_datetime(
        observation_time,
        provider_tz,
        field_name="current.time",
    )

    raw_interval = current_block.get("interval")
    interval_seconds: int | None = None
    if raw_interval is not None:
        if isinstance(raw_interval, bool) or not isinstance(raw_interval, (int, float)):
            raise OpenMeteoValidationError("Field 'current.interval' must be numeric when present.")
        interval_seconds = int(raw_interval)

    current_units_raw = payload.get("current_units")
    if current_units_raw is not None and not isinstance(current_units_raw, dict):
        raise OpenMeteoValidationError("Field 'current_units' must be an object when present.")
    hourly_units_raw = payload.get("hourly_units")
    if hourly_units_raw is not None and not isinstance(hourly_units_raw, dict):
        raise OpenMeteoValidationError("Field 'hourly_units' must be an object when present.")

    units_source: dict[str, Any] = {}
    if isinstance(hourly_units_raw, dict):
        units_source.update(hourly_units_raw)
    if isinstance(current_units_raw, dict):
        units_source.update(current_units_raw)

    units = AirQualityUnits(
        us_aqi=_normalize_unit(units_source.get("us_aqi"), default_unit="US AQI"),
        pm2_5=_normalize_unit(units_source.get("pm2_5"), default_unit="µg/m³"),
        pm10=_normalize_unit(units_source.get("pm10"), default_unit="µg/m³"),
        nitrogen_dioxide=_normalize_unit(units_source.get("nitrogen_dioxide"), default_unit="µg/m³"),
        ozone=_normalize_unit(units_source.get("ozone"), default_unit="µg/m³"),
        sulphur_dioxide=_normalize_unit(units_source.get("sulphur_dioxide"), default_unit="µg/m³"),
    )

    us_aqi_val = _parse_optional_aqi_int(current_block.get("us_aqi"), "current.us_aqi")
    aqi_measurement = AqiMeasurement(
        value=us_aqi_val,
        unit=units.us_aqi,
        band=classify_us_aqi_band(us_aqi_val),
        status="available" if us_aqi_val is not None else "unavailable",
    )

    pm2_5 = _build_pollutant_measurement(
        code="PM2.5",
        parameter="pm2_5",
        name="Fine Particulate Matter (<2.5 µm)",
        raw_value=current_block.get("pm2_5"),
        unit=units.pm2_5,
    )
    pm10 = _build_pollutant_measurement(
        code="PM10",
        parameter="pm10",
        name="Coarse Particulate Matter (<10 µm)",
        raw_value=current_block.get("pm10"),
        unit=units.pm10,
    )
    no2 = _build_pollutant_measurement(
        code="NO2",
        parameter="nitrogen_dioxide",
        name="Nitrogen Dioxide",
        raw_value=current_block.get("nitrogen_dioxide"),
        unit=units.nitrogen_dioxide,
    )
    o3 = _build_pollutant_measurement(
        code="O3",
        parameter="ozone",
        name="Ground-Level Ozone",
        raw_value=current_block.get("ozone"),
        unit=units.ozone,
    )
    so2 = _build_pollutant_measurement(
        code="SO2",
        parameter="sulphur_dioxide",
        name="Sulphur Dioxide",
        raw_value=current_block.get("sulphur_dioxide"),
        unit=units.sulphur_dioxide,
    )

    current_conditions = CurrentModelConditions(
        classification="current_model",
        observation_time=observation_time,
        interval_seconds=interval_seconds,
        aqi=aqi_measurement,
        pm2_5=pm2_5,
        pm10=pm10,
        no2=no2,
        o3=o3,
        so2=so2,
    )

    hourly_forecast, hourly_timeline = _parse_hourly_series(
        payload.get("hourly"),
        observation_dt=observation_dt,
        provider_tz=provider_tz,
        max_forecast_hours=settings.open_meteo_forecast_hours,
    )

    tz_abbrev_raw = payload.get("timezone_abbreviation")
    tz_abbrev = (
        tz_abbrev_raw.strip()
        if isinstance(tz_abbrev_raw, str) and tz_abbrev_raw.strip()
        else None
    )

    provider_lat: float | None = None
    if payload.get("latitude") is not None:
        try:
            provider_lat = float(payload["latitude"])
        except (TypeError, ValueError):
            provider_lat = None

    provider_lon: float | None = None
    if payload.get("longitude") is not None:
        try:
            provider_lon = float(payload["longitude"])
        except (TypeError, ValueError):
            provider_lon = None

    if retrieval_time_iso is not None:
        retrieval_dt = parse_aware_provider_datetime(
            retrieval_time_iso,
            timezone.utc,
            field_name="retrieval_time",
        )
        now_iso = retrieval_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    attribution = DataAttribution()
    provenance = DataProvenance(
        endpoint_url=settings.open_meteo_base_url,
        model_domain=settings.open_meteo_domains,
        attribution=attribution,
        cache_hit=cache_hit,
        provider_latitude=provider_lat,
        provider_longitude=provider_lon,
    )

    return AirQualityResponse(
        location=location,
        observation_time=observation_time,
        retrieval_time=now_iso,
        timezone=resolved_timezone_name,
        timezone_abbreviation=tz_abbrev,
        aqi=aqi_measurement,
        pm2_5=pm2_5,
        pm10=pm10,
        no2=no2,
        o3=o3,
        so2=so2,
        units=units,
        current_conditions=current_conditions,
        hourly_forecast=hourly_forecast,
        hourly_timeline=hourly_timeline,
        provenance=provenance,
        attribution=attribution,
    )


def fetch_open_meteo_air_quality(
    location_id: str = "lagos-ng",
    *,
    http_client: httpx.Client | None = None,
    use_cache: bool = True,
) -> AirQualityResponse:
    """Fetch and normalize Open-Meteo model air quality data for a configured location.

    - Reuses the single configured location registry (Lagos, Abuja, Nairobi, Accra).
    - Raises InvalidLocationError (404) if location_id is not recognized.
    - Uses a short-lived in-memory TTL cache for successful responses only.
    - Never caches errors and never substitutes demo values.
    """
    location = get_location_by_id(location_id)
    if location is None:
        raise InvalidLocationError(location_id)

    settings = get_settings()
    now_monotonic = time.monotonic()

    if use_cache and settings.open_meteo_cache_ttl_seconds > 0:
        cached = _RESPONSE_CACHE.get(location.id)
        if cached is not None and cached.expires_at > now_monotonic:
            cached_copy = cached.response.model_copy(deep=True)
            cached_copy.provenance.cache_hit = True
            return cached_copy

    params = build_query_params(location, settings)
    timeout = httpx.Timeout(
        connect=min(5.0, settings.open_meteo_timeout_seconds),
        read=settings.open_meteo_timeout_seconds,
        write=5.0,
        pool=5.0,
    )

    try:
        if http_client is not None:
            response = http_client.get(
                settings.open_meteo_base_url,
                params=params,
                timeout=timeout,
                headers={"Accept": "application/json"},
            )
        else:
            with httpx.Client(timeout=timeout) as client:
                response = client.get(
                    settings.open_meteo_base_url,
                    params=params,
                    headers={"Accept": "application/json"},
                )
    except httpx.TimeoutException as exc:
        logger.warning(
            "open_meteo_timeout location_id=%s timeout_s=%.1f",
            location.id,
            settings.open_meteo_timeout_seconds,
        )
        raise OpenMeteoTimeoutError(settings.open_meteo_timeout_seconds) from exc
    except httpx.HTTPError as exc:
        logger.warning(
            "open_meteo_http_error location_id=%s exc_type=%s",
            location.id,
            type(exc).__name__,
        )
        raise OpenMeteoUpstreamHttpError(
            "Unable to reach Open-Meteo Air Quality API over HTTP."
        ) from exc

    if response.status_code != 200:
        logger.warning(
            "open_meteo_upstream_non_200 location_id=%s upstream_status=%d",
            location.id,
            response.status_code,
        )
        raise OpenMeteoUpstreamHttpError(
            f"Open-Meteo returned HTTP {response.status_code}.",
            upstream_status=response.status_code,
        )

    try:
        raw_payload = response.json()
    except ValueError as exc:
        logger.warning(
            "open_meteo_invalid_json location_id=%s",
            location.id,
        )
        raise OpenMeteoValidationError("Response body was not valid JSON.") from exc

    normalized = normalize_open_meteo_payload(
        raw_payload,
        location=location,
        settings=settings,
        cache_hit=False,
    )

    if use_cache and settings.open_meteo_cache_ttl_seconds > 0:
        _RESPONSE_CACHE[location.id] = _CacheEntry(
            response=normalized,
            expires_at=now_monotonic + float(settings.open_meteo_cache_ttl_seconds),
        )

    return normalized
