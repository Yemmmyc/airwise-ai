"""Automated pytest suite for Phase 9.1A Observability & Runtime Truth.

Covers:
- Request correlation ID generation, validation, safe rejection of malformed headers,
  response header propagation, and contextvars reset across concurrent/failing requests.
- Structured backend logging & defense-in-depth secret redaction.
- Accurate runtime health reporting (healthy, degraded SQLite, assistant_configured boolean).
- Diagnostic logging on upstream timeout, history fallback, and assistant unavailable paths.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging_config import (
    REQUEST_ID_HEADER,
    get_logger,
    get_request_id,
    is_valid_request_id,
    redact_secrets,
    resolve_request_id,
    reset_request_id,
    set_request_id,
)
from app.main import app, create_app
from app.services.history_store import HistoryStoreError, SQLiteHistoryStore
from app.services.open_meteo import clear_open_meteo_cache
from app.services.open_meteo_history import (
    clear_history_cache,
    fetch_historical_air_quality,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    clear_open_meteo_cache()
    yield
    clear_open_meteo_cache()


# ============================================================================
# 1. Request Correlation ID Tests
# ============================================================================


def test_request_id_generated_when_header_missing() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    req_id = response.headers.get(REQUEST_ID_HEADER)
    assert req_id is not None
    assert is_valid_request_id(req_id)
    assert get_request_id() == "-"


def test_valid_incoming_request_id_is_propagated() -> None:
    supplied = "req-airwise_2026.01"
    response = client.get("/api/v1/health", headers={REQUEST_ID_HEADER: supplied})
    assert response.status_code == 200
    assert response.headers.get(REQUEST_ID_HEADER) == supplied
    assert get_request_id() == "-"


@pytest.mark.parametrize(
    "bad_header",
    [
        "abc",  # too short (< 4)
        "x" * 65,  # too long (> 64)
        "bad id with spaces",
        "bad\r\ninjected-log-line",
        "req;DROP TABLE users",
        "<script>alert(1)</script>",
    ],
)
def test_malformed_request_id_is_rejected_and_replaced(bad_header: str) -> None:
    resolved = resolve_request_id(bad_header)
    assert resolved != bad_header
    assert is_valid_request_id(resolved)

    # Verify HTTP middleware also replaces unsafe header values safely (non-CRLF headers)
    if "\r" not in bad_header and "\n" not in bad_header:
        response = client.get("/api/v1/health", headers={REQUEST_ID_HEADER: bad_header})
        assert response.status_code == 200
        returned = response.headers.get(REQUEST_ID_HEADER)
        assert returned != bad_header
        assert is_valid_request_id(returned)


def test_concurrent_requests_do_not_leak_correlation_ids() -> None:
    ids = [f"concurrent-req-{i:03d}" for i in range(12)]

    def _call(rid: str) -> tuple[str, str | None]:
        resp = client.get("/api/v1/health", headers={REQUEST_ID_HEADER: rid})
        return rid, resp.headers.get(REQUEST_ID_HEADER)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_call, ids))

    for expected, actual in results:
        assert actual == expected
    assert get_request_id() == "-"


def test_request_id_context_resets_and_returns_header_on_unhandled_500() -> None:
    test_app = create_app()

    @test_app.get("/_test_boom")
    def _boom() -> None:
        raise RuntimeError("simulated boom")

    local_client = TestClient(test_app, raise_server_exceptions=False)
    req_id = "boom-req-1234"
    resp = local_client.get("/_test_boom", headers={REQUEST_ID_HEADER: req_id})
    assert resp.status_code == 500
    assert resp.headers.get(REQUEST_ID_HEADER) == req_id
    assert resp.json() == {"detail": "Internal Server Error"}
    assert get_request_id() == "-"


# ============================================================================
# 2. Structured Logging & Secret Redaction Tests
# ============================================================================


def test_secret_redaction_strips_sensitive_patterns() -> None:
    sample = (
        "Failed with key AIzaSyD1234567890abcdefghijkLMNOPQRST "
        "and Authorization: Bearer supersecrettoken12345 "
        "api_key=my_secret_value"
    )
    redacted = redact_secrets(sample)
    assert "AIzaSyD1234567890" not in redacted
    assert "supersecrettoken12345" not in redacted
    assert "my_secret_value" not in redacted
    assert "[REDACTED_GOOGLE_KEY]" in redacted
    assert "[REDACTED]" in redacted


def test_diagnostic_logging_emits_correlation_id_on_open_meteo_timeout(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _TimeoutClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *args, **kwargs):
            raise httpx.ReadTimeout("simulated timeout")

    monkeypatch.setattr("app.services.open_meteo.httpx.Client", _TimeoutClient)

    req_id = "timeout-trace-9901"
    with caplog.at_level(logging.INFO, logger="airwise"):
        resp = client.get(
            "/api/v1/air-quality?location_id=lagos-ng",
            headers={REQUEST_ID_HEADER: req_id},
        )

    assert resp.status_code == 504
    assert resp.headers.get(REQUEST_ID_HEADER) == req_id
    timeout_records = [
        r for r in caplog.records if "open_meteo_timeout" in r.getMessage()
    ]
    assert len(timeout_records) == 1
    assert getattr(timeout_records[0], "request_id", None) == req_id


def test_assistant_unavailable_log_never_leaks_user_prompt_or_keys(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "app.services.gemini_assistant.get_settings",
        lambda: Settings(gemini_api_key=None),
    )

    secret_phrase = "MY_PRIVATE_MEDICAL_CONVERSATION_TEXT"
    req_id = "assistant-trace-4411"
    with caplog.at_level(logging.INFO, logger="airwise"):
        resp = client.post(
            "/api/v1/assistant/ask",
            headers={REQUEST_ID_HEADER: req_id},
            json={
                "location_id": "lagos-ng",
                "mode": "ask",
                "question": secret_phrase,
            },
        )

    assert resp.status_code == 503
    assert resp.headers.get(REQUEST_ID_HEADER) == req_id
    all_messages = "\n".join(r.getMessage() for r in caplog.records)
    assert "gemini_assistant_unavailable" in all_messages
    assert secret_phrase not in all_messages


# ============================================================================
# 3. Accurate Runtime Health Reporting Tests
# ============================================================================


def test_health_reports_degraded_when_history_store_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "app.services.history_store.SQLiteHistoryStore.check_health",
        MagicMock(return_value=False),
    )

    with caplog.at_level(logging.WARNING, logger="airwise"):
        resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "degraded"
    assert payload["history_store_status"] == "unavailable"
    assert any("health_check_degraded" in r.getMessage() for r in caplog.records)


def test_health_reports_assistant_configured_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_secret = "AIzaSyFakeTestKey999999999999999999"
    monkeypatch.setattr(
        "app.api.v1.routes.get_settings",
        lambda: Settings(gemini_api_key=fake_secret),
    )

    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["assistant_configured"] is True
    assert fake_secret not in resp.text


def test_health_distinguishes_configured_provider_from_unverified_connectivity_and_makes_no_network_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbid_network(*args, **kwargs):
        raise AssertionError("GET /api/v1/health must not make outbound HTTP requests")

    monkeypatch.setattr("app.services.open_meteo.httpx.Client", _forbid_network)
    monkeypatch.setattr("app.services.open_meteo_history.httpx.Client", _forbid_network)

    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["provider_configured"] is True
    assert payload["live_provider_connected"] is False
    assert payload["data_mode"] == "live_model"


def test_health_reports_demo_mode_when_provider_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.v1.routes.get_settings",
        lambda: Settings(open_meteo_base_url=""),
    )

    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["provider_configured"] is False
    assert payload["live_provider_connected"] is False
    assert payload["data_mode"] == "demo"


def test_sqlite_check_health_closes_connection_and_avoids_creating_missing_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Missing DB file should NOT be created on disk by a health probe
    missing_db = tmp_path / "nonexistent_dir" / "history.db"
    store_missing = SQLiteHistoryStore(missing_db)
    assert store_missing.check_health() is True
    assert not missing_db.exists()
    assert not missing_db.parent.exists()

    # 2. Existing DB file opens via _connect() and deterministically closes connection
    existing_db = tmp_path / "existing.db"
    store_existing = SQLiteHistoryStore(existing_db)
    store_existing.initialize()

    real_connect = store_existing._connect
    closed_flag = {"closed": False}

    class _TrackedConn:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, *args, **kwargs):
            return self._inner.execute(*args, **kwargs)

        def close(self) -> None:
            closed_flag["closed"] = True
            self._inner.close()

    monkeypatch.setattr(
        store_existing, "_connect", lambda: _TrackedConn(real_connect())
    )
    assert store_existing.check_health() is True
    assert closed_flag["closed"] is True


def test_child_logger_redacts_secrets_in_message_and_exception_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    child_logger = get_logger("services.test_child_redaction")
    secret_key = "AIzaSyChildLoggerSecretKey1234567890"
    secret_token = "Bearer TopSecretChildToken98765"

    token = set_request_id("child-log-req-77")
    try:
        with caplog.at_level(logging.ERROR, logger="airwise"):
            try:
                raise RuntimeError(f"Upstream auth failed for {secret_key}")
            except RuntimeError:
                child_logger.error(
                    "child_error_event auth=%s",
                    secret_token,
                    exc_info=True,
                )
    finally:
        reset_request_id(token)

    matching = [
        r for r in caplog.records if r.name == "airwise.services.test_child_redaction"
    ]
    assert len(matching) == 1
    rec = matching[0]
    assert getattr(rec, "request_id", None) == "child-log-req-77"
    assert secret_token not in rec.getMessage()
    assert "[REDACTED]" in rec.getMessage()
    assert rec.exc_info is None
    assert rec.exc_text is not None
    assert "RuntimeError" in rec.exc_text
    assert secret_key not in rec.exc_text
    assert "[REDACTED_GOOGLE_KEY]" in rec.exc_text


def test_history_sqlite_read_failure_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    clear_history_cache()

    class _FailingReadStore:
        def get_records(self, *args, **kwargs):
            raise HistoryStoreError("simulated sqlite read failure")

        def get_latest_retrieval_time(self, *args, **kwargs):
            return None

    class _TimeoutClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *args, **kwargs):
            raise httpx.ReadTimeout("simulated history timeout")

    monkeypatch.setattr("app.services.open_meteo_history.httpx.Client", _TimeoutClient)

    with caplog.at_level(logging.WARNING, logger="airwise"):
        with pytest.raises(Exception):
            fetch_historical_air_quality(
                location_id="lagos-ng",
                days=7,
                store=_FailingReadStore(),  # type: ignore[arg-type]
            )

    messages = "\n".join(r.getMessage() for r in caplog.records)
    assert "history_sqlite_read_failed" in messages
    assert "history_upstream_timeout" in messages
    clear_history_cache()
