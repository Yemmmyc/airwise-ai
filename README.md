# AIRWISE AI — Urban Air Quality Intelligence Assistant

**Hack2Skill PromptWars Challenge 6: Urban Air Quality Assistant**

> **Deployment Status Notice:** AIRWISE AI currently runs locally on Windows 11 (PowerShell) with zero paid subscriptions required. No public deployment URL is published yet; live URLs and screenshots will be added only after deployment is independently verified.

---

## 1. Problem Statement

Families and urban residents in rapidly growing African cities—such as **Lagos**, **Abuja**, **Nairobi**, and **Accra**—often lack accessible, trustworthy, and actionable daily air-quality guidance. Raw pollutant numbers are difficult for households to translate into practical decisions about children's outdoor play, school commutes, outdoor exercise, elderly precautions, indoor ventilation timing, or low-emission daily habits. Conversely, generic AI chatbots frequently hallucinate unverified readings or blur regional model estimates with street-level sensor telemetry.

---

## 2. Solution Overview

AIRWISE AI is a full-stack Urban Air Quality Assistant that combines transparent atmospheric model data with deterministic risk analytics and strictly grounded AI guidance across four African cities: **Lagos (Nigeria)**, **Abuja (Nigeria)**, **Nairobi (Kenya)**, and **Accra (Ghana)**.

- **Live Model Monitoring & 4-City Map:** Displays US EPA AQI, five core pollutants (`PM2.5`, `PM10`, `NO2`, `O3`, `SO2`), future-only hourly forecasts, and a bidirectional Leaflet intelligence map.
- **Historical Trends & Deterministic Predictive Intelligence:** Provides 7/14/30-day historical trends, 4-city comparisons, Peak Forecast Risk, elevated-risk windows, single-hour spikes, comparatively favorable windows, and independent activity planning.
- **Family-Focused Grounded Gemini Assistant:** Translates verified Open-Meteo model data and future forecast windows into practical family routine guidance, low-emission household/commute habits, and indoor ventilation tips without fabricating numbers or giving medical advice.
- **Strict Scientific Honesty:** Explicitly distinguishes live model data, forecasts, historical records, cached/persisted fallbacks, AI interpretation, and Demo Mode.

---

## 3. Architecture & Technology Stack

### Frontend (`C:\Projects\airwise-ai\frontend`)
- **Stack:** Next.js 16.4.6 (App Router), React 18, TypeScript, Tailwind CSS (Enterprise Dark Charcoal / Forest Green / Teal & Mint theme), and Leaflet (`leaflet` + `@types/leaflet`).
- **Key Modules:**
  - **Live Air Quality Dashboard ([DashboardClient.tsx](file:///c:/Projects/airwise-ai/frontend/src/components/DashboardClient.tsx)):** Synchronized city selector (`lagos-ng`, `abuja-ng`, `nairobi-ke`, `accra-gh`), US EPA AQI summary with category legend, 5 pollutant cards (`PM2.5`, `PM10`, `NO2`, `O3`, `SO2`), future-only hourly forecast timeline + accessible table, CAMS Global provenance section, non-medical health guidance, and explicit Demo Mode toggle.
  - **Air Quality Intelligence Map ([AirQualityMapSection.tsx](file:///c:/Projects/airwise-ai/frontend/src/components/AirQualityMapSection.tsx), [LeafletMapCanvas.tsx](file:///c:/Projects/airwise-ai/frontend/src/components/LeafletMapCanvas.tsx)):** Interactive Leaflet map using free, keyless CARTO Dark Matter / OpenStreetMap tiles plotting all 4 configured cities (no browser GPS/geolocation permissions requested), synchronized bidirectionally with the dashboard location selector.
  - **Historical Trends & Insights ([HistoricalTrendsSection.tsx](file:///c:/Projects/airwise-ai/frontend/src/components/HistoricalTrendsSection.tsx)):** Zero-dependency accessible custom SVG charts supporting 7, 14, and 30-day ranges, 6 selectable metrics (`US AQI`, `PM2.5`, `PM10`, `NO2`, `O3`, `SO2`), daily summaries & peaks, 7-day hourly model series, 4-city daily AQI comparison (distinct color, dash pattern, and marker shape per city), non-causal observational insights, and accessible tabular alternatives.
  - **Predictive Intelligence & Risk Insights ([PredictiveIntelligenceSection.tsx](file:///c:/Projects/airwise-ai/frontend/src/components/PredictiveIntelligenceSection.tsx)):** Phase 7 deterministic risk UI displaying **Peak Forecast Risk**, elevated-risk windows, isolated single-hour spikes, comparatively favorable windows, independent activity-planning cards, 6-metric non-color trend signals, and transparent forecast data-quality evidence (paused automatically in Demo Mode).
  - **Gemini Air Quality Assistant ([AssistantPanel.tsx](file:///c:/Projects/airwise-ai/frontend/src/components/AssistantPanel.tsx)):** Interactive conversation experience supporting **Ask AIRWISE**, **Daily Activity Planner**, **Pollutant Education**, and **4-City Comparison**, strictly grounded in verified FastAPI Open-Meteo responses with explicit separation of verified data, forecast data, AI interpretation, and general non-medical health guidance.
- **Strict Frontend/Backend Boundary:** The browser communicates **only** with the local FastAPI backend (`NEXT_PUBLIC_API_BASE_URL`). It never calls Open-Meteo or Google Gemini directly and never holds API secrets.

### Backend (`C:\Projects\airwise-ai\backend`)
- **Stack:** Python 3.12, FastAPI, Pydantic v2, `pydantic-settings`, `httpx`, `google-genai` (official Google Gen AI SDK), Python standard-library `sqlite3`, and `pytest`.
- **Phase 9.1 Reliability & Observability Architecture (`docs/ARCHITECTURE.md`):**
  - `app/main.py`: FastAPI lifespan owning one shared synchronous `httpx.Client` pool (`max_connections=20`, `max_keepalive_connections=10`, `keepalive_expiry=30.0s`) with deterministic shutdown, `X-Request-ID` correlation middleware, and baseline security response headers (`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`).
  - `app/core/logging_config.py`: Structured stdlib logging (`AIRWISE_LOG_LEVEL`, default `INFO`), `contextvars`-backed `X-Request-ID` propagation (including `ThreadPoolExecutor` comparison workers), and defense-in-depth secret redaction across log messages and tracebacks.
  - `app/core/ttl_cache.py`: Thread-safe `SingleFlightTTLCache` with bounded per-key locks, double-checked reads, monotonic TTL expiration, and deep-copy isolation preventing thundering-herd upstream bursts.
- **Key Services:**
  - `app/services/open_meteo.py`: Live Open-Meteo CAMS Global model retrieval, timezone-aware temporal classification (`historical_model`, `current_model`, `hourly_forecast`), unit normalization, and 300-second single-flight live TTL cache.
  - `app/services/open_meteo_history.py`: Historical Open-Meteo retrieval (`past_days=7|14|30`, `forecast_days=0`), local-timezone daily aggregations, period summaries, dedicated 20-minute single-flight historical TTL cache, and fault-isolated 4-city comparison.
  - `app/services/history_store.py`: Modular Python stdlib `sqlite3` persistence (`backend/data/airwise_history.db`, excluded from Git) with deterministic connection cleanup, explicit transaction boundaries, `PRAGMA journal_mode=WAL` (with fallback), `PRAGMA busy_timeout=5000`, idempotent upserts, and upstream-outage fallback.
  - `app/services/predictive_intelligence.py`: Phase 7 deterministic, rule-based analytical engine transforming authoritative Open-Meteo CAMS Global 24-hour forecasts into Peak Forecast Risk, elevated-risk windows, single-hour spikes, comparatively favorable windows, independent activity guidance, provisional OLS trend signals, and qualitative data-quality evidence (zero AI generation, zero ML training).
  - `app/services/gemini_assistant.py`: Backend-only Gemini Developer API integration (`gemini-3.5-flash-lite` default, configurable via `AIRWISE_GEMINI_MODEL`, via `google-genai`) grounded strictly in verified Open-Meteo data, returning a clean `HTTP 503 assistant_unavailable` state whenever `GEMINI_API_KEY` is unset.
  - `app/services/demo_data.py`: Canonical 4-city location registry and deterministic Day 1 demo scenarios (used only when the user explicitly selects Demo Mode).

---

## 4. AI Integration & Prompt Design

AIRWISE AI integrates **Google Gemini (`gemini-3.5-flash-lite` default, configurable via `AIRWISE_GEMINI_MODEL`)** exclusively on the FastAPI backend via the Gemini Developer API and official `google-genai` SDK (`app/services/gemini_assistant.py`), keeping `GEMINI_API_KEY` completely isolated from the browser.

- **Strict Backend Data Grounding:** Every `POST /api/v1/assistant/ask` call fetches verified live and future-only forecast data via `fetch_open_meteo_air_quality()` (reusing the shared HTTP pool and single-flight cache) and injects that structured JSON snapshot into the prompt.
- **Four Assistant Modes:** `ask`, `activity_planner` (family routine, children's play, school commute, household errands, exercise, elderly precautions, low-emission habits, and indoor ventilation timing), `pollutant_education`, and `city_comparison`.
- **Enforced Five-Section JSON Response Contract:** Gemini is instructed to return strict JSON validated by Pydantic (`StructuredAssistantSections`):
  1. `verified_data_summary` — Factual summary citing exact verified model values, units, and timestamps (or explicit unavailability).
  2. `forecast_context` — Factual summary of strictly future forecast hours (`> observation_time`) or explicit disclosure when unavailable.
  3. `ai_interpretation` — Grounded answer to the user's question.
  4. `general_health_guidance` — General informational precautions (non-medical; no diagnosis, treatment, or medication advice).
  5. `model_limitations_notice` — Concise disclosure of CAMS Global ~45 km grid / 3-hourly native resolution and non-sensor nature.
- **Anti-Hallucination & Honesty Guardrails:**
  - Never fabricates AQI values, pollutant readings, safe hours, or numerical emission-reduction percentages.
  - Explicitly distinguishes location-specific, data-grounded guidance from general precautionary indoor/household tips.
  - Never claims outdoor CAMS Global estimates measure indoor air quality.
  - Returns a clean `HTTP 503 assistant_unavailable` state when `GEMINI_API_KEY` is unset.

---

## 5. Family-Focused Demonstration Workflow

1. **Select a City:** Open AIRWISE AI and switch between Lagos, Abuja, Nairobi, and Accra via the header selector or interactive map.
2. **Inspect Current Conditions & Pollutants:** Review the US EPA AQI banner, observation timestamp, and 5 pollutant cards (`PM2.5`, `PM10`, `NO2`, `O3`, `SO2`) with plain-language health context.
3. **Explore Historical Trends & Predictive Intelligence:** Review 7/14/30-day trends, 4-city comparisons, Peak Forecast Risk, elevated-risk windows, and comparatively favorable outdoor windows.
4. **Run Family Routine & Indoor Guidance Prompts:** In the **AIRWISE AI Assistant**, click **`Family routine & low-emission plan`** or **`Indoor air & ventilation tips`** to receive grounded guidance covering children's outdoor play, school commute timing, elderly precautions, avoiding generator exhaust/open burning/idling, and indoor ventilation timing.
5. **Verify Provenance & Timestamps:** Confirm every section explicitly separates verified model data, forecast context, AI interpretation, non-medical guidance, and CAMS Global model limitations.

---

## 6. Supported Cities (Canonical Location Registry)

| `location_id` | City & Country | Coordinates (`lat`, `lon`) | IANA Timezone |
| :--- | :--- | :--- | :--- |
| `lagos-ng` *(default)* | Lagos, Nigeria | `6.5244, 3.3792` | `Africa/Lagos` |
| `abuja-ng` | Abuja, Nigeria | `9.0765, 7.3986` | `Africa/Lagos` |
| `nairobi-ke` | Nairobi, Kenya | `-1.2921, 36.8219` | `Africa/Nairobi` |
| `accra-gh` | Accra, Ghana | `5.6037, -0.1870` | `Africa/Accra` |

---

## 7. Data Sources, Provenance & Attribution

AIRWISE AI strictly separates every data category and never silently mixes live, historical, cached, persisted, or demo values:

- **Open-Meteo / CAMS Global Model Specifications:**
  - **Source:** Official [Open-Meteo Air Quality API](https://open-meteo.com/en/docs/air-quality-api) (`https://air-quality-api.open-meteo.com/v1/air-quality`) using Copernicus Atmosphere Monitoring Service (**CAMS Global**, `cams_global`).
  - **Spatial Resolution:** Approximately **0.4° (~45 km)** regional atmospheric grid cell average. It does **not** measure exact street-level, roadside, or indoor personal exposure.
  - **Temporal Resolution:** Native underlying CAMS Global output is **3-hourly**, interpolated by Open-Meteo to **1-hourly** API timestamps. Values are **not** independent hourly physical monitoring station readings.
  - **Forecast Horizon:** Up to **5 days**, subject to provider availability.
  - **US AQI:** Reported directly from Open-Meteo's `us_aqi` output (never synthetically recalculated).
  - **Non-Causal Historical Insights:** Historical trends and comparisons describe observed model-estimated patterns only and never infer unverified causes (such as traffic, fires, or industrial events).
- **Explicit Data Labels:**
  - `LIVE PROVIDER DATA — MODEL-BASED ESTIMATE` (current model conditions)
  - `HOURLY FORECAST` (strictly timestamps `> observation_time`)
  - `HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE` (strictly timestamps `< current UTC`, with explicit `storage_origin`: `fresh_provider_retrieval`, `historical_cache`, `persisted_database_records`, or `persisted_database_fallback`)
  - `DEMO DATA` (activated **only** when the user explicitly toggles Demo Mode; live map markers and historical model charts pause in Demo Mode)
  - `DATA UNAVAILABLE` (missing/null individual variables or unreachable cities remain `null` and are never zero-filled or replaced with demo data)
- **Attribution:**
  - Weather and air quality data by Open-Meteo.com (`https://open-meteo.com/en/docs/air-quality-api`)
  - Contains modified Copernicus Atmosphere Monitoring Service (CAMS) information (`https://atmosphere.copernicus.eu/`)
  - Map basemap tiles: `© OpenStreetMap contributors © CARTO` (Dark Matter)

---

## 8. Backend API Endpoints (`/api/v1`)

| Method & Endpoint | Query / Body | Description |
| :--- | :--- | :--- |
| `GET /api/v1/health` | — | Lightweight, zero-network runtime health check reporting `status` (`ok`/`degraded`), `provider_configured`, `live_provider_connected` (`false`), `history_store_status`, `assistant_configured` (boolean only), and `supported_locations_count`. |
| `GET /api/v1/dashboard` | `location=lagos-ng` | Explicit Day 1 deterministic demo dataset (`is_demo_data: true`). |
| `GET /api/v1/air-quality` | `location_id=lagos-ng` | Current CAMS Global model estimate (`us_aqi`, `pm2_5`, `pm10`, `no2`, `o3`, `so2`) + strictly future hourly forecast (`> observation_time`) + 300s in-memory cache. |
| `GET /api/v1/air-quality/history` | `location_id=lagos-ng&days=7\|14\|30&force_refresh=false` | Genuine historical hourly records (`historical_model`), local-timezone daily summaries, period summary, completeness %, SQLite persistence, and 20-minute historical cache. |
| `GET /api/v1/air-quality/history/compare` | `days=7\|14\|30&force_refresh=false` | Fault-isolated historical comparison across Lagos, Abuja, Nairobi, and Accra. A failure in one city never fails the others. |
| `GET /api/v1/air-quality/intelligence` | `location_id=lagos-ng` | Phase 7 deterministic Predictive Intelligence & Risk Insights (Peak Forecast Risk, elevated-risk windows, single-hour spikes, comparatively favorable windows, independent activity planner, 6-metric provisional OLS trend signals, and qualitative data-quality evidence). |
| `GET /api/v1/assistant/status` | — | Safe readiness check confirming whether backend `GEMINI_API_KEY` is configured (never exposes secrets). |
| `POST /api/v1/assistant/ask` | JSON (`location_id`, `mode`, `question`, `pollutant_code`, `history`) | Grounded Gemini assistant (`ask`, `activity_planner`, `pollutant_education`, `city_comparison`). Returns `HTTP 503 assistant_unavailable` if `GEMINI_API_KEY` is unset. |

### Phase 7 Predictive Intelligence Overview & Algorithmic Limitations

**Endpoint:** `GET /api/v1/air-quality/intelligence?location_id={id}` (canonical IDs: `lagos-ng`, `abuja-ng`, `nairobi-ke`, `accra-gh`).

- **Deterministic Engine (`app/services/predictive_intelligence.py`):**
  - **Peak Forecast Risk:** Anchored on maximum hourly forecast US AQI so short spikes are not hidden by a daily mean, accompanied by mean AQI, minimum AQI, dominant category, and hourly category distribution. Does not imply uniform all-day risk.
  - **Elevated-Risk Windows & Single-Hour Spikes:** Detects `>= 2` consecutive forecast hours at `US AQI >= 101` (`duration_hours = len(window_observations)`). Missing observations, timestamp gaps (`Δt != 1h`), or lower-risk hours immediately terminate windows (never merged). Isolated 1-hour spikes are preserved in `single_hour_spikes`.
  - **Comparatively Favorable Windows (2–4h) & Independent Activity Planner:** Share a contiguous 100%-valid candidate-window generator (`generate_contiguous_windows`) while evaluating general comparative windows (`<= 150` ceiling) and activity rules (`outdoor_exercise` 2–3h `<= 100`, `outdoor_errands` 1–2h `<= 150`, `general_outdoor` 2–4h `<= 150`) independently.
  - **Independent Trend Signals:** Computes elapsed-hour OLS trends separately for `US AQI`, `PM2.5`, `PM10`, `NO2`, `O3`, and `SO2` (`Rising`, `Stable`, `Falling`, `Insufficient data`) without zero-filling missing points.
  - **Transparent Data-Quality Evidence:** Returns qualitative tiers (`High`, `Moderate`, `Limited`, `Insufficient data`), valid/missing hour counts, timestamp continuity, per-pollutant coverage, cache hit status, and per-module sufficiency—with **no arbitrary 0–100 numeric confidence score**.
- **Algorithmic & Scientific Limitations:**
  - All risk-window defaults, trend slope/percentage/noise-floor/`R²` thresholds, and activity ceilings are **provisional MVP engineering heuristics**, not medically validated exposure limits or empirically calibrated forecast accuracy statistics.
  - `R²` is used solely as a provisional noise-suppression heuristic and does **not** represent forecast reliability.
  - Qualitative data-quality tiers measure **available input completeness and continuity only**, not statistical forecast accuracy.
  - Outputs are derived from Open-Meteo **CAMS Global** (~0.4° / ~45 km grid, 3-hourly native output interpolated to 1-hourly API timestamps), not roadside physical sensor measurements. AIRWISE AI has not trained a new atmospheric forecasting model and provides no medical diagnosis or guarantee of personal safety.

**Illustrative Response Structure (Not Live Forecast Data):**
```json
{
  "location": { "id": "lagos-ng", "display_name": "Lagos, Nigeria", "timezone": "Africa/Lagos" },
  "data_mode": "predictive_intelligence",
  "data_label": "ANALYTICAL INTERPRETATION — BASED ON OPEN-METEO CAMS GLOBAL FORECAST",
  "observation_time": "2026-11-21T08:00",
  "retrieval_time": "2026-11-21T07:05:00Z",
  "horizon_hours": 24,
  "daily_summary": {
    "peak_forecast_risk": "Moderate",
    "peak_aqi": 87,
    "peak_time": "2026-11-21T09:00",
    "mean_aqi": 68.4,
    "min_aqi": 52,
    "dominant_category": "Moderate",
    "risk_window_evaluation_status": "evaluated",
    "risk_windows_count": 0,
    "single_hour_spikes_count": 0,
    "better_windows_count": 2,
    "data_quality_tier": "High",
    "deterministic_summary": "Across 24/24 available forecast hours..."
  },
  "risk_windows": [],
  "single_hour_spikes": [],
  "better_windows": { "status": "windows_identified", "guardrail_max_aqi_ceiling": 150, "windows": [] },
  "trend_signals": [{ "metric": "us_aqi", "signal": "Stable", "valid_points": 24, "volatility_flag": false }],
  "activity_recommendations": [{ "activity_type": "outdoor_exercise", "status": "window_identified", "is_medical_advice": false }],
  "data_quality": { "tier": "High", "valid_aqi_hours": 24, "expected_forecast_hours": 24, "completeness_percent": 100.0, "timestamp_continuity": "continuous" },
  "is_demo_data": false,
  "is_ai_generated": false
}
```

---

## 9. Environment Variables

### Backend (`backend/.env` — copy from `backend/.env.example`)
| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `AIRWISE_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Allowed CORS origins for the local Next.js frontend. |
| `AIRWISE_LOG_LEVEL` | `INFO` | Backend structured logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `AIRWISE_OPEN_METEO_DOMAINS` | `cams_global` | Open-Meteo atmospheric model domain. |
| `AIRWISE_OPEN_METEO_TIMEOUT_SECONDS` | `8.0` | Timeout for live Open-Meteo requests. |
| `AIRWISE_OPEN_METEO_CACHE_TTL_SECONDS` | `300` | In-memory TTL (seconds) for live `/air-quality` responses. |
| `AIRWISE_HISTORY_DB_PATH` | `data/airwise_history.db` | Local SQLite file path (relative to `backend/`, Git-ignored). |
| `AIRWISE_HISTORY_CACHE_TTL_SECONDS` | `1200` | Dedicated 20-minute in-memory TTL for historical queries. |
| `AIRWISE_HISTORY_REFRESH_MAX_AGE_SECONDS` | `21600` | Max age (6 hours) before persisted SQLite windows refresh from Open-Meteo. |
| `AIRWISE_HISTORY_TIMEOUT_SECONDS` | `12.0` | Timeout for historical Open-Meteo requests. |
| `GEMINI_API_KEY` *(or `AIRWISE_GEMINI_API_KEY`)* | *(unset)* | Optional backend-only Google AI Studio key for Gemini assistant. **Never place in frontend `.env.local`.** |
| `AIRWISE_GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini Developer API model ID used via `google-genai` (overrideable via env var). |
| `AIRWISE_GEMINI_TIMEOUT_SECONDS` | `15.0` | Timeout for Gemini API calls. |

### Frontend (`frontend/.env.local` — copy from `frontend/.env.example`)
| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://127.0.0.1:8000` | Local FastAPI backend base URL. |

---

## 10. Local Installation & Startup (Windows 11 PowerShell)

### Prerequisites
- **Windows 11** with **Windows PowerShell** (no WSL, Linux, or Docker required)
- **Python 3.12+**
- **Node.js 18.18+ / 20+ LTS** (includes `npm`)

### A. Backend Setup & Run (Port 8000)
```powershell
cd C:\Projects\airwise-ai\backend

# Create virtual environment (first time only)
python -m venv .venv

# Install minimal backend dependencies
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Copy example environment file (optional; add GEMINI_API_KEY in .env to enable Gemini)
Copy-Item .env.example .env

# Start FastAPI server on http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### B. Frontend Setup & Run (Port 3000)
Open a **second Windows PowerShell** terminal:
```powershell
cd C:\Projects\airwise-ai\frontend

# Copy example environment file
Copy-Item .env.example .env.local

# Install frontend dependencies
npm.cmd install

# Start Next.js development server on http://localhost:3000
npm.cmd run dev
```
Open **`http://localhost:3000`** in your browser.

---

## 11. Running Tests & Verification (Windows PowerShell)

### Backend Automated Test Suite (`pytest`)
```powershell
cd C:\Projects\airwise-ai\backend
.\.venv\Scripts\python.exe -m pytest -v
```
Runs all **126 offline mocked tests** across `tests/test_api.py`, `tests/test_assistant.py`, `tests/test_history.py`, `tests/test_intelligence.py`, `tests/test_observability.py`, `tests/test_lifecycle_http.py`, `tests/test_cache_concurrency.py`, and `tests/test_sqlite_reliability.py`.

### Frontend TypeScript Check & Production Build
```powershell
cd C:\Projects\airwise-ai\frontend
npm.cmd run typecheck
npm.cmd run build
```

### Phase 8 — Local Browser & Accessibility QA
Local browser QA uses **Playwright (Chromium)** and **axe-core** (`@playwright/test`, `@axe-core/playwright`) with deterministic mocked API responses and stubbed offline map tiles—no live backend, external APIs, or Gemini API key are required.

**Prerequisites (first time only):**
```powershell
cd C:\Projects\airwise-ai\frontend
npm.cmd install
npx.cmd playwright install chromium
```

**Execution (Windows PowerShell):**
```powershell
cd C:\Projects\airwise-ai\frontend

# 1. Build the local production bundle (required after any frontend source changes)
npm.cmd run build

# 2. Run the complete Playwright QA suite (24 tests: functional, responsive, accessibility)
npm.cmd run test:e2e

# 3. Run only the WCAG 2.1 A/AA axe-core & keyboard accessibility suite (6 tests)
npm.cmd run test:e2e:a11y
```
> **Important:** `playwright.config.ts` starts the compiled local production server (`npm.cmd run start`) on `http://localhost:3000`. Always re-run `npm.cmd run build` after frontend source changes before executing `npm.cmd run test:e2e` or `npm.cmd run test:e2e:a11y`.

---

## 12. Deployment Architecture (Planned Free-Tier Topology)

> **Not Yet Deployed:** No live public URL exists yet. The architecture below documents the verified zero-cost deployment plan for Attempt 1.

- **Frontend (Vercel Hobby — Free):** Deploy `frontend/` directly as a Next.js 16 app with build-time environment variable `NEXT_PUBLIC_API_BASE_URL=https://<backend-origin>`.
- **Backend (Render Free Web Service):** Deploy `backend/` as a single-worker ASGI process (`uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`), health check `/api/v1/health`, and server-only environment variables (`GEMINI_API_KEY`, `AIRWISE_ENVIRONMENT=production`, `AIRWISE_APP_VERSION=0.9.1`, `AIRWISE_LOG_LEVEL=INFO`, `AIRWISE_ALLOWED_ORIGINS=https://<frontend-origin>`).
- **Cold-Start Handling:** The frontend API client (`frontend/src/lib/api.ts`) applies a 35s request timeout and at most one bounded retry on idempotent `GET` requests during non-JSON gateway wake-up / cold-start timeouts (never auto-retrying `POST /api/v1/assistant/ask`).

---

## 13. Screenshots & Demo Guide (Attempt 1 Placeholders)

*Live URLs and screenshots will be added only after public deployment is verified:*

- **Live Web App URL:** *(Pending verified public deployment)*
- **Backend Health Endpoint:** *(Pending verified public deployment)*
- **Screenshot 1 — Live Dashboard & 4-City Map:** *(To be captured post-deployment)*
- **Screenshot 2 — Historical Trends & Predictive Intelligence:** *(To be captured post-deployment)*
- **Screenshot 3 — Family Routine & Low-Emission Gemini Assistant:** *(To be captured post-deployment)*

---

## 14. Known Limitations

- **Open-Meteo CAMS Global Resolution:** Atmospheric model outputs represent an ~0.4° (~45 km) regional grid cell with 3-hourly native resolution interpolated to 1-hourly timestamps—not physical street-level or roadside sensors.
- **Outdoor vs. Indoor Measurement Distinction:** Outdoor CAMS Global estimates do **not** measure indoor air quality. All indoor ventilation and smoke-reduction tips are general precautionary household guidance.
- **Non-Medical Scope:** Health and family guidance is informational only and never constitutes medical diagnosis, treatment, or medication advice.
- **Provisional Predictive Heuristics:** Phase 7 risk-window thresholds, OLS trend signals, and activity ceilings are deterministic MVP heuristics rather than empirically calibrated forecast accuracy statistics.
- **Free-Tier Cold Starts:** On free PaaS web services (e.g., Render Free), idle backend instances spin down after inactivity and may take 30–60 seconds to wake on the first request.
- **Ephemeral SQLite Storage on Free Hosting:** On free containers without persistent disks, `backend/data/airwise_history.db` resets on container restart/redeploy. Historical queries automatically re-initialize SQLite and re-fetch from Open-Meteo, though cross-restart `persisted_database_fallback` is only available while the container remains warm.
- **Gemini Free-Tier Quota:** High-frequency assistant queries may encounter upstream Google AI Studio rate limits (`HTTP 429 assistant_rate_limited`); all live AQI, map, historical, and deterministic intelligence features remain unaffected.

---

## 15. Troubleshooting (Windows 11)

- **PowerShell script execution policy blocks `npm`:** Use `npm.cmd` (e.g., `npm.cmd run dev`, `npm.cmd run build`) instead of `npm` to bypass `npm.ps1` execution policy restrictions.
- **Next.js Turbopack socket error on Windows:** `package.json` already configures `"build": "next build --webpack"` for reliable local Windows builds.
- **Gemini Assistant shows "Assistant Unavailable":** Expected when `GEMINI_API_KEY` is blank or unset in `backend/.env`. All live Open-Meteo AQI cards, forecasts, map markers, and historical trends continue working without a Gemini key.
- **Resetting local SQLite historical store:** Stop the backend and delete `backend\data\airwise_history.db`; it will be recreated automatically on the next historical API request.
