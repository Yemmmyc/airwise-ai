"""Modular local SQLite persistence layer for AIRWISE AI historical model records.

Uses Python standard-library `sqlite3` only (zero external database dependencies).
Stores records under `backend/data/airwise_history.db` (configurable via AIRWISE_HISTORY_DB_PATH).

Design & Integrity Rules:
- Uniqueness key: (location_id, timestamp_utc, model_domain).
- Preserves UTC timestamp, original local timestamp, timezone, all 6 variables (with NULL preserved),
  source, retrieval_time, and classification ('historical_model').
- Safe transactions with context-managed connections and WAL mode when supported.
- Modular and cleanly isolated so it can be replaced or removed without touching routes or schemas.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Iterable

from app.core.logging_config import get_logger
from app.schemas.history import HistoricalHourlyRecord

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
logger = get_logger(__name__)


class HistoryStoreError(Exception):
    """Structured exception raised when SQLite historical persistence fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SQLiteHistoryStore:
    """Lightweight SQLite store for persisted historical atmospheric model records."""

    def __init__(self, db_path: str | Path) -> None:
        raw_path = Path(db_path)
        self.db_path: Path = (
            raw_path if raw_path.is_absolute() else (_BACKEND_ROOT / raw_path)
        )
        self._initialized = False

    def initialize(self) -> None:
        """Create parent directory, tables, and indexes safely if they do not exist."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS historical_air_quality (
                        location_id TEXT NOT NULL,
                        timestamp_utc TEXT NOT NULL,
                        model_domain TEXT NOT NULL,
                        local_time TEXT NOT NULL,
                        timezone TEXT NOT NULL,
                        us_aqi INTEGER,
                        pm2_5 REAL,
                        pm10 REAL,
                        no2 REAL,
                        o3 REAL,
                        so2 REAL,
                        source TEXT NOT NULL,
                        retrieval_time TEXT NOT NULL,
                        classification TEXT NOT NULL DEFAULT 'historical_model',
                        PRIMARY KEY (location_id, timestamp_utc, model_domain)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_hist_aq_loc_ts
                    ON historical_air_quality (location_id, model_domain, timestamp_utc)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_hist_aq_loc_local
                    ON historical_air_quality (location_id, model_domain, local_time)
                    """
                )
                conn.commit()
            self._initialized = True
        except (OSError, sqlite3.Error) as exc:
            logger.error(
                "history_store_init_failed exc_type=%s",
                type(exc).__name__,
            )
            raise HistoryStoreError(
                f"Failed to initialize historical SQLite store: {type(exc).__name__}"
            ) from exc

    def check_health(self) -> bool:
        """Verify local SQLite store reachability without mutating data or leaking connections."""
        try:
            if self.db_path.exists():
                with contextlib.closing(self._connect()) as conn:
                    conn.execute("SELECT 1").fetchone()
                return True

            # Avoid creating directories or an empty DB file during a read-only health check.
            if self.db_path.parent.exists() and not self.db_path.parent.is_dir():
                logger.warning(
                    "history_store_health_check_failed exc_type=NotADirectoryError"
                )
                return False

            with contextlib.closing(sqlite3.connect(":memory:", timeout=5.0)) as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except (OSError, sqlite3.Error) as exc:
            logger.warning(
                "history_store_health_check_failed exc_type=%s",
                type(exc).__name__,
            )
            return False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_initialized(self) -> None:
        if not self._initialized or not self.db_path.exists():
            self.initialize()

    def upsert_records(
        self,
        location_id: str,
        records: Iterable[HistoricalHourlyRecord],
    ) -> int:
        """Insert or update historical hourly records using (location_id, timestamp_utc, model_domain)."""
        self._ensure_initialized()
        rows = [
            (
                location_id,
                rec.timestamp_utc,
                rec.model_domain,
                rec.local_time,
                rec.timezone,
                rec.us_aqi,
                rec.pm2_5,
                rec.pm10,
                rec.no2,
                rec.o3,
                rec.so2,
                rec.source,
                rec.retrieval_time,
                rec.classification,
            )
            for rec in records
        ]
        if not rows:
            return 0

        try:
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO historical_air_quality (
                        location_id,
                        timestamp_utc,
                        model_domain,
                        local_time,
                        timezone,
                        us_aqi,
                        pm2_5,
                        pm10,
                        no2,
                        o3,
                        so2,
                        source,
                        retrieval_time,
                        classification
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(location_id, timestamp_utc, model_domain) DO UPDATE SET
                        local_time = excluded.local_time,
                        timezone = excluded.timezone,
                        us_aqi = excluded.us_aqi,
                        pm2_5 = excluded.pm2_5,
                        pm10 = excluded.pm10,
                        no2 = excluded.no2,
                        o3 = excluded.o3,
                        so2 = excluded.so2,
                        source = excluded.source,
                        retrieval_time = excluded.retrieval_time,
                        classification = excluded.classification
                    """,
                    rows,
                )
                conn.commit()
            return len(rows)
        except sqlite3.Error as exc:
            raise HistoryStoreError(
                f"Failed to upsert historical records into SQLite: {type(exc).__name__}"
            ) from exc

    def get_records(
        self,
        *,
        location_id: str,
        model_domain: str,
        start_utc: str,
        end_utc: str,
    ) -> list[HistoricalHourlyRecord]:
        """Retrieve persisted historical records for a location within [start_utc, end_utc] inclusive."""
        self._ensure_initialized()
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    SELECT
                        timestamp_utc,
                        local_time,
                        timezone,
                        us_aqi,
                        pm2_5,
                        pm10,
                        no2,
                        o3,
                        so2,
                        source,
                        model_domain,
                        retrieval_time,
                        classification
                    FROM historical_air_quality
                    WHERE location_id = ?
                      AND model_domain = ?
                      AND timestamp_utc >= ?
                      AND timestamp_utc <= ?
                    ORDER BY timestamp_utc ASC
                    """,
                    (location_id, model_domain, start_utc, end_utc),
                )
                rows = cursor.fetchall()
        except sqlite3.Error as exc:
            raise HistoryStoreError(
                f"Failed to query historical records from SQLite: {type(exc).__name__}"
            ) from exc

        return [
            HistoricalHourlyRecord(
                classification="historical_model",
                timestamp_utc=row["timestamp_utc"],
                local_time=row["local_time"],
                timezone=row["timezone"],
                us_aqi=row["us_aqi"],
                pm2_5=row["pm2_5"],
                pm10=row["pm10"],
                no2=row["no2"],
                o3=row["o3"],
                so2=row["so2"],
                source=row["source"],
                model_domain=row["model_domain"],
                retrieval_time=row["retrieval_time"],
            )
            for row in rows
        ]

    def get_latest_retrieval_time(
        self,
        *,
        location_id: str,
        model_domain: str,
        start_utc: str,
        end_utc: str,
    ) -> str | None:
        """Return the most recent retrieval_time ISO string among matching persisted records."""
        self._ensure_initialized()
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT MAX(retrieval_time) AS latest_retrieval
                    FROM historical_air_quality
                    WHERE location_id = ?
                      AND model_domain = ?
                      AND timestamp_utc >= ?
                      AND timestamp_utc <= ?
                    """,
                    (location_id, model_domain, start_utc, end_utc),
                ).fetchone()
                if row is None:
                    return None
                return row["latest_retrieval"]
        except sqlite3.Error as exc:
            raise HistoryStoreError(
                f"Failed to inspect persisted retrieval metadata: {type(exc).__name__}"
            ) from exc
