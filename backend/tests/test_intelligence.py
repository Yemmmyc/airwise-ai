"""Comprehensive offline pytest suite for Phase 7: Deterministic Predictive Intelligence Engine.

Covers all AQI boundaries, invalid/null values, risk windows (all 5 canonical scenarios + timestamp gaps),
better-window engine, independent activity planner, OLS trend signals (rising, falling, stable, noisy,
incomplete, insufficient), qualitative data-quality tiers (no numeric score), daily summary honesty,
timezone handling, and the FastAPI GET /api/v1/air-quality/intelligence endpoint.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.air_quality import (
    AirQualityResponse,
    AirQualityUnits,
    AqiMeasurement,
    CurrentModelConditions,
    DataAttribution,
    DataProvenance,
    HourlyForecastPoint,
    HourlyForecastSeries,
    PollutantMeasurement,
)
from app.services.demo_data import get_location_by_id
from app.services.open_meteo import clear_open_meteo_cache, resolve_timezone
from app.services.predictive_intelligence import (
    _parse_and_sort_forecast_points,
    classify_aqi_risk,
    compute_predictive_intelligence_from_forecast,
    detect_risk_windows,
)
from tests.test_api import _build_mock_open_meteo_payload, _mock_httpx_client_get

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    clear_open_meteo_cache()
    yield
    clear_open_meteo_cache()


def _make_forecast_points(
    start_iso: str,
    aqi_values: list[int | None],
    *,
    step_hours: list[int] | None = None,
    pm2_5_values: list[float | None] | None = None,
    pm10_values: list[float | None] | None = None,
    no2_values: list[float | None] | None = None,
    o3_values: list[float | None] | None = None,
    so2_values: list[float | None] | None = None,
) -> list[HourlyForecastPoint]:
    """Build synthetic HourlyForecastPoint lists for deterministic unit tests."""
    base_dt = datetime.fromisoformat(start_iso)
    points: list[HourlyForecastPoint] = []
    cur_dt = base_dt

    for i, aqi in enumerate(aqi_values):
        if i > 0:
            delta = step_hours[i - 1] if step_hours is not None else 1
            cur_dt = cur_dt + timedelta(hours=delta)
        points.append(
            HourlyForecastPoint(
                classification="hourly_forecast",
                time=cur_dt.strftime("%Y-%m-%dT%H:%M"),
                us_aqi=aqi,
                pm2_5=pm2_5_values[i] if pm2_5_values is not None else (20.0 if aqi is not None else None),
                pm10=pm10_values[i] if pm10_values is not None else (35.0 if aqi is not None else None),
                no2=no2_values[i] if no2_values is not None else (15.0 if aqi is not None else None),
                o3=o3_values[i] if o3_values is not None else (40.0 if aqi is not None else None),
                so2=so2_values[i] if so2_values is not None else (3.0 if aqi is not None else None),
            )
        )
    return points


def _make_aq_response(
    forecast_points: list[HourlyForecastPoint],
    *,
    location_id: str = "lagos-ng",
    observation_time: str = "2026-11-19T08:00",
    cache_hit: bool = False,
) -> AirQualityResponse:
    loc = get_location_by_id(location_id)
    assert loc is not None

    dummy_aqi = AqiMeasurement(value=70, band="Moderate", status="available")
    dummy_pm25 = PollutantMeasurement(code="PM2.5", parameter="pm2_5", name="PM2.5", value=20.0, unit="µg/m³", status="available")
    dummy_pm10 = PollutantMeasurement(code="PM10", parameter="pm10", name="PM10", value=35.0, unit="µg/m³", status="available")
    dummy_no2 = PollutantMeasurement(code="NO2", parameter="nitrogen_dioxide", name="NO2", value=15.0, unit="µg/m³", status="available")
    dummy_o3 = PollutantMeasurement(code="O3", parameter="ozone", name="O3", value=40.0, unit="µg/m³", status="available")
    dummy_so2 = PollutantMeasurement(code="SO2", parameter="sulphur_dioxide", name="SO2", value=3.0, unit="µg/m³", status="available")

    return AirQualityResponse(
        location=loc,
        observation_time=observation_time,
        retrieval_time="2026-11-19T07:05:00Z",
        timezone=loc.timezone,
        timezone_abbreviation="WAT",
        aqi=dummy_aqi,
        pm2_5=dummy_pm25,
        pm10=dummy_pm10,
        no2=dummy_no2,
        o3=dummy_o3,
        so2=dummy_so2,
        units=AirQualityUnits(),
        current_conditions=CurrentModelConditions(
            observation_time=observation_time,
            interval_seconds=3600,
            aqi=dummy_aqi,
            pm2_5=dummy_pm25,
            pm10=dummy_pm10,
            no2=dummy_no2,
            o3=dummy_o3,
            so2=dummy_so2,
        ),
        hourly_forecast=HourlyForecastSeries(
            hours_returned=len(forecast_points),
            points=forecast_points,
        ),
        provenance=DataProvenance(cache_hit=cache_hit),
        attribution=DataAttribution(),
    )


# ============================================================================
# 1. US EPA AQI Boundary & Invalid Value Tests
# ============================================================================


@pytest.mark.parametrize(
    ("raw_val", "expected_val", "expected_cat", "expected_rank"),
    [
        (0, 0, "Good", 1),
        (50, 50, "Good", 1),
        (51, 51, "Moderate", 2),
        (100, 100, "Moderate", 2),
        (101, 101, "Unhealthy for Sensitive Groups", 3),
        (150, 150, "Unhealthy for Sensitive Groups", 3),
        (151, 151, "Unhealthy", 4),
        (200, 200, "Unhealthy", 4),
        (201, 201, "Very Unhealthy", 5),
        (300, 300, "Very Unhealthy", 5),
        (301, 301, "Hazardous", 6),
        (500, 500, "Hazardous", 6),
        (None, None, "Unavailable", 0),
        (-1, None, "Unavailable", 0),
        (501, None, "Unavailable", 0),
        (True, None, "Unavailable", 0),
        (float("nan"), None, "Unavailable", 0),
    ],
)
def test_aqi_boundary_and_invalid_value_classification(
    raw_val: Any,
    expected_val: int | None,
    expected_cat: str,
    expected_rank: int,
) -> None:
    """Verify exact US EPA AQI threshold boundaries and defensive invalid/null handling."""
    val, cat, rank = classify_aqi_risk(raw_val)
    assert val == expected_val
    assert cat == expected_cat
    assert rank == expected_rank


# ============================================================================
# 2. Risk Window Engine Tests (All 5 Canonical Cases + Timestamp Gap)
# ============================================================================


def test_risk_window_case_1_single_elevated_hour() -> None:
    """Case 1: Isolated single elevated hour emits SingleHourSpike, not a RiskWindow."""
    pts = _make_forecast_points("2026-11-19T10:00", [85, 118, 92])
    parsed = _parse_and_sort_forecast_points(pts, resolve_timezone("Africa/Lagos"))
    windows, spikes, status = detect_risk_windows(parsed, "Africa/Lagos")

    assert status == "evaluated"
    assert windows == []
    assert len(spikes) == 1
    assert spikes[0].time == "2026-11-19T11:00"
    assert spikes[0].us_aqi == 118


def test_risk_window_case_2_multiple_consecutive_elevated_hours() -> None:
    """Case 2: Inclusive boundary 101 and exact observation count duration_hours=3."""
    pts = _make_forecast_points("2026-11-19T08:00", [90, 101, 125, 140, 95])
    parsed = _parse_and_sort_forecast_points(pts, resolve_timezone("Africa/Lagos"))
    windows, spikes, status = detect_risk_windows(parsed, "Africa/Lagos")

    assert status == "evaluated"
    assert spikes == []
    assert len(windows) == 1
    w = windows[0]
    assert w.start_time == "2026-11-19T09:00"
    assert w.end_time == "2026-11-19T11:00"
    assert w.duration_hours == 3
    assert w.peak_aqi == 140
    assert w.peak_time == "2026-11-19T11:00"
    assert w.crosses_midnight is False


def test_risk_window_case_3_crossing_midnight() -> None:
    """Case 3: Contiguous elevated window spanning midnight sets crosses_midnight=True."""
    pts = _make_forecast_points("2026-11-19T22:00", [95, 110, 120, 115, 88])
    parsed = _parse_and_sort_forecast_points(pts, resolve_timezone("Africa/Lagos"))
    windows, _, _ = detect_risk_windows(parsed, "Africa/Lagos")

    assert len(windows) == 1
    w = windows[0]
    assert w.start_time == "2026-11-19T23:00"
    assert w.end_time == "2026-11-20T01:00"
    assert w.duration_hours == 3
    assert w.peak_aqi == 120
    assert w.peak_time == "2026-11-20T00:00"
    assert w.crosses_midnight is True


def test_risk_window_case_4_missing_observation_splits_window() -> None:
    """Case 4: A null observation inside elevated hours terminates the window and never merges."""
    pts = _make_forecast_points("2026-11-19T10:00", [115, 120, None, 130, 125])
    parsed = _parse_and_sort_forecast_points(pts, resolve_timezone("Africa/Lagos"))
    windows, _, _ = detect_risk_windows(parsed, "Africa/Lagos")

    assert len(windows) == 2
    assert windows[0].start_time == "2026-11-19T10:00"
    assert windows[0].end_time == "2026-11-19T11:00"
    assert windows[0].duration_hours == 2
    assert windows[0].interrupted_by_missing_data is True

    assert windows[1].start_time == "2026-11-19T13:00"
    assert windows[1].end_time == "2026-11-19T14:00"
    assert windows[1].duration_hours == 2
    assert windows[1].interrupted_by_missing_data is True


def test_risk_window_case_5_two_separated_windows_and_timestamp_gap() -> None:
    """Case 5: Two elevated windows separated by lower-risk hour OR a 2-hour timestamp gap."""
    pts_lower = _make_forecast_points("2026-11-19T07:00", [112, 118, 82, 108, 115])
    parsed_lower = _parse_and_sort_forecast_points(pts_lower, resolve_timezone("Africa/Lagos"))
    windows, _, _ = detect_risk_windows(parsed_lower, "Africa/Lagos")
    assert len(windows) == 2
    assert windows[0].peak_aqi == 118
    assert windows[1].peak_aqi == 115

    # Timestamp jump of 2 hours between index 1 and index 2 must split the window
    pts_gap = _make_forecast_points(
        "2026-11-19T07:00",
        [112, 118, 122, 125],
        step_hours=[1, 2, 1],
    )
    parsed_gap = _parse_and_sort_forecast_points(pts_gap, resolve_timezone("Africa/Lagos"))
    windows_gap, _, _ = detect_risk_windows(parsed_gap, "Africa/Lagos")
    assert len(windows_gap) == 2
    assert windows_gap[0].interrupted_by_missing_data is True
    assert windows_gap[1].interrupted_by_missing_data is True


# ============================================================================
# 3. Better-Window Engine & Independent Activity Planner Tests
# ============================================================================


def test_better_window_and_activity_planner_normal_and_high_aqi_ceiling() -> None:
    """Verify Better-Window Engine and Activity Planner operate independently and respect ceilings."""
    # 24 hours: hours 0-3 are lowest (52, 54, 55, 58), later hours rise to 130
    aqis = [52, 54, 55, 58] + [85] * 10 + [130] * 10
    aq = _make_aq_response(_make_forecast_points("2026-11-19T09:00", aqis))
    intel = compute_predictive_intelligence_from_forecast(aq)

    assert intel.better_windows.status == "windows_identified"
    assert len(intel.better_windows.windows) >= 1
    best = intel.better_windows.windows[0]
    assert best.start_time == "2026-11-19T09:00"
    assert best.hourly_aqi_values == [52, 54]
    assert "safe" not in best.rationale.lower()

    # Activity planner evaluates all 3 activities independently
    by_act = {a.activity_type: a for a in intel.activity_recommendations}
    assert by_act["outdoor_exercise"].status == "window_identified"
    assert by_act["outdoor_exercise"].is_medical_advice is False
    assert by_act["outdoor_errands"].status == "window_identified"
    assert by_act["outdoor_errands"].recommended_window is not None
    assert by_act["outdoor_errands"].recommended_window.duration_hours in (1, 2)

    # All hours > 150 -> Better-Window and all Activity Planners return no_qualifying_window
    severe_aq = _make_aq_response(_make_forecast_points("2026-11-19T09:00", [165] * 24))
    severe_intel = compute_predictive_intelligence_from_forecast(severe_aq)
    assert severe_intel.better_windows.status == "no_qualifying_window"
    assert severe_intel.better_windows.windows == []
    assert all(a.status == "no_qualifying_window" and a.recommended_window is None for a in severe_intel.activity_recommendations)


# ============================================================================
# 4. Trend Signal Engine Tests (Rising, Falling, Stable, Volatile, Gaps, Insufficient)
# ============================================================================


def test_trend_signals_cover_rising_falling_stable_volatile_incomplete_and_insufficient() -> None:
    """Verify OLS trend engine across all 6 required dataset archetypes."""
    # Rising US AQI, Falling PM2.5, Constant PM10, Volatile NO2 (R^2 < 0.25)
    aqis_rising = [55, 60, 65, 70, 76, 82, 88, 95, 102, 108, 114, 120]
    pm25_falling = [48.0, 44.0, 41.0, 38.0, 35.0, 31.0, 28.0, 25.0, 22.0, 19.0, 16.0, 14.0]
    pm10_constant = [40.0] * 12
    no2_volatile = [10.0, 55.0, 12.0, 58.0, 11.0, 60.0, 14.0, 54.0, 15.0, 62.0, 13.0, 59.0]
    o3_gapped = [40.0, None, 48.0, 54.0, None, 64.0, 70.0, None, 80.0, 86.0, 92.0, 98.0]
    so2_insufficient = [4.0, 4.2, None, None, None, None, None, None, None, None, 4.5, 4.8]

    pts = _make_forecast_points(
        "2026-11-19T09:00",
        aqis_rising,
        pm2_5_values=pm25_falling,
        pm10_values=pm10_constant,
        no2_values=no2_volatile,
        o3_values=o3_gapped,
        so2_values=so2_insufficient,
    )
    intel = compute_predictive_intelligence_from_forecast(_make_aq_response(pts))
    by_metric = {t.metric: t for t in intel.trend_signals}

    assert by_metric["us_aqi"].signal == "Rising"
    assert by_metric["PM2.5"].signal == "Falling"
    assert by_metric["PM10"].signal == "Stable"
    assert by_metric["PM10"].slope_per_hour == 0.0
    assert by_metric["NO2"].signal == "Stable"
    assert by_metric["NO2"].volatility_flag is True
    assert by_metric["O3"].signal == "Rising"
    assert by_metric["O3"].valid_points == 9
    assert by_metric["SO2"].signal == "Insufficient data"
    assert by_metric["SO2"].valid_points == 4


# ============================================================================
# 5. Data-Quality Tiers (No Numeric Score) & Daily Summary Honesty
# ============================================================================


def test_data_quality_tiers_and_daily_summary_distinguish_zero_windows_vs_insufficient() -> None:
    """Verify qualitative tiers (High, Moderate, Limited, Insufficient data) and honest daily summaries."""
    # High: 24/24 continuous valid hours
    high_intel = compute_predictive_intelligence_from_forecast(
        _make_aq_response(_make_forecast_points("2026-11-19T09:00", [65] * 24))
    )
    assert high_intel.data_quality.tier == "High"
    assert high_intel.data_quality.timestamp_continuity == "continuous"
    assert not hasattr(high_intel.data_quality, "score")
    assert high_intel.daily_summary.peak_forecast_risk == "Moderate"
    assert high_intel.daily_summary.risk_window_evaluation_status == "evaluated"
    assert "No qualifying elevated-risk windows" in high_intel.daily_summary.deterministic_summary

    # Moderate: 19 valid hours, 2 nulls (79.2% completeness, 2 gaps)
    mod_aqis = [70] * 10 + [None, None] + [72] * 9
    mod_intel = compute_predictive_intelligence_from_forecast(
        _make_aq_response(_make_forecast_points("2026-11-19T09:00", mod_aqis))
    )
    assert mod_intel.data_quality.tier == "Moderate"

    # Limited: 10 valid hours (41.7% completeness)
    lim_intel = compute_predictive_intelligence_from_forecast(
        _make_aq_response(_make_forecast_points("2026-11-19T09:00", [75] * 10))
    )
    assert lim_intel.data_quality.tier == "Limited"
    assert lim_intel.data_quality.module_sufficiency.better_windows == "insufficient_data"

    # Insufficient data: 4 valid hours (< 6)
    insuff_intel = compute_predictive_intelligence_from_forecast(
        _make_aq_response(_make_forecast_points("2026-11-19T09:00", [75, None, 80, None]))
    )
    assert insuff_intel.data_quality.tier == "Insufficient data"
    assert insuff_intel.daily_summary.risk_window_evaluation_status == "insufficient_data"
    assert "Insufficient contiguous forecast data" in insuff_intel.daily_summary.deterministic_summary


# ============================================================================
# 6. FastAPI Endpoint Integration & Error Handling Tests
# ============================================================================


def test_intelligence_endpoint_returns_valid_payload_for_nairobi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify GET /api/v1/air-quality/intelligence returns typed deterministic response with timezone & provenance."""
    mock_payload = _build_mock_open_meteo_payload(
        current_time="2026-11-19T09:00",
        timezone_str="Africa/Nairobi",
        timezone_abbreviation="EAT",
        utc_offset_seconds=10800,
        hourly_times=[f"2026-11-19T{h:02d}:00" for h in range(10, 24)],
    )
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get("/api/v1/air-quality/intelligence?location_id=nairobi-ke")
    assert response.status_code == 200
    data = response.json()

    assert data["location"]["id"] == "nairobi-ke"
    assert data["timezone"] == "Africa/Nairobi"
    assert data["data_mode"] == "predictive_intelligence"
    assert data["data_label"] == "ANALYTICAL INTERPRETATION — BASED ON OPEN-METEO CAMS GLOBAL FORECAST"
    assert data["is_demo_data"] is False
    assert data["is_ai_generated"] is False
    assert "score" not in data["data_quality"]
    assert "Open-Meteo" in data["attribution"]["provider_attribution"]
    assert "Copernicus Atmosphere Monitoring Service" in data["attribution"]["cams_attribution"]


def test_intelligence_endpoint_handles_invalid_location_and_provider_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify 404 on invalid location and 504 on upstream timeout without fabricating data."""
    bad_loc = client.get("/api/v1/air-quality/intelligence?location_id=invalid-city")
    assert bad_loc.status_code == 404
    assert bad_loc.json()["detail"]["error_code"] == "invalid_location_id"

    _mock_httpx_client_get(monkeypatch, raise_exc=httpx.ReadTimeout("Upstream timed out"))
    timeout_res = client.get("/api/v1/air-quality/intelligence?location_id=lagos-ng")
    assert timeout_res.status_code == 504
    assert timeout_res.json()["detail"]["error_code"] == "provider_timeout"
    assert timeout_res.json()["detail"]["is_demo_data"] is False
