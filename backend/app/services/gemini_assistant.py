"""Modular Gemini Air Quality Assistant service using the official Google Gen AI SDK (`google-genai`).

Core Data Integrity & Security Rules:
- Reads GEMINI_API_KEY / AIRWISE_GEMINI_API_KEY exclusively on the backend; never logs or exposes keys.
- Grounds every answer in verified data fetched from `app.services.open_meteo.fetch_open_meteo_air_quality`.
- Never invents missing AQI or pollutant measurements; explicitly discloses unavailable fields.
- Never fabricates safe forecast hours when future forecast data is absent or elevated.
- Clearly distinguishes verified provider data, future forecast data, AI interpretation, and general health guidance.
- Never describes CAMS Global (~45 km grid, 3-hourly native output) as physical roadside sensor measurements.
- Never provides medical diagnosis, treatment, or medication advice.
- Returns a clearly labelled assistant-unavailable error when credentials are missing rather than pretending Gemini responded.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from app.core.config import Settings, get_settings
from app.core.logging_config import get_logger
from app.schemas.air_quality import AirQualityResponse, DataAttribution, DataProvenance
from app.schemas.assistant import (
    AssistantRequest,
    AssistantResponse,
    AssistantStatusResponse,
    StructuredAssistantSections,
    VerifiedCitySnapshot,
    VerifiedForecastSummary,
    VerifiedPollutantSnapshot,
)
from app.schemas.dashboard import LocationOption
from app.services.demo_data import AVAILABLE_LOCATIONS, get_location_by_id
from app.services.open_meteo import (
    InvalidLocationError,
    OpenMeteoProviderError,
    fetch_open_meteo_air_quality,
)


logger = get_logger(__name__)


class GeminiAssistantError(Exception):
    """Structured base exception for Gemini Assistant failures (safe for API responses)."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "assistant_error",
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code


class GeminiNotConfiguredError(GeminiAssistantError):
    """Raised when GEMINI_API_KEY is missing on the backend."""

    def __init__(self) -> None:
        super().__init__(
            "AIRWISE AI Assistant is unavailable because GEMINI_API_KEY is not configured on the backend. "
            "Set GEMINI_API_KEY in backend/.env to enable Gemini-powered insights.",
            error_code="assistant_unavailable",
            status_code=503,
        )


class GeminiTimeoutError(GeminiAssistantError):
    """Raised when the Gemini API call times out."""

    def __init__(self, timeout_seconds: float) -> None:
        super().__init__(
            f"The Gemini AI service timed out after {timeout_seconds:.1f}s. "
            "Verified air-quality readings remain available on the dashboard; please retry shortly.",
            error_code="assistant_timeout",
            status_code=504,
        )


class GeminiRateLimitError(GeminiAssistantError):
    """Raised when the Gemini API returns a 429 rate-limit / quota response."""

    def __init__(self) -> None:
        super().__init__(
            "The Gemini AI service is temporarily rate-limited (HTTP 429). "
            "Please wait a moment and try your question again.",
            error_code="assistant_rate_limited",
            status_code=429,
        )


class GeminiMalformedResponseError(GeminiAssistantError):
    """Raised when Gemini returns an empty or non-JSON/malformed structured response."""

    def __init__(self, reason: str = "Malformed or empty response from Gemini API.") -> None:
        super().__init__(
            f"AIRWISE AI could not parse a valid structured response from Gemini: {reason}",
            error_code="assistant_malformed_response",
            status_code=502,
        )


class GeminiUpstreamServiceError(GeminiAssistantError):
    """Raised when Gemini API returns an unexpected upstream error."""

    def __init__(self) -> None:
        super().__init__(
            "The Gemini AI service is currently unavailable. Please retry later.",
            error_code="assistant_service_unavailable",
            status_code=502,
        )


def get_assistant_status(settings: Settings | None = None) -> AssistantStatusResponse:
    """Return safe readiness status for the Gemini assistant without exposing secrets."""
    cfg = settings or get_settings()
    if cfg.gemini_api_key:
        return AssistantStatusResponse(
            configured=True,
            status="ready",
            model=cfg.gemini_model,
            sdk="google-genai",
            message=f"AIRWISE AI Assistant is ready (model: {cfg.gemini_model}).",
        )
    return AssistantStatusResponse(
        configured=False,
        status="assistant_unavailable",
        model=cfg.gemini_model,
        sdk="google-genai",
        message=(
            "Assistant unavailable: GEMINI_API_KEY is not configured on the backend. "
            "Configure GEMINI_API_KEY in backend/.env to activate Gemini intelligence."
        ),
    )


def _summarize_forecast(aq: AirQualityResponse) -> VerifiedForecastSummary:
    """Build a strictly factual summary of future-only forecast points (> observation_time)."""
    points = aq.hourly_forecast.points
    if not points:
        return VerifiedForecastSummary(hours_available=0)

    aqi_pairs = [(pt.time, pt.us_aqi) for pt in points if pt.us_aqi is not None]
    min_aqi: int | None = None
    max_aqi: int | None = None
    min_time: str | None = None
    max_time: str | None = None

    if aqi_pairs:
        min_time, min_aqi = min(aqi_pairs, key=lambda pair: pair[1])
        max_time, max_aqi = max(aqi_pairs, key=lambda pair: pair[1])

    return VerifiedForecastSummary(
        hours_available=len(points),
        first_forecast_time=points[0].time,
        last_forecast_time=points[-1].time,
        min_forecast_aqi=min_aqi,
        max_forecast_aqi=max_aqi,
        lowest_aqi_timestamp=min_time,
        highest_aqi_timestamp=max_time,
    )


def _build_verified_snapshot(
    location: LocationOption,
    aq: AirQualityResponse | None,
    error_notice: str | None = None,
) -> VerifiedCitySnapshot:
    """Convert an Open-Meteo AirQualityResponse (or failure) into a transparent snapshot."""
    if aq is None:
        return VerifiedCitySnapshot(
            location=location,
            data_status="unavailable",
            data_label="DATA UNAVAILABLE",
            timezone=location.timezone,
            pollutants=[
                VerifiedPollutantSnapshot(code=code, value=None, unit="µg/m³", status="unavailable")
                for code in ("PM2.5", "PM10", "NO2", "O3", "SO2")
            ],
            forecast_summary=VerifiedForecastSummary(hours_available=0),
            missing_fields=["us_aqi", "PM2.5", "PM10", "NO2", "O3", "SO2", "hourly_forecast"],
            error_notice=error_notice or "Live provider data is currently unavailable.",
        )

    pollutant_objects = [aq.pm2_5, aq.pm10, aq.no2, aq.o3, aq.so2]
    pollutants = [
        VerifiedPollutantSnapshot(
            code=p.code,
            value=p.value if p.status == "available" else None,
            unit=p.unit,
            status=p.status,
        )
        for p in pollutant_objects
    ]

    missing_fields: list[str] = []
    if aq.aqi.status != "available" or aq.aqi.value is None:
        missing_fields.append("us_aqi")
    for p in pollutants:
        if p.status != "available" or p.value is None:
            missing_fields.append(p.code)
    if not aq.hourly_forecast.points:
        missing_fields.append("hourly_forecast")

    return VerifiedCitySnapshot(
        location=aq.location,
        data_status="available",
        data_label=aq.data_label,
        observation_time=aq.observation_time,
        retrieval_time=aq.retrieval_time,
        timezone=aq.timezone,
        us_aqi=aq.aqi.value if aq.aqi.status == "available" else None,
        aqi_band=aq.aqi.band if aq.aqi.status == "available" else None,
        pollutants=pollutants,
        forecast_summary=_summarize_forecast(aq),
        missing_fields=missing_fields,
    )


def _fetch_verified_city_data(
    location: LocationOption,
    *,
    http_client: httpx.Client | None = None,
) -> tuple[AirQualityResponse | None, VerifiedCitySnapshot]:
    """Fetch verified Open-Meteo data for one location without throwing on provider outage."""
    try:
        aq = fetch_open_meteo_air_quality(location_id=location.id, http_client=http_client)
        return aq, _build_verified_snapshot(location, aq)
    except OpenMeteoProviderError as exc:
        return None, _build_verified_snapshot(location, None, error_notice=exc.message)


def _build_system_instruction() -> str:
    """Return strict system instructions enforcing grounding, honesty, and safety."""
    return (
        "You are AIRWISE AI, an urban air-quality intelligence assistant. "
        "You MUST follow every rule below strictly:\n"
        "1. GROUNDING ONLY: Use ONLY the verified Open-Meteo CAMS Global atmospheric model data "
        "supplied in the JSON context. NEVER invent, guess, or fabricate AQI numbers, pollutant "
        "concentrations, timestamps, or forecast hours.\n"
        "2. MISSING DATA HONESTY: If any pollutant, AQI, or future forecast field is null or marked "
        "'unavailable', explicitly state that it is unavailable. Never substitute demo or assumed numbers.\n"
        "3. FORECAST HONESTY: For activity planning, reference ONLY actual future forecast timestamps "
        "and AQI values present in the context. Never invent a 'safe hour' if future forecast data is "
        "unavailable or shows elevated AQI across all available hours.\n"
        "4. MODEL LIMITATIONS: Open-Meteo CAMS Global outputs are atmospheric composition model estimates "
        "(approximately 0.4° / ~45 km spatial grid, 3-hourly native model resolution interpolated to 1-hourly "
        "API timestamps). NEVER describe them as physical roadside sensor measurements. Clearly note when "
        "appropriate that a ~45 km regional grid cannot establish an individual's exact street-level or indoor exposure.\n"
        "5. MEDICAL SAFETY: Provide only general informational environmental health guidance. NEVER provide "
        "medical diagnosis, clinical treatment instructions, or medication/dosage advice.\n"
        "6. OUTPUT FORMAT: Respond ONLY with a valid JSON object matching this exact schema (no markdown fences):\n"
        "{\n"
        '  "verified_data_summary": "Factual summary citing exact verified model values, units, and timestamps (or unavailability).",\n'
        '  "forecast_context": "Factual summary of future forecast hours (> observation_time) or explicit statement if no forecast hours are available.",\n'
        '  "ai_interpretation": "Clear, helpful AI answer to the user question grounded strictly in the verified context.",\n'
        '  "general_health_guidance": "General informational precautions (non-medical; no diagnosis or treatment advice).",\n'
        '  "model_limitations_notice": "Concise disclosure of CAMS Global ~45 km grid / 3-hourly native resolution and non-sensor nature."\n'
        "}"
    )


def _build_user_prompt(
    request: AssistantRequest,
    primary_aq: AirQualityResponse | None,
    primary_snapshot: VerifiedCitySnapshot,
    city_comparisons: list[VerifiedCitySnapshot],
) -> str:
    """Assemble the grounded JSON context + mode-specific task prompt for Gemini."""
    context_payload: dict[str, Any] = {
        "mode": request.mode,
        "selected_location": primary_snapshot.model_dump(mode="json"),
        "model_provenance": {
            "data_label": "LIVE PROVIDER DATA — MODEL-BASED ESTIMATE",
            "provider": "Open-Meteo Air Quality API (CAMS Global)",
            "spatial_resolution": "Approximately 0.4° (~45 km)",
            "source_temporal_resolution": "3-hourly underlying atmospheric model output",
            "api_timestamp_interval": "1-hourly interpolated API timestamps (not independent hourly physical sensor measurements)",
            "is_physical_station_measurement": False,
        },
    }

    if primary_aq is not None and primary_aq.hourly_forecast.points:
        context_payload["future_hourly_forecast_points"] = [
            pt.model_dump(mode="json") for pt in primary_aq.hourly_forecast.points[:12]
        ]
    else:
        context_payload["future_hourly_forecast_points"] = []

    if request.mode == "city_comparison":
        context_payload["all_configured_cities"] = [
            snap.model_dump(mode="json") for snap in city_comparisons
        ]

    mode_directives: dict[str, str] = {
        "ask": (
            "Task: Answer the user's urban air-quality question directly using the verified data context."
        ),
        "activity_planner": (
            "Task: Provide general daily activity planning guidance covering: "
            "(1) Outdoor exercise, (2) Walking, (3) Cycling, (4) Outdoor events, and "
            "(5) Sensitive-group precautions. Cite ONLY the actual future forecast timestamps and AQI values "
            "provided in `future_hourly_forecast_points`. Do NOT invent a safe hour if the forecast does not support it."
        ),
        "pollutant_education": (
            f"Task: Explain the requested pollutant(s) (focus: {request.pollutant_code or 'PM2.5, PM10, NO2, O3, SO2'}) "
            "in accessible plain language, linking the explanation to the verified current model values (or stating if unavailable)."
        ),
        "city_comparison": (
            "Task: Compare Lagos, Abuja, Nairobi, and Accra using strictly the verified snapshots in `all_configured_cities`. "
            "Include each city's observation timestamp, AQI, key pollutants, and explicitly disclose any city or pollutant with unavailable data."
        ),
    }

    history_block = ""
    if request.history:
        turns = "\n".join(
            f"- {turn.role.upper()}: {turn.content}" for turn in request.history[-6:]
        )
        history_block = f"\nRECENT CONVERSATION HISTORY:\n{turns}\n"

    return (
        f"{mode_directives[request.mode]}\n"
        f"{history_block}\n"
        f"USER QUESTION:\n{request.question}\n\n"
        f"VERIFIED BACKEND AIR QUALITY CONTEXT (JSON):\n"
        f"{json.dumps(context_payload, indent=2, ensure_ascii=False)}"
    )


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    """Parse JSON from Gemini response text, safely stripping accidental code fences."""
    cleaned = raw_text.strip()
    if not cleaned:
        raise GeminiMalformedResponseError("Received empty response text.")

    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiMalformedResponseError("Response was not valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise GeminiMalformedResponseError("JSON root must be an object.")
    return parsed


def _create_genai_client(settings: Settings) -> genai.Client:
    """Create a configured Google Gen AI SDK client using the backend-only API key."""
    if not settings.gemini_api_key:
        raise GeminiNotConfiguredError()

    timeout_ms = max(1000, int(settings.gemini_timeout_seconds * 1000))
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=genai_types.HttpOptions(timeout=timeout_ms),
    )


def _invoke_gemini(
    *,
    client: genai.Client,
    model: str,
    system_instruction: str,
    user_prompt: str,
    timeout_seconds: float,
) -> StructuredAssistantSections:
    """Call Gemini via `google-genai` SDK and validate structured JSON sections."""
    try:
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
    except TimeoutError as exc:
        logger.warning("gemini_invoke_timeout model=%s timeout_s=%.1f", model, timeout_seconds)
        raise GeminiTimeoutError(timeout_seconds) from exc
    except genai_errors.APIError as exc:
        code = getattr(exc, "code", None)
        if code == 429:
            logger.warning("gemini_invoke_rate_limited model=%s", model)
            raise GeminiRateLimitError() from exc
        if code in (408, 504):
            logger.warning("gemini_invoke_timeout model=%s status=%s", model, code)
            raise GeminiTimeoutError(timeout_seconds) from exc
        logger.warning("gemini_invoke_api_error model=%s status=%s", model, code)
        raise GeminiUpstreamServiceError() from exc
    except Exception as exc:
        err_name = type(exc).__name__.lower()
        err_str = str(exc).lower()
        if "timeout" in err_name or "timed out" in err_str:
            logger.warning("gemini_invoke_timeout model=%s exc_type=%s", model, type(exc).__name__)
            raise GeminiTimeoutError(timeout_seconds) from exc
        if "429" in err_str or "resource_exhausted" in err_str or "rate limit" in err_str:
            logger.warning("gemini_invoke_rate_limited model=%s exc_type=%s", model, type(exc).__name__)
            raise GeminiRateLimitError() from exc
        logger.warning("gemini_invoke_upstream_error model=%s exc_type=%s", model, type(exc).__name__)
        raise GeminiUpstreamServiceError() from exc

    raw_text = getattr(response, "text", None)
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise GeminiMalformedResponseError("Gemini returned an empty text payload.")

    parsed = _extract_json_object(raw_text)
    required_keys = (
        "verified_data_summary",
        "forecast_context",
        "ai_interpretation",
        "general_health_guidance",
        "model_limitations_notice",
    )
    missing_keys = [
        k for k in required_keys if not isinstance(parsed.get(k), str) or not parsed[k].strip()
    ]
    if missing_keys:
        raise GeminiMalformedResponseError(
            f"Missing required structured sections: {', '.join(missing_keys)}."
        )

    return StructuredAssistantSections(
        verified_data_summary=parsed["verified_data_summary"].strip(),
        forecast_context=parsed["forecast_context"].strip(),
        ai_interpretation=parsed["ai_interpretation"].strip(),
        general_health_guidance=parsed["general_health_guidance"].strip(),
        model_limitations_notice=parsed["model_limitations_notice"].strip(),
    )


def ask_airwise_assistant(
    request: AssistantRequest,
    *,
    settings: Settings | None = None,
    genai_client: genai.Client | None = None,
    http_client: httpx.Client | None = None,
) -> AssistantResponse:
    """Execute a grounded AIRWISE AI Gemini assistant query.

    1. Validates the requested location_id against the canonical location registry.
    2. Checks that backend Gemini credentials are configured (fails cleanly with 503 if not).
    3. Fetches verified Open-Meteo model data for the selected city (and all 4 cities for comparison).
    4. Invokes Gemini via `google-genai` SDK with strict anti-hallucination and non-medical rules.
    5. Returns structured sections + exact verified context + provenance and CAMS attribution.
    """
    location = get_location_by_id(request.location_id)
    if location is None:
        raise InvalidLocationError(request.location_id)

    cfg = settings or get_settings()
    if genai_client is None and not cfg.gemini_api_key:
        logger.warning(
            "gemini_assistant_unavailable location_id=%s mode=%s",
            location.id,
            request.mode,
        )
        raise GeminiNotConfiguredError()

    primary_aq, primary_snapshot = _fetch_verified_city_data(
        location, http_client=http_client
    )

    city_comparisons: list[VerifiedCitySnapshot] = []
    if request.mode == "city_comparison":
        for loc in AVAILABLE_LOCATIONS:
            if loc.id == location.id:
                city_comparisons.append(primary_snapshot)
            else:
                _, snap = _fetch_verified_city_data(loc, http_client=http_client)
                city_comparisons.append(snap)

    system_instruction = _build_system_instruction()
    user_prompt = _build_user_prompt(
        request=request,
        primary_aq=primary_aq,
        primary_snapshot=primary_snapshot,
        city_comparisons=city_comparisons,
    )

    client = genai_client or _create_genai_client(cfg)
    sections = _invoke_gemini(
        client=client,
        model=cfg.gemini_model,
        system_instruction=system_instruction,
        user_prompt=user_prompt,
        timeout_seconds=cfg.gemini_timeout_seconds,
    )

    provenance: DataProvenance | None = primary_aq.provenance if primary_aq is not None else None
    attribution: DataAttribution = (
        primary_aq.attribution if primary_aq is not None else DataAttribution()
    )

    return AssistantResponse(
        status="ok",
        mode=request.mode,
        model=cfg.gemini_model,
        location=location,
        question=request.question,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections=sections,
        verified_context=primary_snapshot,
        city_comparisons=city_comparisons,
        provenance=provenance,
        attribution=attribution,
    )
