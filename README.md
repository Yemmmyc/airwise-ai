# AIRWISE AI — Urban Air Quality Intelligence Assistant

**Hack2Skill PromptWars Challenge 6: Urban Air Quality Assistant**

AIRWISE AI is a local-first, full-stack environmental intelligence platform for urban air quality monitoring, regional mapping, historical trend analysis, and Gemini-powered contextual guidance across four African cities: **Lagos (Nigeria)**, **Abuja (Nigeria)**, **Nairobi (Kenya)**, and **Accra (Ghana)**.

> **Local-Only Notice:** AIRWISE AI runs completely locally on Windows 11 (PowerShell) with zero cloud deployment, zero database server installations, and zero paid subscriptions required.

---

## 1. Current System Architecture

### Frontend (`C:\Projects\airwise-ai\frontend`)
- **Stack:** Next.js 16.4.6 (App Router), React 18, TypeScript, Tailwind CSS (Enterprise Dark Charcoal / Forest Green / Teal & Mint theme), and Leaflet (`leaflet` + `@types/leaflet`).
- **Key Modules:**
  - **Live Air Quality Dashboard ([DashboardClient.tsx](file:///c:/Projects/airwise-ai/frontend/src/components/DashboardClient.tsx)):** Synchronized city selector (`lagos-ng`, `abuja-ng`, `nairobi-ke`, `accra-gh`), US EPA AQI summary with category legend, 5 pollutant cards (`PM2.5`, `PM10`, `NO2`, `O3`, `SO2`), future-only hourly forecast timeline + accessible table, CAMS Global provenance section, non-medical health guidance, and explicit Demo Mode toggle.
  - **Air Quality Intelligence Map ([AirQualityMapSection.tsx](file:///c:/Projects/airwise-ai/frontend/src/components/AirQualityMapSection.tsx), [LeafletMapCanvas.tsx](file:///c:/Projects/airwise-ai/frontend/src/components/LeafletMapCanvas.tsx)):** Interactive Leaflet map using free, keyless CARTO Dark Matter / OpenStreetMap tiles plotting all 4 configured cities (no browser GPS/geolocation permissions requested), synchronized bidirectionally with the dashboard location selector.
  - **Historical Trends & Insights ([HistoricalTrendsSection.tsx](file:///c:/Projects/airwise-ai/frontend/src/components/HistoricalTrendsSection.tsx)):** Zero-dependency accessible custom SVG charts supporting 7, 14, and 30-day ranges, 6 selectable metrics (`US AQI`, `PM2.5`, `PM10`, `NO2`, `O3`, `SO2`), daily summaries & peaks, 7-day hourly model series, 4-city daily AQI comparison (distinct color, dash pattern, and marker shape per city), non-causal observational insights, and accessible tabular alternatives.
  - **Gemini Air Quality Assistant ([AssistantPanel.tsx](file:///c:/Projects/airwise-ai/frontend/src/components/AssistantPanel.tsx)):** Interactive conversation experience supporting **Ask AIRWISE**, **Daily Activity Planner**, **Pollutant Education**, and **4-City Comparison**, strictly grounded in verified FastAPI Open-Meteo responses with explicit separation of verified data, forecast data, AI interpretation, and general non-medical health guidance.
- **Strict Frontend/Backend Boundary:** The browser communicates **only** with the local FastAPI backend (`NEXT_PUBLIC_API_BASE_URL`). It never calls Open-Meteo or Google Gemini directly and never holds API secrets.

### Backend (`C:\Projects\airwise-ai\backend`)
- **Stack:** Python 3.12, FastAPI, Pydantic v2, `pydantic-settings`, `httpx`, `google-genai` (official Google Gen AI SDK), Python standard-library `sqlite3`, and `pytest`.
- **Key Services:**
  - `app/services/open_meteo.py`: Live Open-Meteo CAMS Global model retrieval, timezone-aware temporal classification (`historical_model`, `current_model`, `hourly_forecast`), unit normalization, and 300-second in-memory live TTL cache.
  - `app/services/open_meteo_history.py`: Historical Open-Meteo retrieval (`past_days=7|14|30`, `forecast_days=0`), local-timezone daily aggregations, period summaries, dedicated 20-minute historical in-memory TTL cache, and fault-isolated 4-city comparison.
  - `app/services/history_store.py`: Modular Python stdlib `sqlite3` persistence (`backend/data/airwise_history.db`, excluded from Git) keyed by `(location_id, timestamp_utc, model_domain)` with idempotent upserts and upstream-outage fallback.
  - `app/services/gemini_assistant.py`: Backend-only Gemini integration (`gemini-2.5-flash` via `google-genai`) grounded strictly in verified Open-Meteo data, returning a clean `HTTP 503 assistant_unavailable` state whenever `GEMINI_API_KEY` is unset.
  - `app/services/demo_data.py`: Canonical 4-city location registry and deterministic Day 1 demo scenarios (used only when the user explicitly selects Demo Mode).

---

## 2. Supported Cities (Canonical Location Registry)

| `location_id` | City & Country | Coordinates (`lat`, `lon`) | IANA Timezone |
| :--- | :--- | :--- | :--- |
| `lagos-ng` *(default)* | Lagos, Nigeria | `6.5244, 3.3792` | `Africa/Lagos` |
| `abuja-ng` | Abuja, Nigeria | `9.0765, 7.3986` | `Africa/Lagos` |
| `nairobi-ke` | Nairobi, Kenya | `-1.2921, 36.8219` | `Africa/Nairobi` |
| `accra-gh` | Accra, Ghana | `5.6037, -0.1870` | `Africa/Accra` |

---

## 3. Data Provenance, Integrity & Scientific Limitations

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

## 4. Backend API Endpoints (`/api/v1`)

| Method & Endpoint | Query / Body | Description |
| :--- | :--- | :--- |
| `GET /api/v1/health` | — | Service health check and API version metadata. |
| `GET /api/v1/dashboard` | `location=lagos-ng` | Explicit Day 1 deterministic demo dataset (`is_demo_data: true`). |
| `GET /api/v1/air-quality` | `location_id=lagos-ng` | Current CAMS Global model estimate (`us_aqi`, `pm2_5`, `pm10`, `no2`, `o3`, `so2`) + strictly future hourly forecast (`> observation_time`) + 300s in-memory cache. |
| `GET /api/v1/air-quality/history` | `location_id=lagos-ng&days=7\|14\|30&force_refresh=false` | Genuine historical hourly records (`historical_model`), local-timezone daily summaries, period summary, completeness %, SQLite persistence, and 20-minute historical cache. |
| `GET /api/v1/air-quality/history/compare` | `days=7\|14\|30&force_refresh=false` | Fault-isolated historical comparison across Lagos, Abuja, Nairobi, and Accra. A failure in one city never fails the others. |
| `GET /api/v1/assistant/status` | — | Safe readiness check confirming whether backend `GEMINI_API_KEY` is configured (never exposes secrets). |
| `POST /api/v1/assistant/ask` | JSON (`location_id`, `mode`, `question`, `pollutant_code`, `history`) | Grounded Gemini assistant (`ask`, `activity_planner`, `pollutant_education`, `city_comparison`). Returns `HTTP 503 assistant_unavailable` if `GEMINI_API_KEY` is unset. |

---

## 5. Environment Variables

### Backend (`backend/.env` — copy from `backend/.env.example`)
| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `AIRWISE_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Allowed CORS origins for the local Next.js frontend. |
| `AIRWISE_OPEN_METEO_DOMAINS` | `cams_global` | Open-Meteo atmospheric model domain. |
| `AIRWISE_OPEN_METEO_TIMEOUT_SECONDS` | `8.0` | Timeout for live Open-Meteo requests. |
| `AIRWISE_OPEN_METEO_CACHE_TTL_SECONDS` | `300` | In-memory TTL (seconds) for live `/air-quality` responses. |
| `AIRWISE_HISTORY_DB_PATH` | `data/airwise_history.db` | Local SQLite file path (relative to `backend/`, Git-ignored). |
| `AIRWISE_HISTORY_CACHE_TTL_SECONDS` | `1200` | Dedicated 20-minute in-memory TTL for historical queries. |
| `AIRWISE_HISTORY_REFRESH_MAX_AGE_SECONDS` | `21600` | Max age (6 hours) before persisted SQLite windows refresh from Open-Meteo. |
| `AIRWISE_HISTORY_TIMEOUT_SECONDS` | `12.0` | Timeout for historical Open-Meteo requests. |
| `GEMINI_API_KEY` *(or `AIRWISE_GEMINI_API_KEY`)* | *(unset)* | Optional backend-only Google AI Studio key for Gemini assistant. **Never place in frontend `.env.local`.** |
| `AIRWISE_GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model ID used via `google-genai`. |
| `AIRWISE_GEMINI_TIMEOUT_SECONDS` | `15.0` | Timeout for Gemini API calls. |

### Frontend (`frontend/.env.local` — copy from `frontend/.env.example`)
| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://127.0.0.1:8000` | Local FastAPI backend base URL. |

---

## 6. Local Installation & Startup (Windows 11 PowerShell)

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

## 7. Running Tests & Verification (Windows PowerShell)

### Backend Automated Test Suite (`pytest`)
```powershell
cd C:\Projects\airwise-ai\backend
.\.venv\Scripts\python.exe -m pytest -v
```
Runs all **44 offline mocked tests** across `tests/test_api.py` (24), `tests/test_assistant.py` (9), and `tests/test_history.py` (11).

### Frontend TypeScript Check & Production Build
```powershell
cd C:\Projects\airwise-ai\frontend
npm.cmd run typecheck
npm.cmd run build
```

---

## 8. Troubleshooting (Windows 11)

- **PowerShell script execution policy blocks `npm`:** Use `npm.cmd` (e.g., `npm.cmd run dev`, `npm.cmd run build`) instead of `npm` to bypass `npm.ps1` execution policy restrictions.
- **Next.js Turbopack socket error on Windows:** `package.json` already configures `"build": "next build --webpack"` for reliable local Windows builds.
- **Gemini Assistant shows "Assistant Unavailable":** Expected when `GEMINI_API_KEY` is blank or unset in `backend/.env`. All live Open-Meteo AQI cards, forecasts, map markers, and historical trends continue working without a Gemini key.
- **Resetting local SQLite historical store:** Stop the backend and delete `backend\data\airwise_history.db`; it will be recreated automatically on the next historical API request.
