# AIRWISE AI — Day 1 Architecture & Foundation Overview

**Project:** AIRWISE AI (Hack2Skill PromptWars Challenge 6: Urban Air Quality Assistant)  
**Target OS & Shell:** Windows 11 / Windows PowerShell  

---

## 1. Architectural Principles

1. **Strict Separation of Frontend & Backend:**
   - `frontend/`: Next.js App Router (TypeScript + Tailwind CSS) running on `http://localhost:3000`.
   - `backend/`: Python 3.12 FastAPI service with Pydantic v2 validation running on `http://127.0.0.1:8000`.
2. **Honest Data Integrity (Demo Data Disclosure):**
   - No live atmospheric sensor provider or LLM key is connected in the Day 1 foundation.
   - Both the backend API (`is_demo_data: true`, `data_mode: "demo"`) and the frontend dashboard explicitly banner all AQI values, pollutant concentrations, health advisories, and assistant previews as **deterministic sample/demo scenarios**.
   - Offline resilience: If the FastAPI backend is stopped or unreachable, the frontend displays a clear alert banner and falls back to an explicitly labelled local demo dataset (`DEMO DATA (LOCAL FALLBACK)`).
3. **Security & Zero Secret Exposure:**
   - CORS on the FastAPI backend is restricted by default to `http://localhost:3000` and `http://127.0.0.1:3000` with `allow_credentials=False` and read-only HTTP methods (`GET`, `OPTIONS`).
   - Query parameters (`location`) are validated with regex and length bounds (`min_length=2, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$"`).
   - No API keys or secrets are stored in code.

---

## 2. Backend API Contract (`/api/v1`)

### `GET /api/v1/health`
Returns service readiness and confirms demo data mode:
```json
{
  "status": "ok",
  "service": "AIRWISE AI API",
  "version": "0.1.0",
  "environment": "development",
  "data_mode": "demo",
  "live_provider_connected": false
}
```

### `GET /api/v1/dashboard?location=lagos-ng`
Returns the structured urban air quality dashboard payload validated by `DashboardResponse`:
- `is_demo_data`: `true`
- `data_mode`: `"demo"`
- `data_source_label` & `disclaimer`: Human-readable disclosures that data is simulated.
- `selected_location`: Defaults to **Lagos, Nigeria (`lagos-ng`)**. Also supports `abuja-ng`, `nairobi-ke`, and `accra-gh`.
- `summary`: Sample AQI value, AQI category band, dominant pollutant, plain-language summary, and weather dispersion context.
- `pollutants`: 4 pollutant breakdown cards (`PM2.5`, `PM10`, `NO2`, `O3`) with sample values, units, status levels, WHO reference notes, and typical urban sources.
- `health_advisory`: Population-segmented guidance (Sensitive Groups, Outdoor Workers/Commuters, General Population).
- `daily_recommendations`: Time-windowed urban exposure reduction recommendations.
- `assistant_preview`: Interactive sample Q&A preview demonstrating how the AIRWISE AI assistant answers urban air quality questions.
