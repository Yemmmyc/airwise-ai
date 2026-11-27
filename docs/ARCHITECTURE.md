# AIRWISE AI — System Architecture & Reliability Overview

**Project:** AIRWISE AI (Hack2Skill PromptWars Challenge 6: Urban Air Quality Assistant)  
**Deployment Model:** Local-first on Windows 11 (PowerShell) — not publicly deployed  
**Backend Version:** `0.9.1`

---

## 1. High-Level Architecture

AIRWISE AI enforces a strict separation between the browser UI and the backend intelligence service:

- **Frontend (`frontend/`):** Next.js 16 (App Router), React 18, TypeScript, Tailwind CSS, and Leaflet (`leaflet`), running locally on `http://localhost:3000`.
  - Communicates **only** with the local FastAPI backend (`NEXT_PUBLIC_API_BASE_URL`, default `http://127.0.0.1:8000`).
  - Never calls Open-Meteo or Google Gemini directly and never holds API keys.
  - Displays live model conditions, a 4-city Leaflet map (keyless OpenStreetMap standard raster tiles `https://tile.openstreetmap.org/{z}/{x}/{y}.png` with `© OpenStreetMap contributors` attribution, restrained dark CSS tile-pane styling, subject to OSMF public tile usage policy with no SLA; no API key or browser geolocation API), 7/14/30-day SVG historical trend charts, deterministic predictive intelligence cards, a grounded Gemini assistant panel, and an explicit Demo Mode toggle.
- **Backend (`backend/`):** Python 3.12, FastAPI, Pydantic v2, `pydantic-settings`, `httpx`, `google-genai`, and standard-library `sqlite3`, running locally on `http://127.0.0.1:8000`.
  - Canonical supported cities: `lagos-ng` (Lagos, Nigeria), `abuja-ng` (Abuja, Nigeria), `nairobi-ke` (Nairobi, Kenya), and `accra-gh` (Accra, Ghana).

---

## 2. Core Data & Intelligence Services

### A. Open-Meteo CAMS Global Live & Forecast (`app/services/open_meteo.py`)
- Queries the official Open-Meteo Air Quality API (`cams_global`, ~0.4° / ~45 km grid, 3-hourly native output interpolated to 1-hourly API timestamps) with an 8.0s per-request timeout.
- Classifies timestamps strictly in the city's IANA timezone into `current_model` and strictly future `hourly_forecast` (`> observation_time`).
- Reports `us_aqi` directly from Open-Meteo without synthetic recalculation, preserves `null` measurements without zero-filling, and never substitutes demo data on failure.

### B. Historical Air Quality & 4-City Comparison (`app/services/open_meteo_history.py`)
- Retrieves genuine historical Open-Meteo model records (`past_days=7|14|30`, `forecast_days=0`) with a 12.0s per-request timeout, excluding any timestamp `>= current UTC`.
- Computes local-calendar-day summaries and period completeness statistics without fabricating missing values.
- `fetch_historical_city_comparison()` fans out across all 4 cities using a bounded `ThreadPoolExecutor(max_workers=4)` with per-city fault isolation so a failure in one city returns `status="unavailable"` for that city only. Each worker task receives a fresh `contextvars.copy_context()` so `X-Request-ID` propagates cleanly into worker-thread logs.

### C. Deterministic Predictive Intelligence (`app/services/predictive_intelligence.py`)
- Rule-based analytical engine (zero ML training, zero LLM calls) built on verified Open-Meteo 24-hour forecasts.
- Produces Peak Forecast Risk, elevated-risk windows (`>= 2` contiguous hours at US AQI `>= 101`), isolated single-hour spikes, comparatively favorable windows, independent activity guidance (`outdoor_exercise`, `outdoor_errands`, `general_outdoor`), per-metric provisional OLS trend signals, and qualitative data-quality tiers.

### D. Grounded Gemini Assistant (`app/services/gemini_assistant.py`)
- Backend-only Gemini Developer API integration using the official `google-genai` SDK (`gemini-3.5-flash-lite` default, configurable via `AIRWISE_GEMINI_MODEL`, 15.0s timeout), keeping `GEMINI_API_KEY` strictly on the server.
- Grounds every answer in verified Open-Meteo payloads retrieved through `fetch_open_meteo_air_quality()` (reusing the shared HTTP client and live single-flight cache).
- Enforces the five-section structured JSON contract (`verified_data_summary`, `forecast_context`, `ai_interpretation`, `general_health_guidance`, `model_limitations_notice`) separating verified data, forecast context, AI interpretation, non-medical general health guidance, and model limitations. Returns `HTTP 503 assistant_unavailable` whenever `GEMINI_API_KEY` is unset.

---

## 3. Phase 9.1 Reliability & Runtime Engineering

### A. FastAPI Lifespan & Shared HTTP Connection Pool (`app/main.py`)
- `_app_lifespan` initializes one application-scoped synchronous `httpx.Client` stored on `app.state.http_client` with explicit pool bounds:
  - `max_connections=20`
  - `max_keepalive_connections=10`
  - `keepalive_expiry=30.0` seconds
- All outbound-HTTP routes inject `app.state.http_client` into downstream services without allowing services to close the shared client.
- On shutdown, `_app_lifespan` deterministically closes `shared_client` in a `finally` block and resets `app.state.http_client = None`. Legacy callers without lifespan fall back safely to per-call `httpx.Client` instances.

### B. Thread-Safe Single-Flight TTL Caching (`app/core/ttl_cache.py`)
- `SingleFlightTTLCache` protects both the live cache (`location_id`, 300s TTL, max 4 keys) and the historical cache (`(location_id, range_days)`, 1200s TTL, max 12 keys).
- Uses a short-lived metadata `threading.Lock` (never held across network or SQLite I/O) and persistent per-key locks with double-checked reads so concurrent misses for the same key collapse into a single upstream request.
- Uses `time.monotonic()` for TTL expiration, `model_copy(deep=True)` for cross-caller immutability, never caches errors, and never caches `persisted_database_fallback` responses.

### C. SQLite Persistence Lifecycle & Concurrency (`app/services/history_store.py`)
- Stores historical hourly records in `backend/data/airwise_history.db` (Git-ignored) keyed by `(location_id, timestamp_utc, model_domain)` with idempotent `ON CONFLICT` upserts.
- `_open_connection()` guarantees deterministic `conn.close()` in `finally` (even if rollback fails); `_transaction()` wraps writes in explicit commit/rollback boundaries with zero cross-thread connection sharing.
- Every connection sets `PRAGMA busy_timeout = 5000`; `initialize()` enables `PRAGMA journal_mode = WAL` (with safe fallback when WAL is unsupported) and uses a bounded 16-stripe `_INIT_STRIPES` lock + `_INITIALIZED_DB_PATHS` registry that avoids repeated DDL and transparently re-initializes if the DB file is removed.

### D. Observability, Secret Redaction & Baseline Security Headers (`app/core/logging_config.py`, `app/main.py`)
- **Request Correlation:** HTTP middleware validates incoming `X-Request-ID` (`^[A-Za-z0-9._-]{4,64}$`) or generates a UUID fallback, binds it to a `contextvars.ContextVar`, resets it in `finally`, and returns `X-Request-ID` on normal, `4xx`, `5xx`, and unhandled `500` JSON responses (exposed via CORS `expose_headers`).
- **Secret Redaction:** `RequestIdFilter` and `SecretRedactingFilter` are attached to both child loggers (`get_logger()`) and the `StreamHandler` (`SecretRedactingFormatter`), redacting Google API keys, Bearer tokens, and key/token/password/secret assignments in both log messages and formatted tracebacks.
- **Baseline Security Headers:** Every backend response (including unhandled `500` responses) includes `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `X-Frame-Options: DENY`. CORS defaults to `http://localhost:3000,http://127.0.0.1:3000` with `allow_credentials=False` and `GET, POST, OPTIONS`.

---

## 4. Truthful Health Reporting & Data Provenance

### `GET /api/v1/health` (`app/api/v1/routes.py`)
- Intentionally lightweight: makes **zero outbound network requests** and probes SQLite non-destructively via `SQLiteHistoryStore.check_health()` (without creating a missing DB file).
- Reports `status` (`"ok"` or `"degraded"` when SQLite is unavailable), `data_mode`, `provider_configured`, `live_provider_connected` (`false` on lightweight probes), `history_store_status`, `assistant_configured` (boolean only; never exposes secrets), and `supported_locations_count`.

### Data Provenance & Fallback Semantics
- Every response carries explicit provenance labels (`LIVE PROVIDER DATA — MODEL-BASED ESTIMATE`, `HOURLY FORECAST`, `HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE`, `ANALYTICAL INTERPRETATION — BASED ON OPEN-METEO CAMS GLOBAL FORECAST`, `DEMO DATA`, or `DATA UNAVAILABLE`).
- Historical responses disclose exact `storage_origin`: `fresh_provider_retrieval`, `historical_cache`, `persisted_database_records`, or `persisted_database_fallback`.
- If Open-Meteo is unreachable during a historical request and persisted SQLite records exist, the backend returns them explicitly marked `persisted_database_fallback` (with `served_from_persistence: true` and populated `fallback_reason`) and skips the in-memory historical cache so the next request can recover immediately once Open-Meteo returns. Demo data is never substituted on upstream failure.
