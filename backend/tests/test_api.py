"""Automated pytest suite for AIRWISE AI FastAPI endpoints and Open-Meteo integration.

All external HTTP calls to Open-Meteo are mocked so tests never depend on a live internet connection.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.demo_data import AVAILABLE_LOCATIONS, build_demo_dashboard
from app.services.open_meteo import clear_open_meteo_cache

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_open_meteo_cache() -> None:
    """Ensure every test starts and ends with an empty Open-Meteo in-memory cache."""
    clear_open_meteo_cache()
    yield
    clear_open_meteo_cache()


def _build_mock_open_meteo_payload(
    *,
    latitude: float = 6.5,
    longitude: float = 3.4,
    timezone_str: str = "Africa/Lagos",
    timezone_abbreviation: str = "WAT",
    utc_offset_seconds: int = 3600,
    current_time: str = "2026-11-18T21:00",
    us_aqi: int | None = 93,
    pm2_5: float | None = 31.6,
    pm10: float | None = 64.2,
    nitrogen_dioxide: float | None = 18.4,
    ozone: float | None = 52.1,
    sulphur_dioxide: float | None = 7.3,
    hourly_times: list[str] | None = None,
) -> dict[str, Any]:
    """Construct a realistic Open-Meteo Air Quality API response dictionary."""
    times = (
        hourly_times
        if hourly_times is not None
        else [
            "2026-11-18T20:00",
            "2026-11-18T21:00",
            "2026-11-18T22:00",
            "2026-11-18T23:00",
        ]
    )
    count = len(times)
    return {
        "latitude": latitude,
        "longitude": longitude,
        "generationtime_ms": 0.45,
        "utc_offset_seconds": utc_offset_seconds,
        "timezone": timezone_str,
        "timezone_abbreviation": timezone_abbreviation,
        "elevation": 14.0,
        "current_units": {
            "time": "iso8601",
            "interval": "seconds",
            "us_aqi": "USAQI",
            "pm2_5": "μg/m³",
            "pm10": "μg/m³",
            "nitrogen_dioxide": "μg/m³",
            "ozone": "μg/m³",
            "sulphur_dioxide": "μg/m³",
        },
        "current": {
            "time": current_time,
            "interval": 3600,
            "us_aqi": us_aqi,
            "pm2_5": pm2_5,
            "pm10": pm10,
            "nitrogen_dioxide": nitrogen_dioxide,
            "ozone": ozone,
            "sulphur_dioxide": sulphur_dioxide,
        },
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
            "us_aqi": [88 if us_aqi is not None else None for _ in range(count)],
            "pm2_5": [29.0 if pm2_5 is not None else None for _ in range(count)],
            "pm10": [60.5 if pm10 is not None else None for _ in range(count)],
            "nitrogen_dioxide": [17.2 if nitrogen_dioxide is not None else None for _ in range(count)],
            "ozone": [49.8 if ozone is not None else None for _ in range(count)],
            "sulphur_dioxide": [6.8 if sulphur_dioxide is not None else None for _ in range(count)],
        },
    }


def _mock_httpx_client_get(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int = 200,
    json_payload: Any = None,
    raw_text: str | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Patch httpx.Client so any outbound GET returns a controlled mock response or raises."""
    mock_get = MagicMock()

    if raise_exc is not None:
        mock_get.side_effect = raise_exc
    else:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = status_code
        if raw_text is not None:
            mock_response.json.side_effect = ValueError("Invalid JSON")
            mock_response.text = raw_text
        else:
            mock_response.json.return_value = json_payload
        mock_get.return_value = mock_response

    class _DummyClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> _DummyClient:
            return self

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            return None

        def get(self, *args: Any, **kwargs: Any) -> Any:
            return mock_get(*args, **kwargs)

    monkeypatch.setattr("app.services.open_meteo.httpx.Client", _DummyClient)
    return mock_get


# ============================================================================
# Existing Day 1 Foundation Tests (Preserved)
# ============================================================================


def test_health_endpoint_returns_ok_and_demo_mode() -> None:
    """Verify GET /api/v1/health returns status ok and explicit demo data mode."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "AIRWISE AI API"
    assert payload["data_mode"] == "demo"
    assert payload["live_provider_connected"] is False


def test_dashboard_endpoint_defaults_to_lagos_and_labels_demo_data() -> None:
    """Verify GET /api/v1/dashboard defaults to Lagos, Nigeria and marks payload as demo data."""
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200

    payload = response.json()
    assert payload["is_demo_data"] is True
    assert payload["data_mode"] == "demo"
    assert "DEMO DATA" in payload["data_source_label"].upper()
    assert "not represent live" in payload["disclaimer"].lower()

    selected = payload["selected_location"]
    assert selected["id"] == "lagos-ng"
    assert selected["display_name"] == "Lagos, Nigeria"

    assert isinstance(payload["available_locations"], list)
    assert len(payload["available_locations"]) >= 1
    assert payload["summary"]["aqi_value"] > 0
    assert len(payload["pollutants"]) == 4
    assert len(payload["health_advisory"]["groups"]) >= 2
    assert len(payload["daily_recommendations"]) >= 3
    assert len(payload["assistant_preview"]["sample_prompts"]) >= 2


def test_dashboard_endpoint_supports_location_query_and_fallback() -> None:
    """Verify GET /api/v1/dashboard supports selecting another demo location and safe fallback."""
    abuja_response = client.get("/api/v1/dashboard?location=abuja-ng")
    assert abuja_response.status_code == 200
    assert abuja_response.json()["selected_location"]["id"] == "abuja-ng"
    assert abuja_response.json()["is_demo_data"] is True

    fallback_response = client.get("/api/v1/dashboard?location=unknown-city")
    assert fallback_response.status_code == 200
    assert fallback_response.json()["selected_location"]["id"] == "lagos-ng"


def test_cors_restricts_to_allowed_frontend_origin() -> None:
    """Verify CORS allows configured localhost frontend origin and rejects arbitrary external origins."""
    allowed = client.options(
        "/api/v1/dashboard",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"

    disallowed = client.options(
        "/api/v1/dashboard",
        headers={
            "Origin": "https://malicious.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert disallowed.headers.get("access-control-allow-origin") is None


# ============================================================================
# Phase 2 Open-Meteo Air Quality API Integration Tests (Preserved)
# ============================================================================


def test_air_quality_successful_provider_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """1. Verify successful Open-Meteo response parsing, structure, and current vs hourly separation."""
    mock_payload = _build_mock_open_meteo_payload(
        current_time="2026-11-18T21:00",
        us_aqi=93,
        pm2_5=31.6,
        pm10=64.2,
        nitrogen_dioxide=18.4,
        ozone=52.1,
        sulphur_dioxide=7.3,
    )
    mock_get = _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response.status_code == 200
    assert mock_get.call_count == 1

    data = response.json()
    assert data["location"]["id"] == "lagos-ng"
    assert data["location"]["display_name"] == "Lagos, Nigeria"
    assert data["data_mode"] == "live_model"
    assert data["aqi"]["value"] == 93
    assert data["aqi"]["band"] == "Moderate"
    assert data["aqi"]["status"] == "available"
    assert data["pm2_5"]["value"] == 31.6
    assert data["pm10"]["value"] == 64.2
    assert data["no2"]["value"] == 18.4
    assert data["o3"]["value"] == 52.1
    assert data["so2"]["value"] == 7.3

    # Verify distinction between current model conditions and future hourly forecast
    assert data["current_conditions"]["classification"] == "current_model"
    assert data["hourly_forecast"]["classification"] == "hourly_forecast"
    assert data["hourly_forecast"]["hours_returned"] == 2
    assert data["hourly_forecast"]["points"][0]["classification"] == "hourly_forecast"
    assert data["hourly_forecast"]["points"][0]["time"] == "2026-11-18T22:00"


def test_air_quality_handles_missing_pollutant_values_individually(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2. Verify missing or null pollutant values are handled individually without failing or faking data."""
    mock_payload = _build_mock_open_meteo_payload(
        us_aqi=None,
        pm2_5=28.4,
        pm10=None,
        nitrogen_dioxide=14.1,
        ozone=None,
        sulphur_dioxide=None,
    )
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response.status_code == 200
    data = response.json()

    assert data["aqi"]["value"] is None
    assert data["aqi"]["band"] is None
    assert data["aqi"]["status"] == "unavailable"

    assert data["pm2_5"]["value"] == 28.4
    assert data["pm2_5"]["status"] == "available"

    assert data["pm10"]["value"] is None
    assert data["pm10"]["status"] == "unavailable"

    assert data["no2"]["value"] == 14.1
    assert data["no2"]["status"] == "available"

    assert data["o3"]["value"] is None
    assert data["o3"]["status"] == "unavailable"

    assert data["so2"]["value"] is None
    assert data["so2"]["status"] == "unavailable"


def test_air_quality_rejects_invalid_provider_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """3. Verify malformed JSON or missing 'current' block returns a clean 502 structured error."""
    # Case A: Non-JSON body
    _mock_httpx_client_get(monkeypatch, status_code=200, raw_text="<html>Bad Gateway</html>")
    res_non_json = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert res_non_json.status_code == 502
    detail_a = res_non_json.json()["detail"]
    assert detail_a["error_code"] == "provider_invalid_payload"
    assert detail_a["is_demo_data"] is False

    # Case B: Missing 'current' object
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload={"latitude": 6.5})
    res_missing_current = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert res_missing_current.status_code == 502
    assert res_missing_current.json()["detail"]["error_code"] == "provider_invalid_payload"

    # Case C: Negative pollutant concentration
    bad_numeric = _build_mock_open_meteo_payload(pm2_5=-5.0)
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=bad_numeric)
    res_negative = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert res_negative.status_code == 502
    assert res_negative.json()["detail"]["error_code"] == "provider_invalid_payload"


def test_air_quality_handles_provider_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """4. Verify provider timeout returns HTTP 504 with structured error and does not cache failure."""
    mock_get = _mock_httpx_client_get(
        monkeypatch,
        raise_exc=httpx.ReadTimeout("Upstream read timed out"),
    )

    response = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response.status_code == 504
    detail = response.json()["detail"]
    assert detail["error_code"] == "provider_timeout"
    assert detail["data_mode"] == "unavailable"
    assert detail["is_demo_data"] is False

    # Subsequent call must retry upstream (errors are never cached)
    response_retry = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response_retry.status_code == 504
    assert mock_get.call_count == 2


def test_air_quality_handles_upstream_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """5. Verify upstream HTTP 500/503 returns HTTP 502 without leaking internal stack traces."""
    _mock_httpx_client_get(
        monkeypatch,
        status_code=503,
        json_payload={"error": True, "reason": "Service unavailable"},
    )

    response = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["error_code"] == "provider_upstream_http_error"
    assert "HTTP 503" in detail["message"]
    assert detail["is_demo_data"] is False


def test_air_quality_rejects_invalid_location_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """6. Verify an unconfigured location_id returns HTTP 404 without calling Open-Meteo."""
    mock_get = _mock_httpx_client_get(
        monkeypatch,
        status_code=200,
        json_payload=_build_mock_open_meteo_payload(),
    )

    response = client.get("/api/v1/air-quality?location_id=unknown-city")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["error_code"] == "invalid_location_id"
    assert "lagos-ng" in detail["message"]
    assert mock_get.call_count == 0


@pytest.mark.parametrize(
    "expected_loc",
    AVAILABLE_LOCATIONS,
    ids=[loc.id for loc in AVAILABLE_LOCATIONS],
)
def test_air_quality_supports_all_four_configured_locations(
    monkeypatch: pytest.MonkeyPatch,
    expected_loc: Any,
) -> None:
    """7. Verify all four configured locations (Lagos, Abuja, Nairobi, Accra) use exact coordinates & timezones."""
    mock_payload = _build_mock_open_meteo_payload(
        latitude=expected_loc.latitude,
        longitude=expected_loc.longitude,
        timezone_str=expected_loc.timezone,
    )
    mock_get = _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get(f"/api/v1/air-quality?location_id={expected_loc.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["location"]["id"] == expected_loc.id
    assert data["location"]["latitude"] == expected_loc.latitude
    assert data["location"]["longitude"] == expected_loc.longitude
    assert data["location"]["timezone"] == expected_loc.timezone

    # Verify outbound query parameters passed to Open-Meteo
    _, called_kwargs = mock_get.call_args
    sent_params = called_kwargs["params"]
    assert sent_params["latitude"] == expected_loc.latitude
    assert sent_params["longitude"] == expected_loc.longitude
    assert sent_params["timezone"] == expected_loc.timezone
    assert sent_params["domains"] == "cams_global"
    for var in ("us_aqi", "pm2_5", "pm10", "nitrogen_dioxide", "ozone", "sulphur_dioxide"):
        assert var in sent_params["current"]
        assert var in sent_params["hourly"]


def test_air_quality_preserves_timestamps_and_normalizes_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """8. Verify provider observation_time is preserved verbatim and units are normalized."""
    provider_obs_time = "2026-11-18T19:00"
    mock_payload = _build_mock_open_meteo_payload(
        current_time=provider_obs_time,
        timezone_str="Africa/Nairobi",
        timezone_abbreviation="EAT",
        utc_offset_seconds=10800,
    )
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get("/api/v1/air-quality?location_id=nairobi-ke")
    assert response.status_code == 200
    data = response.json()

    assert data["observation_time"] == provider_obs_time
    assert data["current_conditions"]["observation_time"] == provider_obs_time
    assert data["retrieval_time"].endswith("Z")
    assert data["timezone"] == "Africa/Nairobi"
    assert data["timezone_abbreviation"] == "EAT"

    assert data["units"] == {
        "us_aqi": "US AQI",
        "pm2_5": "µg/m³",
        "pm10": "µg/m³",
        "nitrogen_dioxide": "µg/m³",
        "ozone": "µg/m³",
        "sulphur_dioxide": "µg/m³",
    }


def test_air_quality_provenance_and_model_data_disclaimer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """9. Verify response includes explicit model-based estimate label and never claims roadside station data."""
    mock_payload = _build_mock_open_meteo_payload()
    mock_get = _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    first_res = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert first_res.status_code == 200
    first_data = first_res.json()

    assert first_data["data_label"] == "LIVE PROVIDER DATA — MODEL-BASED ESTIMATE"
    assert first_data["provenance"]["data_label"] == "LIVE PROVIDER DATA — MODEL-BASED ESTIMATE"
    assert first_data["provenance"]["is_physical_station_measurement"] is False
    assert first_data["provenance"]["is_demo_data"] is False
    assert first_data["provenance"]["model_domain"] == "cams_global"
    assert first_data["provenance"]["cache_hit"] is False
    assert "not direct measurements from physical roadside" in first_data["disclaimer"]

    # Second call should hit the in-memory TTL cache without a second outbound HTTP request
    second_res = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert second_res.status_code == 200
    assert second_res.json()["provenance"]["cache_hit"] is True
    assert mock_get.call_count == 1


def test_air_quality_never_silently_substitutes_demo_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """10. Verify missing provider values are never replaced with Lagos demo values (AQI 112, PM2.5 39.8, etc.)."""
    demo_lagos = build_demo_dashboard("lagos-ng")
    demo_pm25 = next(p.value for p in demo_lagos.pollutants if p.code == "PM2.5")
    demo_aqi = demo_lagos.summary.aqi_value

    all_null_payload = _build_mock_open_meteo_payload(
        us_aqi=None,
        pm2_5=None,
        pm10=None,
        nitrogen_dioxide=None,
        ozone=None,
        sulphur_dioxide=None,
    )
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=all_null_payload)

    response = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response.status_code == 200
    data = response.json()

    assert data["provenance"]["is_demo_data"] is False
    assert data["aqi"]["value"] is None
    assert data["aqi"]["value"] != demo_aqi
    assert data["pm2_5"]["value"] is None
    assert data["pm2_5"]["value"] != demo_pm25
    assert data["pm10"]["value"] is None
    assert data["no2"]["value"] is None
    assert data["o3"]["value"] is None
    assert data["so2"]["value"] is None


# ============================================================================
# Phase 2.1 Air Quality Data Integrity Regression Tests
# ============================================================================


def test_historical_hourly_points_are_never_classified_as_forecasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression 1: Historical hourly points (< observation_time) are classified as 'historical_model' and excluded from forecast points."""
    mock_payload = _build_mock_open_meteo_payload(
        current_time="2026-11-18T14:00",
        hourly_times=[
            "2026-11-18T11:00",
            "2026-11-18T12:00",
            "2026-11-18T13:00",
            "2026-11-18T14:00",
            "2026-11-18T15:00",
        ],
    )
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response.status_code == 200
    data = response.json()

    forecast_times = [pt["time"] for pt in data["hourly_forecast"]["points"]]
    assert "2026-11-18T11:00" not in forecast_times
    assert "2026-11-18T12:00" not in forecast_times
    assert "2026-11-18T13:00" not in forecast_times
    assert "2026-11-18T14:00" not in forecast_times
    assert forecast_times == ["2026-11-18T15:00"]

    assert data["hourly_forecast"]["historical_hours_count"] == 3
    historical_points = data["hourly_forecast"]["historical_points"]
    assert len(historical_points) == 3
    assert all(pt["classification"] == "historical_model" for pt in historical_points)


def test_current_model_timestamps_are_correctly_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression 2: Current model timestamp (== observation_time) is classified as 'current_model'."""
    mock_payload = _build_mock_open_meteo_payload(
        current_time="2026-11-18T14:00",
        hourly_times=[
            "2026-11-18T13:00",
            "2026-11-18T14:00",
            "2026-11-18T15:00",
        ],
    )
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response.status_code == 200
    data = response.json()

    assert data["current_conditions"]["classification"] == "current_model"
    assert data["current_conditions"]["observation_time"] == "2026-11-18T14:00"

    current_hour_pt = data["hourly_forecast"]["current_hour_point"]
    assert current_hour_pt is not None
    assert current_hour_pt["time"] == "2026-11-18T14:00"
    assert current_hour_pt["classification"] == "current_model"

    timeline_classifications = {pt["time"]: pt["classification"] for pt in data["hourly_timeline"]}
    assert timeline_classifications["2026-11-18T13:00"] == "historical_model"
    assert timeline_classifications["2026-11-18T14:00"] == "current_model"
    assert timeline_classifications["2026-11-18T15:00"] == "hourly_forecast"


def test_future_points_are_classified_as_forecasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression 3: Future points (> observation_time) are classified as 'hourly_forecast'."""
    mock_payload = _build_mock_open_meteo_payload(
        current_time="2026-11-18T14:00",
        hourly_times=[
            "2026-11-18T14:00",
            "2026-11-18T15:00",
            "2026-11-18T16:00",
            "2026-11-18T17:00",
        ],
    )
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response.status_code == 200
    data = response.json()

    assert data["hourly_forecast"]["hours_returned"] == 3
    future_points = data["hourly_forecast"]["points"]
    assert [pt["time"] for pt in future_points] == [
        "2026-11-18T15:00",
        "2026-11-18T16:00",
        "2026-11-18T17:00",
    ]
    assert all(pt["classification"] == "hourly_forecast" for pt in future_points)


def test_empty_future_forecast_arrays_are_handled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression 4: When provider returns only historical/current hours and no future points, forecast points array is empty."""
    mock_payload = _build_mock_open_meteo_payload(
        current_time="2026-11-18T23:00",
        hourly_times=[
            "2026-11-18T21:00",
            "2026-11-18T22:00",
            "2026-11-18T23:00",
        ],
    )
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response.status_code == 200
    data = response.json()

    assert data["hourly_forecast"]["hours_returned"] == 0
    assert data["hourly_forecast"]["points"] == []
    assert data["hourly_forecast"]["historical_hours_count"] == 2
    assert data["hourly_forecast"]["current_hour_point"]["time"] == "2026-11-18T23:00"
    assert data["hourly_forecast"]["current_hour_point"]["classification"] == "current_model"


def test_timezone_differences_do_not_cause_incorrect_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression 5: Timezone-aware datetime comparisons accurately classify timestamps across different UTC offsets."""
    # Nairobi is UTC+3 (Africa/Nairobi).
    # Current observation time: 2026-11-18T21:00+03:00 (which is 18:00 UTC).
    # Hourly points mix explicit UTC ('Z'), +01:00 (WAT), and local naive Africa/Nairobi (+03:00):
    # - '2026-11-18T17:00Z'       -> 17:00 UTC (< 18:00 UTC) -> historical_model
    # - '2026-11-18T19:00+01:00'  -> 18:00 UTC (== 18:00 UTC) -> current_model
    # - '2026-11-18T22:00'        -> 22:00 EAT = 19:00 UTC (> 18:00 UTC) -> hourly_forecast
    mock_payload = _build_mock_open_meteo_payload(
        current_time="2026-11-18T21:00+03:00",
        timezone_str="Africa/Nairobi",
        timezone_abbreviation="EAT",
        utc_offset_seconds=10800,
        hourly_times=[
            "2026-11-18T17:00Z",
            "2026-11-18T19:00+01:00",
            "2026-11-18T22:00",
        ],
    )
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get("/api/v1/air-quality?location_id=nairobi-ke")
    assert response.status_code == 200
    data = response.json()

    assert data["hourly_forecast"]["historical_hours_count"] == 1
    assert data["hourly_forecast"]["historical_points"][0]["time"] == "2026-11-18T17:00Z"
    assert data["hourly_forecast"]["historical_points"][0]["classification"] == "historical_model"

    assert data["hourly_forecast"]["current_hour_point"]["time"] == "2026-11-18T19:00+01:00"
    assert data["hourly_forecast"]["current_hour_point"]["classification"] == "current_model"

    assert data["hourly_forecast"]["hours_returned"] == 1
    assert data["hourly_forecast"]["points"][0]["time"] == "2026-11-18T22:00"
    assert data["hourly_forecast"]["points"][0]["classification"] == "hourly_forecast"


def test_cams_global_resolution_and_temporal_metadata_are_accurate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression 6: CAMS Global spatial resolution (~0.4° / 45 km), 3-hourly source resolution, and 5-day forecast horizon are documented."""
    mock_payload = _build_mock_open_meteo_payload()
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response.status_code == 200
    data = response.json()

    prov = data["provenance"]
    meta = prov["model_metadata"]

    assert "0.4" in prov["spatial_resolution"] and "45 km" in prov["spatial_resolution"]
    assert "0.4" in meta["spatial_resolution"] and "45 km" in meta["spatial_resolution"]
    assert "3-hourly" in prov["source_temporal_resolution"]
    assert "3-hourly" in meta["source_temporal_resolution"]
    assert "1-hourly" in prov["api_timestamp_interval"]
    assert "not independent hourly physical" in meta["api_timestamp_interval"]
    assert "5 days" in prov["forecast_availability"]
    assert "5 days" in meta["forecast_availability"]


def test_provider_and_cams_attribution_are_included(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression 7: Open-Meteo Air Quality API and Copernicus CAMS attribution are exposed in provenance and top-level response."""
    mock_payload = _build_mock_open_meteo_payload()
    _mock_httpx_client_get(monkeypatch, status_code=200, json_payload=mock_payload)

    response = client.get("/api/v1/air-quality?location_id=lagos-ng")
    assert response.status_code == 200
    data = response.json()

    top_attr = data["attribution"]
    prov_attr = data["provenance"]["attribution"]

    for attr_block in (top_attr, prov_attr):
        assert "Open-Meteo" in attr_block["provider_attribution"]
        assert "Copernicus Atmosphere Monitoring Service" in attr_block["cams_attribution"]
        assert "CAMS" in attr_block["cams_attribution"]
        assert "Open-Meteo Air Quality API" in attr_block["sources"]
        assert "Copernicus Atmosphere Monitoring Service (CAMS) Global" in attr_block["sources"]
