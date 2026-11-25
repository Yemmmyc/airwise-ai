"""Deterministic SQLite reliability, WAL, busy_timeout, and lifecycle tests (Phase 9.1C).

Uses temporary databases (`tmp_path`) and deterministic synchronization (`threading.Barrier`).
Avoids sleep-based assertions and joins all worker threads cleanly.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from app.schemas.history import HistoricalHourlyRecord
from app.services.history_store import (
    DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    HistoryStoreError,
    SQLiteHistoryStore,
)


def _make_record(
    *,
    hour: int = 0,
    us_aqi: int = 72,
    retrieval_time: str = "2026-11-25T08:00:00Z",
) -> HistoricalHourlyRecord:
    hh = f"{hour:02d}"
    return HistoricalHourlyRecord(
        classification="historical_model",
        timestamp_utc=f"2026-11-20T{hh}:00:00Z",
        local_time=f"2026-11-20T{hh}:00",
        timezone="Africa/Lagos",
        us_aqi=us_aqi,
        pm2_5=21.5,
        pm10=44.0,
        no2=15.0,
        o3=48.0,
        so2=5.2,
        source="Open-Meteo CAMS Global",
        model_domain="cams_global",
        retrieval_time=retrieval_time,
    )


def test_wal_activation_and_persistence_after_reopening(tmp_path: Path) -> None:
    db_file = tmp_path / "wal_test.db"
    store1 = SQLiteHistoryStore(db_file)
    store1.initialize()

    # Reopen via a brand-new SQLiteHistoryStore instance and inspect PRAGMA journal_mode
    store2 = SQLiteHistoryStore(db_file)
    with store2._open_connection() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"


def test_busy_timeout_equals_5000_ms(tmp_path: Path) -> None:
    db_file = tmp_path / "busy_timeout.db"
    store = SQLiteHistoryStore(db_file)
    store.initialize()

    with store._open_connection() as conn:
        timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert int(timeout_ms) == DEFAULT_SQLITE_BUSY_TIMEOUT_MS == 5000


def test_connection_closure_after_successful_init_write_and_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_file = tmp_path / "close_success.db"
    store = SQLiteHistoryStore(db_file)
    real_connect = store._connect
    tracker = {"opened": 0, "closed": 0}

    class _TrackedConn:
        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner

        def execute(self, *args: Any, **kwargs: Any) -> Any:
            return self._inner.execute(*args, **kwargs)

        def executemany(self, *args: Any, **kwargs: Any) -> Any:
            return self._inner.executemany(*args, **kwargs)

        def commit(self) -> None:
            self._inner.commit()

        def rollback(self) -> None:
            self._inner.rollback()

        def close(self) -> None:
            tracker["closed"] += 1
            self._inner.close()

    def _wrapped_connect() -> Any:
        tracker["opened"] += 1
        return _TrackedConn(real_connect())

    monkeypatch.setattr(store, "_connect", _wrapped_connect)

    store.initialize()
    assert store.upsert_records("lagos-ng", [_make_record(hour=1)]) == 1
    rows = store.get_records(
        location_id="lagos-ng",
        model_domain="cams_global",
        start_utc="2026-11-20T00:00:00Z",
        end_utc="2026-11-20T23:00:00Z",
    )
    assert len(rows) == 1
    latest = store.get_latest_retrieval_time(
        location_id="lagos-ng",
        model_domain="cams_global",
        start_utc="2026-11-20T00:00:00Z",
        end_utc="2026-11-20T23:00:00Z",
    )
    assert latest == "2026-11-25T08:00:00Z"
    assert store.check_health() is True

    assert tracker["opened"] == 5
    assert tracker["closed"] == 5


def test_connection_closure_after_query_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_file = tmp_path / "close_exc.db"
    store = SQLiteHistoryStore(db_file)
    store.initialize()

    closed = {"flag": False}

    class _FailingConn:
        def execute(self, *args: Any, **kwargs: Any) -> Any:
            raise sqlite3.OperationalError("simulated read error")

        def close(self) -> None:
            closed["flag"] = True

    monkeypatch.setattr(store, "_connect", lambda: _FailingConn())

    with pytest.raises(HistoryStoreError):
        store.get_records(
            location_id="lagos-ng",
            model_domain="cams_global",
            start_utc="2026-11-20T00:00:00Z",
            end_utc="2026-11-20T23:00:00Z",
        )
    assert closed["flag"] is True


def test_connection_closure_when_transaction_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_file = tmp_path / "commit_fail.db"
    store = SQLiteHistoryStore(db_file)
    store.initialize()

    real_connect = store._connect
    events = {"rolled_back": False, "closed": False}

    class _CommitFailConn:
        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner

        def executemany(self, *args: Any, **kwargs: Any) -> Any:
            return self._inner.executemany(*args, **kwargs)

        def commit(self) -> None:
            raise sqlite3.OperationalError("simulated commit failure")

        def rollback(self) -> None:
            events["rolled_back"] = True
            self._inner.rollback()

        def close(self) -> None:
            events["closed"] = True
            self._inner.close()

    monkeypatch.setattr(store, "_connect", lambda: _CommitFailConn(real_connect()))

    with pytest.raises(HistoryStoreError):
        store.upsert_records("lagos-ng", [_make_record(hour=2)])

    assert events["rolled_back"] is True
    assert events["closed"] is True


def test_transaction_rollback_leaves_no_partial_writes_on_failed_upsert(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "rollback.db"
    store = SQLiteHistoryStore(db_file)
    store.initialize()

    # Add a trigger that fails on the 2nd row (us_aqi == 499) inside a single executemany batch
    with store._transaction() as conn:
        conn.execute(
            """
            CREATE TRIGGER abort_bad_aqi
            BEFORE INSERT ON historical_air_quality
            WHEN NEW.us_aqi = 499
            BEGIN
                SELECT RAISE(ABORT, 'simulated mid-batch failure');
            END;
            """
        )

    batch = [_make_record(hour=0, us_aqi=70), _make_record(hour=1, us_aqi=499)]
    with pytest.raises(HistoryStoreError):
        store.upsert_records("lagos-ng", batch)

    # First row must NOT have been partially committed
    rows = store.get_records(
        location_id="lagos-ng",
        model_domain="cams_global",
        start_utc="2026-11-20T00:00:00Z",
        end_utc="2026-11-20T23:00:00Z",
    )
    assert rows == []


def test_concurrent_reads_and_writes_across_four_cities(tmp_path: Path) -> None:
    db_file = tmp_path / "concurrent_rw.db"
    store = SQLiteHistoryStore(db_file)
    store.initialize()

    cities = ["lagos-ng", "abuja-ng", "nairobi-ke", "accra-gh"]
    barrier = threading.Barrier(len(cities) + 2, timeout=5.0)
    errors: list[BaseException] = []

    def _writer(city_id: str, base_aqi: int) -> None:
        try:
            barrier.wait()
            recs = [_make_record(hour=h, us_aqi=base_aqi + h) for h in range(6)]
            assert store.upsert_records(city_id, recs) == 6
        except BaseException as exc:
            errors.append(exc)

    def _reader() -> None:
        try:
            barrier.wait()
            for city_id in cities:
                store.get_records(
                    location_id=city_id,
                    model_domain="cams_global",
                    start_utc="2026-11-20T00:00:00Z",
                    end_utc="2026-11-20T23:00:00Z",
                )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=_writer, args=(city, 50 + idx * 10))
        for idx, city in enumerate(cities)
    ] + [threading.Thread(target=_reader), threading.Thread(target=_reader)]

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive()

    assert not errors
    for city in cities:
        rows = store.get_records(
            location_id=city,
            model_domain="cams_global",
            start_utc="2026-11-20T00:00:00Z",
            end_utc="2026-11-20T23:00:00Z",
        )
        assert len(rows) == 6


def test_concurrent_upserts_of_identical_records_produce_no_duplicates(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "concurrent_upsert_same.db"
    store = SQLiteHistoryStore(db_file)
    store.initialize()

    workers = 4
    barrier = threading.Barrier(workers, timeout=5.0)
    errors: list[BaseException] = []

    def _worker(idx: int) -> None:
        try:
            barrier.wait()
            recs = [_make_record(hour=h, us_aqi=70 + idx) for h in range(4)]
            assert store.upsert_records("lagos-ng", recs) == 4
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive()

    assert not errors
    rows = store.get_records(
        location_id="lagos-ng",
        model_domain="cams_global",
        start_utc="2026-11-20T00:00:00Z",
        end_utc="2026-11-20T23:00:00Z",
    )
    assert len(rows) == 4


def test_health_check_succeeds_during_active_write_transaction(tmp_path: Path) -> None:
    db_file = tmp_path / "health_during_write.db"
    store = SQLiteHistoryStore(db_file)
    store.initialize()

    write_started = threading.Event()
    release_write = threading.Event()
    errors: list[BaseException] = []

    def _active_writer() -> None:
        try:
            with store._transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO historical_air_quality (
                        location_id, timestamp_utc, model_domain, local_time, timezone,
                        us_aqi, pm2_5, pm10, no2, o3, so2, source, retrieval_time, classification
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "lagos-ng",
                        "2026-11-20T05:00:00Z",
                        "cams_global",
                        "2026-11-20T05:00",
                        "Africa/Lagos",
                        77,
                        20.0,
                        40.0,
                        12.0,
                        45.0,
                        5.0,
                        "Open-Meteo CAMS Global",
                        "2026-11-25T08:00:00Z",
                        "historical_model",
                    ),
                )
                write_started.set()
                assert release_write.wait(timeout=5.0)
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=_active_writer)
    t.start()
    assert write_started.wait(timeout=5.0)

    # Under WAL mode, check_health() must succeed immediately while writer holds write tx
    assert store.check_health() is True

    release_write.set()
    t.join(timeout=5.0)
    assert not t.is_alive()
    assert not errors


def test_database_reopen_preserves_persisted_records(tmp_path: Path) -> None:
    db_file = tmp_path / "reopen.db"
    store1 = SQLiteHistoryStore(db_file)
    store1.upsert_records("lagos-ng", [_make_record(hour=3, us_aqi=84)])

    # Brand-new store instance simulates process restart
    store2 = SQLiteHistoryStore(db_file)
    rows = store2.get_records(
        location_id="lagos-ng",
        model_domain="cams_global",
        start_utc="2026-11-20T00:00:00Z",
        end_utc="2026-11-20T23:00:00Z",
    )
    assert len(rows) == 1
    assert rows[0].us_aqi == 84


def test_concurrent_initialization_of_same_database_path(tmp_path: Path) -> None:
    db_file = tmp_path / "concurrent_init.db"
    workers = 6
    barrier = threading.Barrier(workers, timeout=5.0)
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            store = SQLiteHistoryStore(db_file)
            barrier.wait()
            store.initialize()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive()

    assert not errors
    assert db_file.exists()


def test_reinitialization_after_database_file_deletion(tmp_path: Path) -> None:
    db_file = tmp_path / "deleted_reinit.db"
    store = SQLiteHistoryStore(db_file)
    store.upsert_records("lagos-ng", [_make_record(hour=0, us_aqi=65)])
    assert db_file.exists()

    # Remove DB file (and any sidecar WAL/SHM files if present)
    for suffix in ("", "-wal", "-shm"):
        p = Path(f"{db_file}{suffix}")
        if p.exists():
            p.unlink()
    assert not db_file.exists()

    # Next operation must cleanly recreate DB & schema and persist new record
    assert store.upsert_records("lagos-ng", [_make_record(hour=1, us_aqi=88)]) == 1
    rows = store.get_records(
        location_id="lagos-ng",
        model_domain="cams_global",
        start_utc="2026-11-20T00:00:00Z",
        end_utc="2026-11-20T23:00:00Z",
    )
    assert len(rows) == 1
    assert rows[0].us_aqi == 88


def test_wal_activation_failure_logs_warning_and_falls_back_safely(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db_file = tmp_path / "wal_fallback.db"
    store = SQLiteHistoryStore(db_file)

    class _NonWalConn:
        def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
            class _Row:
                def fetchone(self) -> tuple[str]:
                    return ("delete",)

            return _Row()

    with caplog.at_level(logging.WARNING, logger="airwise"):
        activated = store._enable_wal_mode(_NonWalConn())  # type: ignore[arg-type]

    assert activated is False
    assert any(
        "history_store_wal_unexpected_mode" in r.getMessage() for r in caplog.records
    )

    class _ErrorWalConn:
        def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
            raise sqlite3.OperationalError("wal unsupported")

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="airwise"):
        activated_err = store._enable_wal_mode(_ErrorWalConn())  # type: ignore[arg-type]

    assert activated_err is False
    assert any(
        "history_store_wal_activation_failed" in r.getMessage() for r in caplog.records
    )


def test_no_unnecessary_repeated_ddl_during_normal_historical_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_file = tmp_path / "no_repeat_ddl.db"
    first_store = SQLiteHistoryStore(db_file)
    first_store.upsert_records("lagos-ng", [_make_record(hour=4, us_aqi=71)])

    # Simulate fresh per-request SQLiteHistoryStore instances; initialize() must NOT re-run
    init_calls = {"count": 0}
    orig_init = SQLiteHistoryStore.initialize

    def _spy_init(self: SQLiteHistoryStore) -> None:
        init_calls["count"] += 1
        orig_init(self)

    monkeypatch.setattr(SQLiteHistoryStore, "initialize", _spy_init)

    for _ in range(3):
        req_store = SQLiteHistoryStore(db_file)
        rows = req_store.get_records(
            location_id="lagos-ng",
            model_domain="cams_global",
            start_utc="2026-11-20T00:00:00Z",
            end_utc="2026-11-20T23:00:00Z",
        )
        assert len(rows) == 1

    assert init_calls["count"] == 0
