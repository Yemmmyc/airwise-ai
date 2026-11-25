"""Dedicated Open-Meteo Historical Air Quality retrieval, aggregation, and caching service.

Implements Option B (Hybrid Architecture):
- On-demand Open-Meteo historical retrieval (`past_days=7|14|30`, `forecast_days=0`, `domains=cams_global`).
- Lightweight local SQLite persistence (`SQLiteHistoryStore`) with a bounded refresh policy.
- Dedicated in-memory historical TTL cache strictly separate from the live 300s cache.

Data Integrity Safeguards:
- Every record is explicitly classified as `historical_model`.
- Future timestamps (>= current UTC hour or > local end date) are strictly excluded.
- Null/missing measurements are preserved as None—never zero-filled or interpolated.
- Daily summaries aggregate strictly by local calendar day in the location's IANA timezone.
- Never silently mixes demo data into historical responses.
- Never reports cached or persisted records as a fresh upstream retrieval.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.logging_config import get_logger
from app.core.ttl_cache import SingleFlightTTLCache
from app.schemas.air_quality import AirQualityUnits, DataAttribution, DataProvenance
from app.schemas.dashboard import LocationOption
from app.schemas.history import (
    CityHistoricalComparisonItem,
    DailyHistoricalSummary,
    HistoricalAirQualityResponse,
    HistoricalCityComparisonResponse,
    HistoricalDataOriginMetadata,
    HistoricalHourlyRecord,
    HistoricalPeriodSummary,
    HistoricalRangeDays,
    HistoricalStorageOrigin,
)
from app.services.demo_data import AVAILABLE_LOCATIONS, get_location_by_id
from app.services.history_store import HistoryStoreError, SQLiteHistoryStore
from app.services.open_meteo import (
    OPEN_METEO_VARIABLES,
    InvalidLocationError,
    OpenMeteoProviderError,
    OpenMeteoTimeoutError,
    OpenMeteoUpstreamHttpError,
    OpenMeteoValidationError,
    _normalize_unit,
    _parse_optional_aqi_int,
    _parse_optional_float,
    classify_us_aqi_band,
    parse_aware_provider_datetime,
    resolve_timezone,
)

SUPPORTED_HISTORY_DAYS: tuple[int, ...] = (7, 14, 30)
logger = get_logger(__name__)


class InvalidHistoryRangeError(OpenMeteoProviderError):
    """Raised when a caller requests a `days` value outside {7, 14, 30}."""

    def __init__(self, days: int) -> None:
        super().__init__(
            f"Unsupported historical range '{days}'. Supported values for 'days' are: 7, 14, or 30.",
            error_code="invalid_history_range",
            status_code=422,
        )


_HISTORY_CACHE: SingleFlightTTLCache[
    tuple[str, int], HistoricalAirQualityResponse
] = SingleFlightTTLCache()


def clear_history_cache() -> None:
    """Clear the dedicated in-memory historical TTL cache safely (preserving per-key locks)."""
    _HISTORY_CACHE.clear()


def _get_history_store(settings: Settings) -> SQLiteHistoryStore:
    """Instantiate the modular SQLite history store from settings."""
    return SQLiteHistoryStore(settings.history_db_path)


def _compute_local_date_window(
    location: LocationOption,
    days: HistoricalRangeDays,
    now_utc: datetime,
) -> tuple[date, date, datetime, datetime]:
    """Compute the exact local calendar date window [start_date, end_date] for `days` completed past days.

    In the location's IANA timezone, `past_days=N` with `forecast_days=0` covers the N completed
    local calendar days ending yesterday (`local_today - 1 day`).
    """
    loc_tz = resolve_timezone(location.timezone)
    local_now = now_utc.astimezone(loc_tz)
    end_local_date = local_now.date() - timedelta(days=1)
    start_local_date = end_local_date - timedelta(days=days - 1)

    start_local_dt = datetime(
        start_local_date.year,
        start_local_date.month,
        start_local_date.day,
        0,
        0,
        0,
        tzinfo=loc_tz,
    )
    end_local_dt = datetime(
        end_local_date.year,
        end_local_date.month,
        end_local_date.day,
        23,
        59,
        59,
        tzinfo=loc_tz,
    )
    return (
        start_local_date,
        end_local_date,
        start_local_dt.astimezone(timezone.utc),
        end_local_dt.astimezone(timezone.utc),
    )


def build_history_query_params(
    location: LocationOption,
    days: HistoricalRangeDays,
    settings: Settings,
) -> dict[str, str | float | int]:
    """Construct Open-Meteo query parameters for genuine historical model retrieval."""
    variables_csv = ",".join(OPEN_METEO_VARIABLES)
    return {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "hourly": variables_csv,
        "timezone": location.timezone,
        "domains": settings.open_meteo_domains,
        "past_days": days,
        "forecast_days": 0,
    }


def _record_has_any_valid_measurement(rec: HistoricalHourlyRecord) -> bool:
    """Return True if at least one of the six environmental variables is non-null."""
    return any(
        val is not None
        for val in (rec.us_aqi, rec.pm2_5, rec.pm10, rec.no2, rec.o3, rec.so2)
    )


def _mean_or_none(values: list[float] | list[int]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def compute_daily_summaries(
    records: list[HistoricalHourlyRecord],
    *,
    location: LocationOption,
    start_date: date,
    end_date: date,
) -> list[DailyHistoricalSummary]:
    """Aggregate historical hourly records by local calendar day in the location's IANA timezone.

    - Converts each record's canonical UTC timestamp into `location.timezone` to determine its
      exact local calendar date (safe across UTC offsets and timezone boundaries).
    - Never zero-fills or interpolates missing hours.
    - Tracks valid_hours, expected_hours (24), missing_hours, and completeness_percent.
    """
    loc_tz = resolve_timezone(location.timezone)
    buckets: dict[str, list[HistoricalHourlyRecord]] = {}

    # Seed every expected local calendar date in [start_date, end_date]
    cursor = start_date
    ordered_dates: list[str] = []
    while cursor <= end_date:
        key = cursor.isoformat()
        ordered_dates.append(key)
        buckets[key] = []
        cursor += timedelta(days=1)

    for rec in records:
        utc_dt = parse_aware_provider_datetime(
            rec.timestamp_utc,
            timezone.utc,
            field_name="record.timestamp_utc",
        )
        local_date_str = utc_dt.astimezone(loc_tz).date().isoformat()
        if local_date_str in buckets:
            buckets[local_date_str].append(rec)

    summaries: list[DailyHistoricalSummary] = []
    for day_str in ordered_dates:
        day_records = buckets[day_str]
        valid_records = [r for r in day_records if _record_has_any_valid_measurement(r)]

        aqi_vals = [r.us_aqi for r in day_records if r.us_aqi is not None]
        pm25_vals = [r.pm2_5 for r in day_records if r.pm2_5 is not None]
        pm10_vals = [r.pm10 for r in day_records if r.pm10 is not None]
        no2_vals = [r.no2 for r in day_records if r.no2 is not None]
        o3_vals = [r.o3 for r in day_records if r.o3 is not None]
        so2_vals = [r.so2 for r in day_records if r.so2 is not None]

        expected_hours = 24
        valid_hours = min(expected_hours, len(valid_records))
        missing_hours = max(0, expected_hours - valid_hours)
        completeness = round((valid_hours / expected_hours) * 100.0, 1)

        avg_aqi = _mean_or_none(aqi_vals)
        dominant_band = (
            classify_us_aqi_band(int(round(avg_aqi))) if avg_aqi is not None else None
        )

        summaries.append(
            DailyHistoricalSummary(
                date=day_str,
                timezone=location.timezone,
                avg_us_aqi=avg_aqi,
                max_us_aqi=max(aqi_vals) if aqi_vals else None,
                min_us_aqi=min(aqi_vals) if aqi_vals else None,
                dominant_aqi_band=dominant_band,
                avg_pm2_5=_mean_or_none(pm25_vals),
                max_pm2_5=round(max(pm25_vals), 2) if pm25_vals else None,
                avg_pm10=_mean_or_none(pm10_vals),
                avg_no2=_mean_or_none(no2_vals),
                avg_o3=_mean_or_none(o3_vals),
                avg_so2=_mean_or_none(so2_vals),
                valid_hours=valid_hours,
                expected_hours=expected_hours,
                missing_hours=missing_hours,
                completeness_percent=completeness,
            )
        )

    return summaries


def compute_period_summary(
    records: list[HistoricalHourlyRecord],
    daily_summaries: list[DailyHistoricalSummary],
    *,
    days: HistoricalRangeDays,
) -> HistoricalPeriodSummary:
    """Compute overall period summary statistics without fabricating or zero-filling nulls."""
    total_expected = sum(d.expected_hours for d in daily_summaries)
    total_valid = sum(d.valid_hours for d in daily_summaries)
    total_missing = sum(d.missing_hours for d in daily_summaries)
    completeness = (
        round((total_valid / total_expected) * 100.0, 1) if total_expected > 0 else 0.0
    )

    aqi_pairs = [(r.local_time, r.us_aqi) for r in records if r.us_aqi is not None]
    aqi_vals = [val for _, val in aqi_pairs]
    pm25_vals = [r.pm2_5 for r in records if r.pm2_5 is not None]
    pm10_vals = [r.pm10 for r in records if r.pm10 is not None]
    no2_vals = [r.no2 for r in records if r.no2 is not None]
    o3_vals = [r.o3 for r in records if r.o3 is not None]
    so2_vals = [r.so2 for r in records if r.so2 is not None]

    peak_timestamp: str | None = None
    max_aqi: int | None = None
    if aqi_pairs:
        peak_timestamp, max_aqi = max(aqi_pairs, key=lambda pair: pair[1])

    days_by_band: dict[str, int] = {}
    for day in daily_summaries:
        if day.dominant_aqi_band is not None:
            days_by_band[day.dominant_aqi_band] = (
                days_by_band.get(day.dominant_aqi_band, 0) + 1
            )

    return HistoricalPeriodSummary(
        days_requested=days,
        days_with_data=sum(1 for d in daily_summaries if d.valid_hours > 0),
        total_valid_hours=total_valid,
        total_expected_hours=total_expected,
        total_missing_hours=total_missing,
        completeness_percent=completeness,
        avg_us_aqi=_mean_or_none(aqi_vals),
        max_us_aqi=max_aqi,
        min_us_aqi=min(aqi_vals) if aqi_vals else None,
        peak_aqi_timestamp=peak_timestamp,
        avg_pm2_5=_mean_or_none(pm25_vals),
        max_pm2_5=round(max(pm25_vals), 2) if pm25_vals else None,
        avg_pm10=_mean_or_none(pm10_vals),
        avg_no2=_mean_or_none(no2_vals),
        avg_o3=_mean_or_none(o3_vals),
        avg_so2=_mean_or_none(so2_vals),
        days_by_aqi_band=days_by_band,
    )


def parse_open_meteo_history_payload(
    payload: Any,
    *,
    location: LocationOption,
    settings: Settings,
    now_utc: datetime,
    retrieval_time_iso: str,
) -> tuple[list[HistoricalHourlyRecord], AirQualityUnits, float | None, float | None]:
    """Validate and normalize an Open-Meteo historical JSON response into HistoricalHourlyRecords.

    - Strictly filters out any timestamp that is in the future (>= now_utc).
    - Preserves null/missing measurements as None.
    - Stores canonical UTC timestamps alongside original local timestamps.
    """
    if not isinstance(payload, dict):
        raise OpenMeteoValidationError("Root historical JSON payload must be an object.")

    if payload.get("error") is True:
        reason = payload.get("reason")
        safe_reason = (
            str(reason) if isinstance(reason, str) and reason.strip() else "Upstream API error flag."
        )
        raise OpenMeteoValidationError(safe_reason)

    hourly_block = payload.get("hourly")
    if not isinstance(hourly_block, dict):
        raise OpenMeteoValidationError("Missing or invalid 'hourly' object in historical payload.")

    times = hourly_block.get("time")
    if not isinstance(times, list) or not all(isinstance(t, str) and t.strip() for t in times):
        raise OpenMeteoValidationError("The 'hourly.time' field must be a list of ISO timestamp strings.")

    provider_tz_str = payload.get("timezone")
    resolved_tz_name = (
        provider_tz_str.strip()
        if isinstance(provider_tz_str, str) and provider_tz_str.strip()
        else location.timezone
    )
    raw_offset = payload.get("utc_offset_seconds")
    utc_offset = (
        int(raw_offset)
        if isinstance(raw_offset, (int, float)) and not isinstance(raw_offset, bool)
        else None
    )
    provider_tz = resolve_timezone(resolved_tz_name, utc_offset_seconds=utc_offset)

    hourly_units_raw = payload.get("hourly_units")
    if hourly_units_raw is not None and not isinstance(hourly_units_raw, dict):
        raise OpenMeteoValidationError("Field 'hourly_units' must be an object when present.")
    units_source = hourly_units_raw if isinstance(hourly_units_raw, dict) else {}

    units = AirQualityUnits(
        us_aqi=_normalize_unit(units_source.get("us_aqi"), default_unit="US AQI"),
        pm2_5=_normalize_unit(units_source.get("pm2_5"), default_unit="µg/m³"),
        pm10=_normalize_unit(units_source.get("pm10"), default_unit="µg/m³"),
        nitrogen_dioxide=_normalize_unit(units_source.get("nitrogen_dioxide"), default_unit="µg/m³"),
        ozone=_normalize_unit(units_source.get("ozone"), default_unit="µg/m³"),
        sulphur_dioxide=_normalize_unit(units_source.get("sulphur_dioxide"), default_unit="µg/m³"),
    )

    def _get_val(key: str, idx: int) -> Any:
        series = hourly_block.get(key)
        if series is None:
            return None
        if not isinstance(series, list):
            raise OpenMeteoValidationError(f"The 'hourly.{key}' field must be a list when present.")
        if idx >= len(series):
            return None
        return series[idx]

    # Exclude any future timestamps strictly (>= current UTC hour boundary)
    cutoff_utc = now_utc.astimezone(timezone.utc)
    records: list[HistoricalHourlyRecord] = []

    for i, raw_time in enumerate(times):
        clean_time = raw_time.strip()
        aware_dt = parse_aware_provider_datetime(
            clean_time,
            provider_tz,
            field_name=f"hourly.time[{i}]",
        )
        dt_utc = aware_dt.astimezone(timezone.utc)
        if dt_utc >= cutoff_utc:
            # Never allow future/forecast timestamps into historical records
            continue

        records.append(
            HistoricalHourlyRecord(
                classification="historical_model",
                timestamp_utc=dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                local_time=clean_time,
                timezone=resolved_tz_name,
                us_aqi=_parse_optional_aqi_int(_get_val("us_aqi", i), f"hourly.us_aqi[{i}]"),
                pm2_5=_parse_optional_float(_get_val("pm2_5", i), f"hourly.pm2_5[{i}]"),
                pm10=_parse_optional_float(_get_val("pm10", i), f"hourly.pm10[{i}]"),
                no2=_parse_optional_float(
                    _get_val("nitrogen_dioxide", i), f"hourly.nitrogen_dioxide[{i}]"
                ),
                o3=_parse_optional_float(_get_val("ozone", i), f"hourly.ozone[{i}]"),
                so2=_parse_optional_float(
                    _get_val("sulphur_dioxide", i), f"hourly.sulphur_dioxide[{i}]"
                ),
                source="open_meteo_cams_global",
                model_domain=settings.open_meteo_domains,
                retrieval_time=retrieval_time_iso,
            )
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

    return records, units, provider_lat, provider_lon


def _is_persisted_window_fresh(
    records: list[HistoricalHourlyRecord],
    *,
    expected_hours: int,
    latest_retrieval_iso: str | None,
    now_utc: datetime,
    max_age_seconds: int,
) -> bool:
    """Decide whether persisted SQLite records satisfy coverage & refresh policy without upstream call."""
    if not records or not latest_retrieval_iso:
        return False
    # Require near-complete window coverage before skipping an upstream refresh
    if len(records) < expected_hours:
        return False
    try:
        retrieved_dt = parse_aware_provider_datetime(latest_retrieval_iso, timezone.utc)
    except OpenMeteoValidationError:
        return False
    age_seconds = (now_utc - retrieved_dt.astimezone(timezone.utc)).total_seconds()
    return 0.0 <= age_seconds <= float(max_age_seconds)


def _assemble_history_response(
    *,
    location: LocationOption,
    days: HistoricalRangeDays,
    start_date: date,
    end_date: date,
    records: list[HistoricalHourlyRecord],
    units: AirQualityUnits,
    retrieval_time_iso: str,
    storage_origin: HistoricalStorageOrigin,
    cache_hit: bool,
    served_from_persistence: bool,
    persisted_to_database: bool,
    fallback_reason: str | None,
    settings: Settings,
    provider_lat: float | None = None,
    provider_lon: float | None = None,
) -> HistoricalAirQualityResponse:
    """Build the final validated HistoricalAirQualityResponse with rollups and provenance."""
    daily_summaries = compute_daily_summaries(
        records,
        location=location,
        start_date=start_date,
        end_date=end_date,
    )
    period_summary = compute_period_summary(
        records,
        daily_summaries,
        days=days,
    )
    attribution = DataAttribution()
    provenance = DataProvenance(
        endpoint_url=settings.open_meteo_base_url,
        model_domain=settings.open_meteo_domains,
        attribution=attribution,
        cache_hit=cache_hit,
        provider_latitude=provider_lat,
        provider_longitude=provider_lon,
    )
    origin = HistoricalDataOriginMetadata(
        storage_origin=storage_origin,
        cache_hit=cache_hit,
        served_from_persistence=served_from_persistence,
        persisted_to_database=persisted_to_database,
        fallback_reason=fallback_reason,
    )

    return HistoricalAirQualityResponse(
        location=location,
        range_days=days,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        timezone=location.timezone,
        retrieval_time=retrieval_time_iso,
        units=units,
        hourly_records=records,
        daily_summaries=daily_summaries,
        period_summary=period_summary,
        data_completeness_percent=period_summary.completeness_percent,
        origin=origin,
        provenance=provenance,
        attribution=attribution,
    )


def _mark_history_cache_hit(
    response: HistoricalAirQualityResponse,
) -> HistoricalAirQualityResponse:
    response.origin.storage_origin = "historical_cache"
    response.origin.cache_hit = True
    response.provenance.cache_hit = True
    return response


def _resolve_historical_uncached(
    *,
    location: LocationOption,
    range_days: HistoricalRangeDays,
    force_refresh: bool,
    cfg: Settings,
    store: SQLiteHistoryStore | None,
    http_client: httpx.Client | None,
    current_utc: datetime,
) -> HistoricalAirQualityResponse:
    """Resolve historical data from fresh SQLite records, upstream Open-Meteo, or SQLite fallback."""
    start_date, end_date, start_utc_dt, end_utc_dt = _compute_local_date_window(
        location, range_days, current_utc
    )
    start_utc_str = start_utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_utc_str = end_utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    history_store = store or _get_history_store(cfg)
    persisted_records: list[HistoricalHourlyRecord] = []
    persisted_latest_retrieval: str | None = None

    try:
        persisted_records = history_store.get_records(
            location_id=location.id,
            model_domain=cfg.open_meteo_domains,
            start_utc=start_utc_str,
            end_utc=end_utc_str,
        )
        persisted_latest_retrieval = history_store.get_latest_retrieval_time(
            location_id=location.id,
            model_domain=cfg.open_meteo_domains,
            start_utc=start_utc_str,
            end_utc=end_utc_str,
        )
    except HistoryStoreError:
        logger.warning(
            "history_sqlite_read_failed location_id=%s days=%d",
            location.id,
            range_days,
        )
        persisted_records = []
        persisted_latest_retrieval = None

    expected_hours = range_days * 24
    if not force_refresh and _is_persisted_window_fresh(
        persisted_records,
        expected_hours=expected_hours,
        latest_retrieval_iso=persisted_latest_retrieval,
        now_utc=current_utc,
        max_age_seconds=cfg.history_refresh_max_age_seconds,
    ):
        return _assemble_history_response(
            location=location,
            days=range_days,
            start_date=start_date,
            end_date=end_date,
            records=persisted_records,
            units=AirQualityUnits(),
            retrieval_time_iso=persisted_latest_retrieval
            or current_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            storage_origin="persisted_database_records",
            cache_hit=False,
            served_from_persistence=True,
            persisted_to_database=False,
            fallback_reason=None,
            settings=cfg,
        )

    # Perform fresh upstream retrieval from Open-Meteo
    params = build_history_query_params(location, range_days, cfg)
    timeout = httpx.Timeout(
        connect=min(5.0, cfg.history_timeout_seconds),
        read=cfg.history_timeout_seconds,
        write=5.0,
        pool=5.0,
    )
    retrieval_iso = current_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        if http_client is not None:
            http_res = http_client.get(
                cfg.open_meteo_base_url,
                params=params,
                timeout=timeout,
                headers={"Accept": "application/json"},
            )
        else:
            with httpx.Client(timeout=timeout) as client:
                http_res = client.get(
                    cfg.open_meteo_base_url,
                    params=params,
                    headers={"Accept": "application/json"},
                )
        if http_res.status_code != 200:
            raise OpenMeteoUpstreamHttpError(
                f"Open-Meteo historical query returned HTTP {http_res.status_code}.",
                upstream_status=http_res.status_code,
            )
        try:
            raw_payload = http_res.json()
        except ValueError as exc:
            raise OpenMeteoValidationError("Historical response body was not valid JSON.") from exc

        records, units, provider_lat, provider_lon = parse_open_meteo_history_payload(
            raw_payload,
            location=location,
            settings=cfg,
            now_utc=current_utc,
            retrieval_time_iso=retrieval_iso,
        )
    except httpx.TimeoutException as exc:
        provider_err: OpenMeteoProviderError = OpenMeteoTimeoutError(cfg.history_timeout_seconds)
        logger.warning(
            "history_upstream_timeout location_id=%s days=%d fallback_available=%s",
            location.id,
            range_days,
            bool(persisted_records),
        )
        if persisted_records:
            return _assemble_history_response(
                location=location,
                days=range_days,
                start_date=start_date,
                end_date=end_date,
                records=persisted_records,
                units=AirQualityUnits(),
                retrieval_time_iso=persisted_latest_retrieval or retrieval_iso,
                storage_origin="persisted_database_fallback",
                cache_hit=False,
                served_from_persistence=True,
                persisted_to_database=False,
                fallback_reason=provider_err.message,
                settings=cfg,
            )
        raise provider_err from exc
    except httpx.HTTPError as exc:
        provider_err = OpenMeteoUpstreamHttpError(
            "Unable to reach Open-Meteo Air Quality API for historical data."
        )
        logger.warning(
            "history_upstream_http_error location_id=%s days=%d exc_type=%s fallback_available=%s",
            location.id,
            range_days,
            type(exc).__name__,
            bool(persisted_records),
        )
        if persisted_records:
            return _assemble_history_response(
                location=location,
                days=range_days,
                start_date=start_date,
                end_date=end_date,
                records=persisted_records,
                units=AirQualityUnits(),
                retrieval_time_iso=persisted_latest_retrieval or retrieval_iso,
                storage_origin="persisted_database_fallback",
                cache_hit=False,
                served_from_persistence=True,
                persisted_to_database=False,
                fallback_reason=provider_err.message,
                settings=cfg,
            )
        raise provider_err from exc
    except OpenMeteoProviderError as exc:
        logger.warning(
            "history_upstream_provider_error location_id=%s days=%d error_code=%s fallback_available=%s",
            location.id,
            range_days,
            exc.error_code,
            bool(persisted_records),
        )
        if persisted_records:
            return _assemble_history_response(
                location=location,
                days=range_days,
                start_date=start_date,
                end_date=end_date,
                records=persisted_records,
                units=AirQualityUnits(),
                retrieval_time_iso=persisted_latest_retrieval or retrieval_iso,
                storage_origin="persisted_database_fallback",
                cache_hit=False,
                served_from_persistence=True,
                persisted_to_database=False,
                fallback_reason=exc.message,
                settings=cfg,
            )
        raise

    # Persist freshly validated records into SQLite without letting DB errors break the API response
    persisted_ok = False
    try:
        if records:
            history_store.upsert_records(location.id, records)
            persisted_ok = True
    except HistoryStoreError:
        logger.warning(
            "history_sqlite_persist_failed location_id=%s days=%d",
            location.id,
            range_days,
        )
        persisted_ok = False

    return _assemble_history_response(
        location=location,
        days=range_days,
        start_date=start_date,
        end_date=end_date,
        records=records,
        units=units,
        retrieval_time_iso=retrieval_iso,
        storage_origin="fresh_provider_retrieval",
        cache_hit=False,
        served_from_persistence=False,
        persisted_to_database=persisted_ok,
        fallback_reason=None,
        settings=cfg,
        provider_lat=provider_lat,
        provider_lon=provider_lon,
    )


def fetch_historical_air_quality(
    location_id: str = "lagos-ng",
    *,
    days: int = 7,
    force_refresh: bool = False,
    use_cache: bool = True,
    settings: Settings | None = None,
    store: SQLiteHistoryStore | None = None,
    http_client: httpx.Client | None = None,
    now_utc: datetime | None = None,
) -> HistoricalAirQualityResponse:
    """Retrieve genuine historical CAMS Global model air quality data with hybrid SQLite persistence.

    Resolution order:
    1. Validate `location_id` (404) and `days` in {7, 14, 30} (422).
    2. Check dedicated thread-safe in-memory historical TTL cache (unless `force_refresh=True`).
    3. Serialize same-key misses / force-refreshes via per-key lock with double-checked read.
    4. Check local SQLite persisted records if fresh within `history_refresh_max_age_seconds`.
    5. Query Open-Meteo historical endpoint (`past_days=days`, `forecast_days=0`), validate,
       exclude future timestamps, upsert into SQLite, and cache the successful result.
    6. If upstream Open-Meteo fails (timeout/HTTP/validation) and valid persisted SQLite records
       exist for this window, return them with `storage_origin="persisted_database_fallback"` and
       the error reason—never reporting persisted records as a fresh retrieval and never mixing demo data.
    """
    location = get_location_by_id(location_id)
    if location is None:
        raise InvalidLocationError(location_id)

    if days not in SUPPORTED_HISTORY_DAYS:
        raise InvalidHistoryRangeError(days)

    range_days: HistoricalRangeDays = days  # type: ignore[assignment]
    cfg = settings or get_settings()
    current_utc = now_utc or datetime.now(timezone.utc)
    ttl = cfg.history_cache_ttl_seconds
    cache_enabled = use_cache and ttl > 0
    cache_key = (location.id, range_days)

    # Explicit uncached, non-forced bypass: do not read, write, or lock the shared cache.
    if not cache_enabled and not force_refresh:
        return _resolve_historical_uncached(
            location=location,
            range_days=range_days,
            force_refresh=False,
            cfg=cfg,
            store=store,
            http_client=http_client,
            current_utc=current_utc,
        )

    # Fast-path cache read without contending on per-key I/O locks.
    if cache_enabled and not force_refresh:
        cached = _HISTORY_CACHE.get(cache_key)
        if cached is not None:
            return _mark_history_cache_hit(cached)

    with _HISTORY_CACHE.key_lock(cache_key):
        # Double-check after acquiring per-key lock unless force_refresh was requested.
        if cache_enabled and not force_refresh:
            cached = _HISTORY_CACHE.get(cache_key)
            if cached is not None:
                return _mark_history_cache_hit(cached)

        response = _resolve_historical_uncached(
            location=location,
            range_days=range_days,
            force_refresh=force_refresh,
            cfg=cfg,
            store=store,
            http_client=http_client,
            current_utc=current_utc,
        )

        # Preserve existing rule: never cache persisted_database_fallback responses.
        if cache_enabled and response.origin.storage_origin != "persisted_database_fallback":
            _HISTORY_CACHE.set(cache_key, response, ttl)

        return response


def fetch_historical_city_comparison(
    *,
    days: int = 7,
    force_refresh: bool = False,
    settings: Settings | None = None,
    store: SQLiteHistoryStore | None = None,
    http_client: httpx.Client | None = None,
    now_utc: datetime | None = None,
) -> HistoricalCityComparisonResponse:
    """Fetch historical summaries for all four configured cities with fault isolation per city.

    A failure in one city returns `status='unavailable'` for that city only and never fails
    the remaining cities or substitutes demo data.
    """
    if days not in SUPPORTED_HISTORY_DAYS:
        raise InvalidHistoryRangeError(days)

    range_days: HistoricalRangeDays = days  # type: ignore[assignment]
    cfg = settings or get_settings()
    current_utc = now_utc or datetime.now(timezone.utc)

    def _load_one(loc: LocationOption) -> CityHistoricalComparisonItem:
        try:
            res = fetch_historical_air_quality(
                location_id=loc.id,
                days=range_days,
                force_refresh=force_refresh,
                settings=cfg,
                store=store,
                http_client=http_client,
                now_utc=current_utc,
            )
            return CityHistoricalComparisonItem(
                location=loc,
                status="available",
                data_label=res.data_label,
                retrieval_time=res.retrieval_time,
                origin=res.origin,
                period_summary=res.period_summary,
                daily_summaries=res.daily_summaries,
            )
        except OpenMeteoProviderError as exc:
            return CityHistoricalComparisonItem(
                location=loc,
                status="unavailable",
                data_label="DATA UNAVAILABLE",
                error_code=exc.error_code,
                error_message=exc.message,
            )

    # Bounded concurrency (max 4 workers for 4 configured cities)
    with ThreadPoolExecutor(max_workers=len(AVAILABLE_LOCATIONS)) as executor:
        items = list(executor.map(_load_one, AVAILABLE_LOCATIONS))

    available_count = sum(1 for item in items if item.status == "available")
    unavailable_count = len(items) - available_count

    return HistoricalCityComparisonResponse(
        range_days=range_days,
        generated_at=current_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        cities_available=available_count,
        cities_unavailable=unavailable_count,
        cities=items,
    )
