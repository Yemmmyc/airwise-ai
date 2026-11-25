"""Deterministic concurrency and single-flight TTL cache tests (Phase 9.1B.2).

Uses threading.Event and threading.Barrier (zero fragile sleep-based timing assertions)
and joins all worker threads cleanly.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.history_store import SQLiteHistoryStore
from app.services.open_meteo import (
    OpenMeteoTimeoutError,
    clear_open_meteo_cache,
    fetch_open_meteo_air_quality,
)
from app.services.open_meteo_history import (
    clear_history_cache,
    fetch_historical_air_quality,
)


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    clear_open_meteo_cache()
    clear_history_cache()
    yield
    clear_open_meteo_cache()
    clear_history_cache()


def _live_payload(us_aqi: int = 75, tz: str = "Africa/Lagos") -> dict[str, Any]:
    return {
        "latitude": 6.5,
        "longitude": 3.4,
        "utc_offset_seconds": 3600,
        "timezone": tz,
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
            "us_aqi": us_aqi,
            "pm2_5": 22.0,
            "pm10": 44.0,
            "nitrogen_dioxide": 15.0,
            "ozone": 46.0,
            "sulphur_dioxide": 5.0,
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
            "us_aqi": [us_aqi, us_aqi + 4, us_aqi + 8, us_aqi + 2],
            "pm2_5": [22.0, 23.0, 24.0, 22.5],
            "pm10": [44.0, 45.0, 46.0, 44.5],
            "nitrogen_dioxide": [15.0, 15.5, 16.0, 15.2],
            "ozone": [46.0, 48.0, 50.0, 47.0],
            "sulphur_dioxide": [5.0, 5.1, 5.2, 5.0],
        },
    }


def _history_payload(us_aqi: int = 64) -> dict[str, Any]:
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
            "time": ["2026-11-20T00:00", "2026-11-20T01:00"],
            "us_aqi": [us_aqi, us_aqi + 2],
            "pm2_5": [18.0, 19.0],
            "pm10": [40.0, 41.0],
            "nitrogen_dioxide": [12.0, 12.5],
            "ozone": [42.0, 43.0],
            "sulphur_dioxide": [4.5, 4.6],
        },
    }


def _mock_response(payload: dict[str, Any]) -> MagicMock:
    res = MagicMock()
    res.status_code = 200
    res.json.return_value = payload
    return res


def test_same_key_live_cold_cache_deduplicates_concurrent_requests() -> None:
    worker_count = 5
    start_barrier = threading.Barrier(worker_count, timeout=5.0)
    entered_fetch = threading.Event()
    release_fetch = threading.Event()
    fetch_count = {"n": 0}
    fetch_lock = threading.Lock()

    http_client = MagicMock(spec=httpx.Client)

    def _fake_get(*args: Any, **kwargs: Any) -> MagicMock:
        with fetch_lock:
            fetch_count["n"] += 1
        entered_fetch.set()
        assert release_fetch.wait(timeout=5.0)
        return _mock_response(_live_payload(us_aqi=81))

    http_client.get.side_effect = _fake_get

    results: list[Any] = [None] * worker_count
    errors: list[BaseException] = []

    def _worker(idx: int) -> None:
        try:
            start_barrier.wait()
            results[idx] = fetch_open_meteo_air_quality("lagos-ng", http_client=http_client)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(worker_count)]
    for t in threads:
        t.start()

    assert entered_fetch.wait(timeout=5.0)
    release_fetch.set()

    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive()

    assert not errors
    assert fetch_count["n"] == 1
    assert all(r.aqi.value == 81 for r in results)
    cache_hits = [r.provenance.cache_hit for r in results]
    assert cache_hits.count(False) == 1
    assert cache_hits.count(True) == worker_count - 1


def test_same_key_historical_cold_cache_deduplicates_concurrent_requests(
    tmp_path: Path,
) -> None:
    worker_count = 4
    start_barrier = threading.Barrier(worker_count, timeout=5.0)
    entered_fetch = threading.Event()
    release_fetch = threading.Event()
    fetch_count = {"n": 0}
    fetch_lock = threading.Lock()
    store = SQLiteHistoryStore(tmp_path / "hist_dedup.db")
    fixed_now = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)

    http_client = MagicMock(spec=httpx.Client)

    def _fake_get(*args: Any, **kwargs: Any) -> MagicMock:
        with fetch_lock:
            fetch_count["n"] += 1
        entered_fetch.set()
        assert release_fetch.wait(timeout=5.0)
        return _mock_response(_history_payload(us_aqi=66))

    http_client.get.side_effect = _fake_get

    results: list[Any] = [None] * worker_count
    errors: list[BaseException] = []

    def _worker(idx: int) -> None:
        try:
            start_barrier.wait()
            results[idx] = fetch_historical_air_quality(
                "lagos-ng",
                days=7,
                store=store,
                http_client=http_client,
                now_utc=fixed_now,
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(worker_count)]
    for t in threads:
        t.start()

    assert entered_fetch.wait(timeout=5.0)
    release_fetch.set()

    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive()

    assert not errors
    assert fetch_count["n"] == 1
    origins = [r.origin.storage_origin for r in results]
    assert origins.count("fresh_provider_retrieval") == 1
    assert origins.count("historical_cache") == worker_count - 1


def test_different_keys_fetch_concurrently_without_blocking_each_other() -> None:
    # A Barrier(2) INSIDE the mock HTTP handler succeeds ONLY if both cities
    # execute upstream fetches concurrently (would deadlock under a global lock).
    both_in_flight = threading.Barrier(2, timeout=5.0)
    http_client = MagicMock(spec=httpx.Client)

    def _fake_get(*args: Any, params: dict[str, Any] | None = None, **kwargs: Any) -> MagicMock:
        both_in_flight.wait()
        is_nairobi = params is not None and float(params.get("latitude", 0)) < 0
        return _mock_response(
            _live_payload(
                us_aqi=42 if is_nairobi else 78,
                tz="Africa/Nairobi" if is_nairobi else "Africa/Lagos",
            )
        )

    http_client.get.side_effect = _fake_get
    results: dict[str, Any] = {}
    errors: list[BaseException] = []

    def _worker(city_id: str) -> None:
        try:
            results[city_id] = fetch_open_meteo_air_quality(city_id, http_client=http_client)
        except BaseException as exc:
            errors.append(exc)

    t1 = threading.Thread(target=_worker, args=("lagos-ng",))
    t2 = threading.Thread(target=_worker, args=("nairobi-ke",))
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert not t1.is_alive() and not t2.is_alive()
    assert not errors
    assert results["lagos-ng"].aqi.value == 78
    assert results["nairobi-ke"].aqi.value == 42
    assert http_client.get.call_count == 2


def test_ttl_expiry_triggers_expected_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr("app.core.ttl_cache.time.monotonic", lambda: clock["now"])

    http_client = MagicMock(spec=httpx.Client)
    http_client.get.side_effect = [
        _mock_response(_live_payload(us_aqi=70)),
        _mock_response(_live_payload(us_aqi=95)),
    ]

    r1 = fetch_open_meteo_air_quality("lagos-ng", http_client=http_client)
    assert r1.aqi.value == 70
    assert r1.provenance.cache_hit is False

    # Still within 300s TTL
    clock["now"] = 1200.0
    r2 = fetch_open_meteo_air_quality("lagos-ng", http_client=http_client)
    assert r2.aqi.value == 70
    assert r2.provenance.cache_hit is True
    assert http_client.get.call_count == 1

    # Advance past 300s TTL -> must refresh
    clock["now"] = 1301.0
    r3 = fetch_open_meteo_air_quality("lagos-ng", http_client=http_client)
    assert r3.aqi.value == 95
    assert r3.provenance.cache_hit is False
    assert http_client.get.call_count == 2


def test_force_refresh_bypasses_warm_cache_and_updates_subsequent_reads(
    tmp_path: Path,
) -> None:
    store = SQLiteHistoryStore(tmp_path / "hist_force.db")
    fixed_now = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)
    http_client = MagicMock(spec=httpx.Client)
    http_client.get.side_effect = [
        _mock_response(_history_payload(us_aqi=60)),
        _mock_response(_history_payload(us_aqi=88)),
    ]

    r1 = fetch_historical_air_quality(
        "lagos-ng", days=7, store=store, http_client=http_client, now_utc=fixed_now
    )
    assert r1.period_summary.avg_us_aqi == 61
    assert r1.origin.cache_hit is False

    r2 = fetch_historical_air_quality(
        "lagos-ng",
        days=7,
        force_refresh=True,
        store=store,
        http_client=http_client,
        now_utc=fixed_now,
    )
    assert r2.period_summary.avg_us_aqi == 89
    assert r2.origin.storage_origin == "fresh_provider_retrieval"
    assert http_client.get.call_count == 2

    r3 = fetch_historical_air_quality(
        "lagos-ng", days=7, store=store, http_client=http_client, now_utc=fixed_now
    )
    assert r3.period_summary.avg_us_aqi == 89
    assert r3.origin.storage_origin == "historical_cache"
    assert r3.origin.cache_hit is True
    assert http_client.get.call_count == 2


def test_normal_cold_request_vs_concurrent_force_refresh_updates_cache_cleanly(
    tmp_path: Path,
) -> None:
    """Deterministic test:
    1. Normal cold request acquires key_lock and pauses inside upstream fetch #1.
    2. Concurrent force_refresh=True request for same key starts and waits on key_lock.
    3. Normal request finishes first (AQI 60).
    4. Forced refresh runs afterward (AQI 92) and updates cache.
    5. Subsequent normal request receives refreshed value (AQI 92) from cache.
    """
    store = SQLiteHistoryStore(tmp_path / "hist_normal_vs_force.db")
    fixed_now = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)

    normal_in_fetch = threading.Event()
    release_normal = threading.Event()
    call_order: list[int] = []
    call_lock = threading.Lock()
    http_client = MagicMock(spec=httpx.Client)

    def _fake_get(*args: Any, **kwargs: Any) -> MagicMock:
        with call_lock:
            call_num = len(call_order) + 1
            call_order.append(call_num)
        if call_num == 1:
            normal_in_fetch.set()
            assert release_normal.wait(timeout=5.0)
            return _mock_response(_history_payload(us_aqi=60))
        return _mock_response(_history_payload(us_aqi=92))

    http_client.get.side_effect = _fake_get

    normal_res: dict[str, Any] = {}
    force_res: dict[str, Any] = {}
    errors: list[BaseException] = []

    def _run_normal() -> None:
        try:
            normal_res["value"] = fetch_historical_air_quality(
                "lagos-ng",
                days=7,
                force_refresh=False,
                store=store,
                http_client=http_client,
                now_utc=fixed_now,
            )
        except BaseException as exc:
            errors.append(exc)

    def _run_force() -> None:
        try:
            force_res["value"] = fetch_historical_air_quality(
                "lagos-ng",
                days=7,
                force_refresh=True,
                store=store,
                http_client=http_client,
                now_utc=fixed_now,
            )
        except BaseException as exc:
            errors.append(exc)

    t_normal = threading.Thread(target=_run_normal)
    t_normal.start()
    assert normal_in_fetch.wait(timeout=5.0)

    # Start concurrent force_refresh=True while normal request holds key_lock
    t_force = threading.Thread(target=_run_force)
    t_force.start()

    # Allow normal request to finish first; force_refresh then acquires key_lock and refreshes
    release_normal.set()
    t_normal.join(timeout=5.0)
    t_force.join(timeout=5.0)

    assert not t_normal.is_alive() and not t_force.is_alive()
    assert not errors
    assert call_order == [1, 2]
    assert normal_res["value"].period_summary.avg_us_aqi == 61
    assert force_res["value"].period_summary.avg_us_aqi == 93

    # Subsequent normal read must receive the refreshed value from cache
    after = fetch_historical_air_quality(
        "lagos-ng",
        days=7,
        force_refresh=False,
        store=store,
        http_client=http_client,
        now_utc=fixed_now,
    )
    assert after.period_summary.avg_us_aqi == 93
    assert after.origin.storage_origin == "historical_cache"
    assert after.origin.cache_hit is True
    assert http_client.get.call_count == 2


def test_upstream_failure_releases_lock_and_allows_waiting_retry() -> None:
    entered_first = threading.Event()
    release_first = threading.Event()
    call_count = {"n": 0}
    call_lock = threading.Lock()
    http_client = MagicMock(spec=httpx.Client)

    def _fake_get(*args: Any, **kwargs: Any) -> MagicMock:
        with call_lock:
            call_count["n"] += 1
            n = call_count["n"]
        if n == 1:
            entered_first.set()
            assert release_first.wait(timeout=5.0)
            raise httpx.ReadTimeout("simulated first failure")
        return _mock_response(_live_payload(us_aqi=74))

    http_client.get.side_effect = _fake_get

    outcomes: dict[str, Any] = {}

    def _first() -> None:
        try:
            outcomes["first"] = fetch_open_meteo_air_quality("lagos-ng", http_client=http_client)
        except Exception as exc:
            outcomes["first_err"] = exc

    def _second() -> None:
        outcomes["second"] = fetch_open_meteo_air_quality("lagos-ng", http_client=http_client)

    t1 = threading.Thread(target=_first)
    t1.start()
    assert entered_first.wait(timeout=5.0)

    t2 = threading.Thread(target=_second)
    t2.start()

    release_first.set()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert not t1.is_alive() and not t2.is_alive()
    assert isinstance(outcomes.get("first_err"), OpenMeteoTimeoutError)
    assert outcomes["second"].aqi.value == 74
    assert outcomes["second"].provenance.cache_hit is False
    assert call_count["n"] == 2


def test_concurrent_cache_clear_while_fetch_in_flight_is_safe() -> None:
    entered_fetch = threading.Event()
    release_fetch = threading.Event()
    http_client = MagicMock(spec=httpx.Client)

    def _fake_get(*args: Any, **kwargs: Any) -> MagicMock:
        entered_fetch.set()
        assert release_fetch.wait(timeout=5.0)
        return _mock_response(_live_payload(us_aqi=77))

    http_client.get.side_effect = _fake_get
    result_holder: dict[str, Any] = {}

    def _worker() -> None:
        result_holder["res"] = fetch_open_meteo_air_quality("lagos-ng", http_client=http_client)

    t = threading.Thread(target=_worker)
    t.start()
    assert entered_fetch.wait(timeout=5.0)

    # Clear cache while request is in-flight — must not raise or replace per-key lock
    clear_open_meteo_cache()
    release_fetch.set()
    t.join(timeout=5.0)

    assert not t.is_alive()
    assert result_holder["res"].aqi.value == 77


def test_cached_objects_are_deep_copied_and_isolated_from_caller_mutation() -> None:
    http_client = MagicMock(spec=httpx.Client)
    http_client.get.return_value = _mock_response(_live_payload(us_aqi=83))

    r1 = fetch_open_meteo_air_quality("lagos-ng", http_client=http_client)
    r1.aqi.value = 999
    r1.provenance.provider_name = "MUTATED"

    r2 = fetch_open_meteo_air_quality("lagos-ng", http_client=http_client)
    assert r2.aqi.value == 83
    assert r2.provenance.provider_name != "MUTATED"
    assert r2.provenance.cache_hit is True
    assert http_client.get.call_count == 1


def test_predictive_intelligence_and_live_endpoint_share_single_flight_cache() -> None:
    app_instance = create_app()
    start_barrier = threading.Barrier(2, timeout=5.0)
    entered_fetch = threading.Event()
    release_fetch = threading.Event()
    fetch_count = {"n": 0}
    fetch_lock = threading.Lock()

    with TestClient(app_instance) as client:
        shared = app_instance.state.http_client
        assert isinstance(shared, httpx.Client)

        def _fake_get(*args: Any, **kwargs: Any) -> MagicMock:
            with fetch_lock:
                fetch_count["n"] += 1
            entered_fetch.set()
            assert release_fetch.wait(timeout=5.0)
            return _mock_response(_live_payload(us_aqi=79))

        shared.get = _fake_get  # type: ignore[method-assign]

        responses: dict[str, Any] = {}
        errors: list[BaseException] = []

        def _call_live() -> None:
            try:
                start_barrier.wait()
                responses["live"] = client.get("/api/v1/air-quality?location_id=lagos-ng")
            except BaseException as exc:
                errors.append(exc)

        def _call_intel() -> None:
            try:
                start_barrier.wait()
                responses["intel"] = client.get(
                    "/api/v1/air-quality/intelligence?location_id=lagos-ng"
                )
            except BaseException as exc:
                errors.append(exc)

        t1 = threading.Thread(target=_call_live)
        t2 = threading.Thread(target=_call_intel)
        t1.start()
        t2.start()

        assert entered_fetch.wait(timeout=5.0)
        release_fetch.set()

        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        assert not t1.is_alive() and not t2.is_alive()
        assert not errors
        assert responses["live"].status_code == 200
        assert responses["intel"].status_code == 200
        assert fetch_count["n"] == 1
