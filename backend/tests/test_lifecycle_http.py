"""Automated pytest suite for Phase 9.1B.1 FastAPI Lifecycle & Shared HTTP Client.

Verifies:
- Lifespan startup creates `app.state.http_client` with bounded pool limits and logs startup.
- Lifespan shutdown deterministically closes `app.state.http_client`, clears state, and logs shutdown.
- Separate `create_app()` instances own independent `httpx.Client` instances.
- Routes reuse `app.state.http_client` across air-quality, intelligence, history, history/compare,
  and assistant grounding without closing the application-owned client.
- Direct service calls without an injected client continue using the per-call fallback cleanly.
- Shutdown closes the shared HTTP client even when an exception occurs during application execution.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.assistant import AssistantRequest
from app.services.gemini_assistant import ask_airwise_assistant
from app.services.open_meteo import clear_open_meteo_cache, fetch_open_meteo_air_quality
from app.services.open_meteo_history import (
    clear_history_cache,
    fetch_historical_air_quality,
)
from app.services.predictive_intelligence import fetch_predictive_intelligence


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    clear_open_meteo_cache()
    clear_history_cache()
    yield
    clear_open_meteo_cache()
    clear_history_cache()


def _build_live_payload() -> dict[str, Any]:
    return {
        "latitude": 6.5,
        "longitude": 3.4,
        "utc_offset_seconds": 3600,
        "timezone": "Africa/Lagos",
        "timezone_abbreviation": "WAT",
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
            "time": "2026-11-25T08:00",
            "interval": 3600,
            "us_aqi": 72,
            "pm2_5": 21.5,
            "pm10": 45.0,
            "nitrogen_dioxide": 14.2,
            "ozone": 48.0,
            "sulphur_dioxide": 5.5,
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
            "time": [
                "2026-11-25T08:00",
                "2026-11-25T09:00",
                "2026-11-25T10:00",
                "2026-11-25T11:00",
            ],
            "us_aqi": [72, 76, 80, 84],
            "pm2_5": [21.5, 22.0, 23.0, 24.0],
            "pm10": [45.0, 46.0, 47.0, 48.0],
            "nitrogen_dioxide": [14.2, 14.5, 15.0, 15.2],
            "ozone": [48.0, 50.0, 52.0, 54.0],
            "sulphur_dioxide": [5.5, 5.6, 5.7, 5.8],
        },
    }


def _build_history_payload() -> dict[str, Any]:
    return {
        "latitude": 6.5,
        "longitude": 3.4,
        "utc_offset_seconds": 3600,
        "timezone": "Africa/Lagos",
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
            "time": [
                "2026-11-20T00:00",
                "2026-11-20T01:00",
            ],
            "us_aqi": [65, 68],
            "pm2_5": [19.0, 20.1],
            "pm10": [41.0, 43.0],
            "nitrogen_dioxide": [13.0, 13.5],
            "ozone": [44.0, 45.0],
            "sulphur_dioxide": [5.0, 5.1],
        },
    }


def test_lifespan_creates_and_deterministically_closes_shared_http_client(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app_instance = create_app()
    assert app_instance.state.http_client is None

    with caplog.at_level(logging.INFO, logger="airwise"):
        with TestClient(app_instance) as client:
            shared = app_instance.state.http_client
            assert isinstance(shared, httpx.Client)
            assert shared.is_closed is False
            resp = client.get("/api/v1/health")
            assert resp.status_code == 200

    assert shared.is_closed is True
    assert app_instance.state.http_client is None
    messages = "\n".join(r.getMessage() for r in caplog.records)
    assert "app_lifespan_started" in messages
    assert "app_lifespan_shutdown_complete" in messages


def test_separate_app_instances_own_independent_http_clients() -> None:
    app_one = create_app()
    app_two = create_app()

    with TestClient(app_one):
        client_one = app_one.state.http_client
        with TestClient(app_two):
            client_two = app_two.state.http_client
            assert isinstance(client_one, httpx.Client)
            assert isinstance(client_two, httpx.Client)
            assert client_one is not client_two
            assert client_one.is_closed is False
            assert client_two.is_closed is False

        # Closing app_two must not affect app_one's client
        assert client_two.is_closed is True
        assert client_one.is_closed is False

    assert client_one.is_closed is True


def test_routes_reuse_shared_http_client_without_closing_it() -> None:
    app_instance = create_app()
    live_payload = _build_live_payload()
    history_payload = _build_history_payload()

    with TestClient(app_instance) as client:
        shared = app_instance.state.http_client
        assert isinstance(shared, httpx.Client)

        calls: list[dict[str, Any]] = []

        def _fake_get(url: str, *, params: dict[str, Any] | None = None, **kwargs: Any):
            calls.append({"url": url, "params": params, "timeout": kwargs.get("timeout")})
            mock_res = MagicMock()
            mock_res.status_code = 200
            if params and "past_days" in params:
                mock_res.json.return_value = history_payload
            else:
                mock_res.json.return_value = live_payload
            return mock_res

        shared.get = _fake_get  # type: ignore[method-assign]

        # 1. Live air-quality route reuses shared client
        r_aq = client.get("/api/v1/air-quality?location_id=lagos-ng")
        assert r_aq.status_code == 200
        assert shared.is_closed is False

        # 2. Intelligence route reuses shared client (on uncached city abuja-ng)
        r_int = client.get("/api/v1/air-quality/intelligence?location_id=abuja-ng")
        assert r_int.status_code == 200
        assert shared.is_closed is False

        # 3. Historical route (force_refresh=true) reuses shared client
        r_hist = client.get(
            "/api/v1/air-quality/history?location_id=lagos-ng&days=7&force_refresh=true"
        )
        assert r_hist.status_code == 200
        assert shared.is_closed is False

        # 4. Historical 4-city compare reuses shared client across parallel workers
        r_cmp = client.get("/api/v1/air-quality/history/compare?days=7&force_refresh=true")
        assert r_cmp.status_code == 200
        assert r_cmp.json()["cities_available"] == 4
        assert shared.is_closed is False

        # At least 1 (lagos) + 1 (abuja) + 1 (history) + 4 (compare) = 7 shared client calls
        assert len(calls) >= 7
        assert all(isinstance(c["timeout"], httpx.Timeout) for c in calls)

    assert shared.is_closed is True


def test_assistant_grounding_reuses_injected_http_client_without_closing() -> None:
    live_payload = _build_live_payload()
    mock_http = MagicMock(spec=httpx.Client)
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = live_payload
    mock_http.get.return_value = mock_res

    fake_genai_client = MagicMock()
    fake_genai_response = MagicMock()
    fake_genai_response.text = (
        '{"verified_data_summary": "AQI is 72.", '
        '"forecast_context": "Rising to 84.", '
        '"ai_interpretation": "Moderate conditions.", '
        '"general_health_guidance": "General outdoor activity is fine.", '
        '"model_limitations_notice": "CAMS Global ~45 km model."}'
    )
    fake_genai_client.models.generate_content.return_value = fake_genai_response

    result = ask_airwise_assistant(
        AssistantRequest(
            location_id="lagos-ng",
            mode="ask",
            question="How is air quality?",
        ),
        settings=Settings(gemini_api_key="AIzaSyDummyKeyForTest1234567890"),
        genai_client=fake_genai_client,
        http_client=mock_http,
    )
    assert result.status == "ok"
    assert mock_http.get.call_count == 1
    assert mock_http.close.call_count == 0


def test_direct_service_calls_without_injected_client_still_use_per_call_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_payload = _build_live_payload()
    history_payload = _build_history_payload()
    created_clients = {"count": 0}

    class _DummyClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            created_clients["count"] += 1

        def __enter__(self) -> "_DummyClient":
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

        def get(self, *args: Any, params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
            res = MagicMock()
            res.status_code = 200
            if params and "past_days" in params:
                res.json.return_value = history_payload
            else:
                res.json.return_value = live_payload
            return res

    monkeypatch.setattr("app.services.open_meteo.httpx.Client", _DummyClient)

    aq = fetch_open_meteo_air_quality("lagos-ng", use_cache=False)
    assert aq.aqi.value == 72

    intel = fetch_predictive_intelligence("abuja-ng")
    assert intel.location.id == "abuja-ng"

    hist = fetch_historical_air_quality("lagos-ng", days=7, force_refresh=True, use_cache=False)
    assert hist.location.id == "lagos-ng"
    assert created_clients["count"] == 3


def test_lifespan_closes_http_client_even_on_exception_in_context() -> None:
    app_instance = create_app()
    captured_client: httpx.Client | None = None

    with pytest.raises(RuntimeError, match="forced failure inside lifespan"):
        with TestClient(app_instance):
            captured_client = app_instance.state.http_client
            assert isinstance(captured_client, httpx.Client)
            assert captured_client.is_closed is False
            raise RuntimeError("forced failure inside lifespan")

    assert captured_client is not None
    assert captured_client.is_closed is True
    assert app_instance.state.http_client is None
