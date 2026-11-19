"""Comprehensive pytest suite for Phase 6.2 Step 2: Backend Historical Engine & SQLite Persistence.

All upstream Open-Meteo HTTP calls are mocked so tests run deterministically offline.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.schemas.history import HistoricalHourlyRecord
from app.services.demo_data import build_demo_dashboard, get_location_by_id
from app.services.history_store import SQLiteHistoryStore
from app.services.open_meteo import clear_open_meteo_cache, resolve_timezone
from app.services.open_meteo_history import (
    clear_history_cache,
    compute_daily_summaries,
    fetch_historical_air_quality,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_history_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point SQLite persistence to a clean temp database and clear caches for every test."""
    clear_history_cache()
    clear_open_meteo_cache()

    db_file = tmp_path / "test_airwise_history.db"
    test_settings = Settings(
        history_db_path=str(db_file),
        history_cache_ttl_seconds=1200,
        history_refresh_max_age_seconds=21600,
        history_timeout_seconds=8.0,
    )
    monkeypatch.setattr("app.services.open_meteo_history.get_settings", lambda: test_settings)
    yield db_file
    clear_history_cache()
    clear_open_meteo_cache()


def _build_historical_open_meteo_payload(
    *,
    days: int = 7,
    timezone_str: str = "Africa/Lagos",
    utc_offset_seconds: int = 3600,
    end_local_date: date | None = None,
    null_indices: set[int] | None = None,
    include_future_hours: int = 0,
    base_aqi: int = 60,
    base_pm25: float = 20.0,
) -> dict[str, Any]:
    """Generate a realistic hourly Open-Meteo historical JSON payload for N completed local days."""
    loc_tz = resolve_timezone(timezone_str, utc_offset_seconds=utc_offset_seconds)
    if end_local_date is None:
        end_local_date = datetime.now(timezone.utc).astimezone(loc_tz).date() - timedelta(days=1)

    start_local_date = end_local_date - timedelta(days=days - 1)
    total_hours = days * 24 + include_future_hours
    null_set = null_indices or set()

    times: list[str] = []
    us_aqi: list[int | None] = []
    pm2_5: list[float | None] = []
    pm10: list[float | None] = []
    no2: list[float | None] = []
    o3: list[float | None] = []
    so2: list[float | None] = []

    start_dt = datetime(start_local_date.year, start_local_date.month, start_local_date.day, 0, 0)
    for idx in range(total_hours):
        dt = start_dt + timedelta(hours=idx)
        times.append(dt.strftime("%Y-%m-%dT%H:%M"))
        if idx in null_set:
            us_aqi.append(None)
            pm2_5.append(None)
            pm10.append(None)
            no2.append(None)
            o3.append(None)
            so2.append(None)
        else:
            us_aqi.append(base_aqi + (idx % 10))
            pm2_5.append(round(base_pm25 + (idx % 5) * 0.5, 2))
            pm10.append(round(35.0 + (idx % 6), 2))
            no2.append(round(14.0 + (idx % 4) * 0.5, 2))
            o3.append(round(42.0 + (idx % 7), 2))
            so2.append(round(3.0 + (idx % 3) * 0.2, 2))

    return {
        "latitude": 6.5,
        "longitude": 3.4,
        "utc_offset_seconds": utc_offset_seconds,
        "timezone": timezone_str,
        "timezone_abbreviation": "WAT",
        "hourly_units": {
            "time": "iso8601",
            "us_aqi": "USAQI",
            "pm2_5": "μg/m³",
            "pm10": "μg/m³",
            "nitrogen_dioxide": "μg/m³",
            "ozone": "μg/m³",
            "sulphur_dioxide": "μg/m³",
        },
        "hourly": {
            "time": times,
            "us_aqi": us_aqi,
            "pm2_5": pm2_5,
            "pm10": pm10,
            "nitrogen_dioxide": no2,
            "ozone": o3,
            "sulphur_dioxide": so2,
        },
    }


def _mock_history_httpx_get(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int = 200,
    json_payload: Any = None,
    raw_text: str | None = None,
    raise_exc: Exception | None = None,
    side_effect_fn: Any = None,
) -> MagicMock:
    """Patch httpx.Client inside open_meteo_history for deterministic offline tests."""
    mock_get = MagicMock()

    if side_effect_fn is not None:
        mock_get.side_effect = side_effect_fn
    elif raise_exc is not None:
        mock_get.side_effect = raise_exc
    else:
        mock_res = MagicMock(spec=httpx.Response)
        mock_res.status_code = status_code
        if raw_text is not None:
            mock_res.json.side_effect = ValueError("Invalid JSON")
            mock_res.text = raw_text
        else:
            mock_res.json.return_value = json_payload
        mock_get.return_value = mock_res

    class _DummyClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> _DummyClient:
            return self

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            return None

        def get(self, *args: Any, **kwargs: Any) -> Any:
            return mock_get(*args, **kwargs)

    monkeypatch.setattr("app.services.open_meteo_history.httpx.Client", _DummyClient)
    return mock_get


# ============================================================================
# 1. Range Retrieval Tests (7d, 14d, 30d) & Validation
# ============================================================================


@pytest.mark.parametrize("days", [7, 14, 30])
def test_history_endpoint_supports_7_14_and_30_days(
    monkeypatch: pytest.MonkeyPatch,
    days: int,
) -> None:
    """Verify 7-day, 14-day, and 30-day historical retrieval, daily summaries, and provenance."""
    payload = _build_historical_open_meteo_payload(days=days)
    mock_get = _mock_history_httpx_get(monkeypatch, status_code=200, json_payload=payload)

    response = client.get(f"/api/v1/air-quality/history?location_id=lagos-ng&days={days}")
    assert response.status_code == 200
    assert mock_get.call_count == 1

    data = response.json()
    assert data["data_mode"] == "historical_model"
    assert data["data_label"] == "HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE"
    assert data["is_demo_data"] is False
    assert data["range_days"] == days
    assert len(data["hourly_records"]) == days * 24
    assert len(data["daily_summaries"]) == days
    assert data["data_completeness_percent"] == 100.0
    assert data["origin"]["storage_origin"] == "fresh_provider_retrieval"
    assert data["origin"]["persisted_to_database"] is True
    assert data["origin"]["cache_hit"] is False
    assert all(rec["classification"] == "historical_model" for rec in data["hourly_records"])

    # Verify outbound Open-Meteo query used past_days and forecast_days=0
    sent_params = mock_get.call_args.kwargs["params"]
    assert sent_params["past_days"] == days
    assert sent_params["forecast_days"] == 0
    assert sent_params["domains"] == "cams_global"


def test_history_endpoint_rejects_invalid_range_and_invalid_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify unsupported days values return 422 and unknown location_id returns 404 without calling provider."""
    mock_get = _mock_history_httpx_get(monkeypatch, status_code=200, json_payload={})

    bad_range = client.get("/api/v1/air-quality/history?location_id=lagos-ng&days=10")
    assert bad_range.status_code == 422
    assert bad_range.json()["detail"]["error_code"] == "invalid_history_range"

    bad_location = client.get("/api/v1/air-quality/history?location_id=unknown-city&days=7")
    assert bad_location.status_code == 404
    assert bad_location.json()["detail"]["error_code"] == "invalid_location_id"
    assert mock_get.call_count == 0


# ============================================================================
# 2. Daily Summary Mathematics, Missing Values, & Timezone Boundaries
# ============================================================================


def test_daily_summary_mathematics_and_null_preservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify exact mean/min/max math, missing hour tracking, and zero-fill prevention."""
    # Day 1 has 4 missing (all-null) hours at indices 0, 1, 2, 3 -> 20 valid / 4 missing
    payload = _build_historical_open_meteo_payload(
        days=7,
        null_indices={0, 1, 2, 3},
        base_aqi=50,
        base_pm25=10.0,
    )
    _mock_history_httpx_get(monkeypatch, status_code=200, json_payload=payload)

    response = client.get("/api/v1/air-quality/history?location_id=lagos-ng&days=7")
    assert response.status_code == 200
    data = response.json()

    first_day = data["daily_summaries"][0]
    assert first_day["valid_hours"] == 20
    assert first_day["expected_hours"] == 24
    assert first_day["missing_hours"] == 4
    assert first_day["completeness_percent"] == round((20 / 24) * 100.0, 1)

    # Confirm null hourly records remained None and were NOT converted to 0
    assert data["hourly_records"][0]["us_aqi"] is None
    assert data["hourly_records"][0]["pm2_5"] is None
    assert first_day["min_us_aqi"] == 50  # Not 0!

    # Period summary tracks total missing hours accurately
    assert data["period_summary"]["total_missing_hours"] == 4
    assert data["period_summary"]["total_valid_hours"] == 164


def test_timezone_boundary_aggregation_for_nairobi_eat() -> None:
    """Verify UTC timestamps crossing midnight in Africa/Nairobi (UTC+3) aggregate into the correct local day."""
    nairobi = get_location_by_id("nairobi-ke")
    assert nairobi is not None

    # 2026-11-17T21:00:00Z == 2026-11-18T00:00 EAT (belongs to 2026-11-18, NOT 2026-11-17)
    # 2026-11-17T20:00:00Z == 2026-11-17T23:00 EAT (belongs to 2026-11-17)
    records = [
        HistoricalHourlyRecord(
            timestamp_utc="2026-11-17T20:00:00Z",
            local_time="2026-11-17T23:00",
            timezone="Africa/Nairobi",
            us_aqi=40,
            pm2_5=10.0,
            retrieval_time="2026-11-19T08:00:00Z",
        ),
        HistoricalHourlyRecord(
            timestamp_utc="2026-11-17T21:00:00Z",
            local_time="2026-11-18T00:00",
            timezone="Africa/Nairobi",
            us_aqi=80,
            pm2_5=30.0,
            retrieval_time="2026-11-19T08:00:00Z",
        ),
    ]

    summaries = compute_daily_summaries(
        records,
        location=nairobi,
        start_date=date(2026, 11, 17),
        end_date=date(2026, 11, 18),
    )
    assert len(summaries) == 2
    assert summaries[0].date == "2026-11-17"
    assert summaries[0].avg_us_aqi == 40.0
    assert summaries[0].valid_hours == 1
    assert summaries[1].date == "2026-11-18"
    assert summaries[1].avg_us_aqi == 80.0
    assert summaries[1].valid_hours == 1


def test_future_timestamps_are_strictly_excluded_from_historical_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify any future/forecast timestamp returned by the provider is excluded from historical records."""
    # Include 48 extra hours extending into today/tomorrow (future relative to now_utc)
    payload = _build_historical_open_meteo_payload(days=7, include_future_hours=48)
    _mock_history_httpx_get(monkeypatch, status_code=200, json_payload=payload)

    now_utc = datetime.now(timezone.utc)
    res = fetch_historical_air_quality("lagos-ng", days=7, now_utc=now_utc)

    for rec in res.hourly_records:
        rec_utc = datetime.fromisoformat(rec.timestamp_utc.replace("Z", "+00:00"))
        assert rec_utc < now_utc
        assert rec.classification == "historical_model"


# ============================================================================
# 3. SQLite Persistence, Upsert, Cache, & Fallback Resilience
# ============================================================================


def test_sqlite_store_initialization_insert_retrieve_and_upsert(tmp_path: Path) -> None:
    """Verify SQLite table creation, insertion, retrieval, and idempotent upsert on (location_id, timestamp_utc, model_domain)."""
    store = SQLiteHistoryStore(tmp_path / "subdir" / "history.db")
    store.initialize()
    assert store.db_path.exists()

    rec_v1 = HistoricalHourlyRecord(
        timestamp_utc="2026-11-15T10:00:00Z",
        local_time="2026-11-15T11:00",
        timezone="Africa/Lagos",
        us_aqi=72,
        pm2_5=22.4,
        pm10=40.1,
        no2=15.0,
        o3=38.0,
        so2=None,
        retrieval_time="2026-11-19T08:00:00Z",
    )
    assert store.upsert_records("lagos-ng", [rec_v1]) == 1

    fetched = store.get_records(
        location_id="lagos-ng",
        model_domain="cams_global",
        start_utc="2026-11-15T00:00:00Z",
        end_utc="2026-11-15T23:59:59Z",
    )
    assert len(fetched) == 1
    assert fetched[0].us_aqi == 72
    assert fetched[0].so2 is None

    # Upsert same key with updated value -> count remains 1 and value updates
    rec_v2 = rec_v1.model_copy(update={"us_aqi": 75, "retrieval_time": "2026-11-19T09:00:00Z"})
    assert store.upsert_records("lagos-ng", [rec_v2]) == 1

    fetched_after = store.get_records(
        location_id="lagos-ng",
        model_domain="cams_global",
        start_utc="2026-11-15T00:00:00Z",
        end_utc="2026-11-15T23:59:59Z",
    )
    assert len(fetched_after) == 1
    assert fetched_after[0].us_aqi == 75
    assert fetched_after[0].retrieval_time == "2026-11-19T09:00:00Z"


def test_history_cache_and_sqlite_persistence_origin_distinction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify clear distinction between fresh_provider_retrieval, historical_cache, and persisted_database_records."""
    payload = _build_historical_open_meteo_payload(days=7)
    mock_get = _mock_history_httpx_get(monkeypatch, status_code=200, json_payload=payload)

    # Call 1: Fresh upstream retrieval -> persisted to SQLite
    r1 = client.get("/api/v1/air-quality/history?location_id=lagos-ng&days=7")
    assert r1.status_code == 200
    assert r1.json()["origin"]["storage_origin"] == "fresh_provider_retrieval"
    assert r1.json()["origin"]["cache_hit"] is False
    assert r1.json()["origin"]["persisted_to_database"] is True
    assert mock_get.call_count == 1

    # Call 2: Served from in-memory historical TTL cache (no new HTTP call)
    r2 = client.get("/api/v1/air-quality/history?location_id=lagos-ng&days=7")
    assert r2.status_code == 200
    assert r2.json()["origin"]["storage_origin"] == "historical_cache"
    assert r2.json()["origin"]["cache_hit"] is True
    assert mock_get.call_count == 1

    # Call 3: Clear in-memory cache -> served from fresh SQLite persisted records without calling Open-Meteo
    clear_history_cache()
    r3 = client.get("/api/v1/air-quality/history?location_id=lagos-ng&days=7")
    assert r3.status_code == 200
    assert r3.json()["origin"]["storage_origin"] == "persisted_database_records"
    assert r3.json()["origin"]["served_from_persistence"] is True
    assert r3.json()["origin"]["cache_hit"] is False
    assert mock_get.call_count == 1


def test_provider_timeout_http_error_invalid_payload_and_persisted_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify 504 timeout, 502 HTTP error, 502 invalid JSON, and fallback to persisted SQLite records when available."""
    # 1. Timeout with empty DB -> HTTP 504
    _mock_history_httpx_get(monkeypatch, raise_exc=httpx.ReadTimeout("Timed out"))
    res_timeout = client.get("/api/v1/air-quality/history?location_id=lagos-ng&days=7")
    assert res_timeout.status_code == 504
    assert res_timeout.json()["detail"]["error_code"] == "provider_timeout"
    assert res_timeout.json()["detail"]["is_demo_data"] is False

    # 2. HTTP 503 with empty DB -> HTTP 502
    _mock_history_httpx_get(monkeypatch, status_code=503, json_payload={"error": True})
    res_http = client.get("/api/v1/air-quality/history?location_id=lagos-ng&days=7")
    assert res_http.status_code == 502
    assert res_http.json()["detail"]["error_code"] == "provider_upstream_http_error"

    # 3. Malformed JSON with empty DB -> HTTP 502
    _mock_history_httpx_get(monkeypatch, status_code=200, raw_text="<html>Broken</html>")
    res_bad = client.get("/api/v1/air-quality/history?location_id=lagos-ng&days=7")
    assert res_bad.status_code == 502
    assert res_bad.json()["detail"]["error_code"] == "provider_invalid_payload"

    # 4. Seed SQLite with a valid response, then force_refresh during a provider outage -> persisted_database_fallback
    payload = _build_historical_open_meteo_payload(days=7)
    _mock_history_httpx_get(monkeypatch, status_code=200, json_payload=payload)
    seed_res = client.get("/api/v1/air-quality/history?location_id=lagos-ng&days=7")
    assert seed_res.status_code == 200

    clear_history_cache()
    _mock_history_httpx_get(monkeypatch, raise_exc=httpx.ReadTimeout("Upstream down"))
    fallback_res = client.get(
        "/api/v1/air-quality/history?location_id=lagos-ng&days=7&force_refresh=true"
    )
    assert fallback_res.status_code == 200
    fb_data = fallback_res.json()
    assert fb_data["origin"]["storage_origin"] == "persisted_database_fallback"
    assert fb_data["origin"]["served_from_persistence"] is True
    assert fb_data["origin"]["fallback_reason"] is not None
    assert fb_data["is_demo_data"] is False


# ============================================================================
# 4. Multi-City Comparison & Partial City Failure Isolation
# ============================================================================


def test_multi_city_history_comparison_isolates_partial_city_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify one failing city returns status='unavailable' without failing the other three or mixing demo data."""
    demo_lagos_aqi = build_demo_dashboard("lagos-ng").summary.aqi_value

    def _per_city_mock(*args: Any, **kwargs: Any) -> MagicMock:
        params = kwargs.get("params", {})
        lat = params.get("latitude")
        # Simulate failure for Abuja (lat=9.0765) only
        if lat == 9.0765:
            raise httpx.ReadTimeout("Abuja upstream timeout")
        res = MagicMock(spec=httpx.Response)
        res.status_code = 200
        res.json.return_value = _build_historical_open_meteo_payload(
            days=7,
            timezone_str=params.get("timezone", "Africa/Lagos"),
            base_aqi=55,
        )
        return res

    _mock_history_httpx_get(monkeypatch, side_effect_fn=_per_city_mock)

    response = client.get("/api/v1/air-quality/history/compare?days=7")
    assert response.status_code == 200
    data = response.json()

    assert data["range_days"] == 7
    assert data["cities_available"] == 3
    assert data["cities_unavailable"] == 1
    assert data["is_demo_data"] is False

    by_id = {c["location"]["id"]: c for c in data["cities"]}
    assert by_id["lagos-ng"]["status"] == "available"
    assert by_id["lagos-ng"]["period_summary"]["avg_us_aqi"] != demo_lagos_aqi
    assert by_id["nairobi-ke"]["status"] == "available"
    assert by_id["accra-gh"]["status"] == "available"

    assert by_id["abuja-ng"]["status"] == "unavailable"
    assert by_id["abuja-ng"]["data_label"] == "DATA UNAVAILABLE"
    assert by_id["abuja-ng"]["period_summary"] is None
    assert by_id["abuja-ng"]["error_code"] == "provider_timeout"
    assert by_id["abuja-ng"]["is_demo_data"] is False
