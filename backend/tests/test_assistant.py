"""Automated pytest suite for Phase 5 Gemini Air Quality Assistant endpoints and grounding.

All Gemini SDK calls and Open-Meteo HTTP calls are mocked so tests run offline deterministically.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.services.open_meteo import clear_open_meteo_cache
from tests.test_api import _build_mock_open_meteo_payload, _mock_httpx_client_get

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_cache_and_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset Open-Meteo cache before and after every assistant test."""
    clear_open_meteo_cache()
    yield
    clear_open_meteo_cache()


def _configure_backend_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gemini_api_key: str | None = "test-fake-key-never-logged",
    gemini_model: str = "gemini-2.5-flash",
) -> Settings:
    """Return a controlled Settings instance and patch get_settings in assistant service."""
    test_settings = Settings(
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        gemini_timeout_seconds=10.0,
    )
    monkeypatch.setattr("app.services.gemini_assistant.get_settings", lambda: test_settings)
    return test_settings


def _mock_gemini_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response_json: dict[str, Any] | None = None,
    raw_text: str | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Patch _create_genai_client so Gemini SDK calls return controlled outputs or raise."""
    mock_generate = MagicMock()

    if raise_exc is not None:
        mock_generate.side_effect = raise_exc
    else:
        mock_response = MagicMock()
        if raw_text is not None:
            mock_response.text = raw_text
        else:
            mock_response.text = json.dumps(
                response_json
                or {
                    "verified_data_summary": (
                        "Verified Open-Meteo CAMS Global model estimate for Lagos, Nigeria at "
                        "2026-11-18T21:00 (Africa/Lagos): US AQI 93 (Moderate), PM2.5 31.6 µg/m³, "
                        "PM10 64.2 µg/m³, NO2 18.4 µg/m³, O3 52.1 µg/m³, SO2 7.3 µg/m³."
                    ),
                    "forecast_context": (
                        "2 future forecast hours are available (2026-11-18T22:00 and 2026-11-18T23:00), "
                        "both with US AQI 88 (Moderate)."
                    ),
                    "ai_interpretation": (
                        "Under these Moderate model conditions, most residents can pursue normal outdoor "
                        "activities, though people sensitive to fine particulate matter may prefer shorter "
                        "or less intense outdoor sessions."
                    ),
                    "general_health_guidance": (
                        "General informational guidance only (not medical advice): monitor personal comfort "
                        "during vigorous outdoor exercise and consult a healthcare professional for personal health conditions."
                    ),
                    "model_limitations_notice": (
                        "Open-Meteo CAMS Global provides atmospheric model estimates on an ~0.4° (~45 km) "
                        "grid with 3-hourly native resolution; it is not physical roadside sensor telemetry "
                        "and cannot establish precise street-level or indoor exposure."
                    ),
                }
            )
        mock_generate.return_value = mock_response

    fake_client = MagicMock()
    fake_client.models.generate_content = mock_generate
    monkeypatch.setattr("app.services.gemini_assistant._create_genai_client", lambda _cfg: fake_client)
    return mock_generate


def test_assistant_status_reports_unavailable_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify GET /api/v1/assistant/status reports assistant_unavailable when GEMINI_API_KEY is unset."""
    _configure_backend_settings(monkeypatch, gemini_api_key=None)
    response = client.get("/api/v1/assistant/status")
    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is False
    assert data["status"] == "assistant_unavailable"
    assert data["sdk"] == "google-genai"


def test_assistant_missing_api_key_returns_503_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify POST /api/v1/assistant/ask returns HTTP 503 assistant_unavailable when GEMINI_API_KEY is missing."""
    _configure_backend_settings(monkeypatch, gemini_api_key=None)

    response = client.post(
        "/api/v1/assistant/ask",
        json={
            "location_id": "lagos-ng",
            "mode": "ask",
            "question": "Is the air quality safe for outdoor exercise in Lagos?",
        },
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error_code"] == "assistant_unavailable"
    assert detail["assistant_status"] == "assistant_unavailable"
    assert "GEMINI_API_KEY" in detail["message"]


def test_assistant_successful_gemini_response_with_verified_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify successful mocked Gemini response passes verified Open-Meteo data and separates response sections."""
    _configure_backend_settings(monkeypatch)
    _mock_httpx_client_get(
        monkeypatch,
        status_code=200,
        json_payload=_build_mock_open_meteo_payload(
            current_time="2026-11-18T21:00",
            us_aqi=93,
            pm2_5=31.6,
        ),
    )
    mock_generate = _mock_gemini_client(monkeypatch)

    response = client.post(
        "/api/v1/assistant/ask",
        json={
            "location_id": "lagos-ng",
            "mode": "ask",
            "question": "Is the air quality safe for outdoor exercise in Lagos?",
        },
    )
    assert response.status_code == 200
    assert mock_generate.call_count == 1

    data = response.json()
    assert data["status"] == "ok"
    assert data["is_ai_generated"] is True
    assert data["model"] == "gemini-2.5-flash"
    assert data["location"]["id"] == "lagos-ng"
    assert data["verified_context"]["data_status"] == "available"
    assert data["verified_context"]["us_aqi"] == 93
    assert data["verified_context"]["observation_time"] == "2026-11-18T21:00"
    assert data["provenance"]["is_physical_station_measurement"] is False
    assert "Open-Meteo" in data["attribution"]["provider_attribution"]
    assert "Copernicus Atmosphere Monitoring Service" in data["attribution"]["cams_attribution"]

    sections = data["sections"]
    assert "93" in sections["verified_data_summary"]
    assert "2026-11-18T22:00" in sections["forecast_context"]
    assert sections["ai_interpretation"]
    assert sections["general_health_guidance"]
    assert "45 km" in sections["model_limitations_notice"]

    # Confirm the prompt sent to Gemini included verified context and system anti-fabrication rules
    call_kwargs = mock_generate.call_args.kwargs
    assert "lagos-ng" in call_kwargs["contents"]
    assert "31.6" in call_kwargs["contents"]
    assert "NEVER invent, guess, or fabricate" in call_kwargs["config"].system_instruction


def test_assistant_handles_gemini_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Gemini timeout returns HTTP 504 with clean structured error."""
    _configure_backend_settings(monkeypatch)
    _mock_httpx_client_get(
        monkeypatch,
        status_code=200,
        json_payload=_build_mock_open_meteo_payload(),
    )
    _mock_gemini_client(monkeypatch, raise_exc=TimeoutError("Gemini request timed out"))

    response = client.post(
        "/api/v1/assistant/ask",
        json={
            "location_id": "lagos-ng",
            "mode": "ask",
            "question": "What does today's PM2.5 reading mean?",
        },
    )
    assert response.status_code == 504
    detail = response.json()["detail"]
    assert detail["error_code"] == "assistant_timeout"
    assert "timed out" in detail["message"].lower()


def test_assistant_handles_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Gemini 429 rate-limit error returns HTTP 429 without exposing internal details."""
    _configure_backend_settings(monkeypatch)
    _mock_httpx_client_get(
        monkeypatch,
        status_code=200,
        json_payload=_build_mock_open_meteo_payload(),
    )
    _mock_gemini_client(
        monkeypatch,
        raise_exc=RuntimeError("429 RESOURCE_EXHAUSTED: Quota exceeded"),
    )

    response = client.post(
        "/api/v1/assistant/ask",
        json={
            "location_id": "lagos-ng",
            "mode": "ask",
            "question": "Which pollutants are elevated?",
        },
    )
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["error_code"] == "assistant_rate_limited"


def test_assistant_handles_malformed_gemini_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify non-JSON or incomplete JSON from Gemini returns HTTP 502 assistant_malformed_response."""
    _configure_backend_settings(monkeypatch)
    _mock_httpx_client_get(
        monkeypatch,
        status_code=200,
        json_payload=_build_mock_open_meteo_payload(),
    )

    # Case A: Invalid JSON text
    _mock_gemini_client(monkeypatch, raw_text="Here is my answer without JSON structure.")
    res_invalid = client.post(
        "/api/v1/assistant/ask",
        json={
            "location_id": "lagos-ng",
            "mode": "ask",
            "question": "Explain PM2.5",
        },
    )
    assert res_invalid.status_code == 502
    assert res_invalid.json()["detail"]["error_code"] == "assistant_malformed_response"

    # Case B: Missing required structured fields
    _mock_gemini_client(monkeypatch, raw_text=json.dumps({"ai_interpretation": "Incomplete"}))
    res_missing_keys = client.post(
        "/api/v1/assistant/ask",
        json={
            "location_id": "lagos-ng",
            "mode": "ask",
            "question": "Explain PM2.5",
        },
    )
    assert res_missing_keys.status_code == 502
    assert res_missing_keys.json()["detail"]["error_code"] == "assistant_malformed_response"


def test_assistant_handles_missing_air_quality_values_and_prevents_fabrication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify missing pollutant/AQI fields are passed explicitly as null/unavailable and never fabricated."""
    _configure_backend_settings(monkeypatch)
    _mock_httpx_client_get(
        monkeypatch,
        status_code=200,
        json_payload=_build_mock_open_meteo_payload(
            us_aqi=None,
            pm2_5=24.1,
            pm10=None,
            nitrogen_dioxide=None,
            ozone=41.0,
            sulphur_dioxide=None,
            hourly_times=["2026-11-18T20:00", "2026-11-18T21:00"],  # No future forecast points
        ),
    )
    mock_generate = _mock_gemini_client(monkeypatch)

    response = client.post(
        "/api/v1/assistant/ask",
        json={
            "location_id": "lagos-ng",
            "mode": "activity_planner",
            "question": "Plan my outdoor activities for today in Lagos.",
        },
    )
    assert response.status_code == 200
    data = response.json()

    # Verified snapshot accurately reports missing values without substituting demo values (e.g. AQI 112 / PM2.5 39.8)
    snap = data["verified_context"]
    assert snap["us_aqi"] is None
    assert "us_aqi" in snap["missing_fields"]
    assert "PM10" in snap["missing_fields"]
    assert "NO2" in snap["missing_fields"]
    assert "SO2" in snap["missing_fields"]
    assert "hourly_forecast" in snap["missing_fields"]
    assert snap["forecast_summary"]["hours_available"] == 0

    # Verify the exact context passed to Gemini contained empty future forecast array & null unavailable fields
    sent_prompt = mock_generate.call_args.kwargs["contents"]
    assert '"future_hourly_forecast_points": []' in sent_prompt
    assert '"us_aqi": null' in sent_prompt
    assert "Do NOT invent a safe hour" in sent_prompt


def test_assistant_passes_only_future_forecast_context_for_activity_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify activity_planner passes strictly future forecast points (> observation_time) and excludes historical hours."""
    _configure_backend_settings(monkeypatch)
    _mock_httpx_client_get(
        monkeypatch,
        status_code=200,
        json_payload=_build_mock_open_meteo_payload(
            current_time="2026-11-18T15:00",
            hourly_times=[
                "2026-11-18T13:00",
                "2026-11-18T14:00",
                "2026-11-18T15:00",
                "2026-11-18T16:00",
                "2026-11-18T17:00",
            ],
        ),
    )
    mock_generate = _mock_gemini_client(monkeypatch)

    response = client.post(
        "/api/v1/assistant/ask",
        json={
            "location_id": "abuja-ng",
            "mode": "activity_planner",
            "question": "When can I go cycling or walking in Abuja?",
        },
    )
    assert response.status_code == 200
    data = response.json()

    forecast_summary = data["verified_context"]["forecast_summary"]
    assert forecast_summary["hours_available"] == 2
    assert forecast_summary["first_forecast_time"] == "2026-11-18T16:00"
    assert forecast_summary["last_forecast_time"] == "2026-11-18T17:00"

    sent_prompt = mock_generate.call_args.kwargs["contents"]
    assert "2026-11-18T16:00" in sent_prompt
    assert "2026-11-18T17:00" in sent_prompt
    assert "2026-11-18T13:00" not in sent_prompt
    assert "2026-11-18T14:00" not in sent_prompt


def test_assistant_city_comparison_fetches_all_four_cities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify city_comparison mode returns verified snapshots for all four configured cities."""
    _configure_backend_settings(monkeypatch)
    _mock_httpx_client_get(
        monkeypatch,
        status_code=200,
        json_payload=_build_mock_open_meteo_payload(),
    )
    _mock_gemini_client(monkeypatch)

    response = client.post(
        "/api/v1/assistant/ask",
        json={
            "location_id": "lagos-ng",
            "mode": "city_comparison",
            "question": "Compare air quality across Lagos, Abuja, Nairobi, and Accra.",
        },
    )
    assert response.status_code == 200
    data = response.json()

    city_ids = [snap["location"]["id"] for snap in data["city_comparisons"]]
    assert city_ids == ["lagos-ng", "abuja-ng", "nairobi-ke", "accra-gh"]
    assert all(snap["observation_time"] is not None for snap in data["city_comparisons"])
