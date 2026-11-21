"""Deterministic Predictive Intelligence & Risk Insights Engine (Phase 7).

Transforms authoritative Open-Meteo CAMS Global hourly forecasts (`fetch_open_meteo_air_quality`)
into reproducible, rule-based risk classifications, elevated-risk windows, single-hour spikes,
comparatively favorable windows, independent activity-planning guidance, provisional OLS trend
signals, transparent data-quality evidence, and honest deterministic daily summaries.

Zero AI generation, zero ML training, zero fabricated values, and zero numeric confidence scores.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any

from app.schemas.air_quality import AirQualityResponse, HourlyForecastPoint
from app.schemas.dashboard import AqiBand
from app.schemas.intelligence import (
    ActivityRecommendation,
    ActivityType,
    BetterWindow,
    BetterWindowResult,
    CandidateWindow,
    CategoryDistributionEntry,
    DailyIntelligenceSummary,
    DataQualityTier,
    ForecastDataQuality,
    HourlyRiskPoint,
    MetricTrendSignal,
    ModuleSufficiency,
    PollutantCoverageInfo,
    PredictiveIntelligenceResponse,
    RiskCategory,
    RiskWindow,
    RiskWindowEvaluationStatus,
    SingleHourSpike,
    TimestampContinuity,
    TrendSignal,
)
from app.services.open_meteo import (
    classify_us_aqi_band,
    fetch_open_meteo_air_quality,
    parse_aware_provider_datetime,
    resolve_timezone,
)


@dataclass(frozen=True)
class IntelligenceConfig:
    """Centralized internal constants and provisional MVP engineering heuristics."""

    expected_horizon_hours: int = 24

    # Risk Window rules (inclusive >= 101, minimum 2 consecutive hourly observations)
    risk_window_aqi_threshold: int = 101
    risk_window_min_consecutive_hours: int = 2

    # Better-Window Engine rules (decoupled from activity-specific rules)
    better_window_min_hours: int = 2
    better_window_max_hours: int = 4
    better_window_min_horizon_completeness_pct: float = 50.0
    better_window_default_max_aqi_ceiling: int = 150
    better_window_secondary_delta_aqi: float = 10.0
    better_window_secondary_max_aqi: int = 100

    # Provisional MVP Trend Engine engineering heuristics
    trend_min_valid_points: int = 6
    trend_min_span_hours: float = 6.0
    trend_aqi_min_net_change: float = 10.0
    trend_aqi_min_slope_per_hour: float = 0.4
    trend_pollutant_min_relative_change: float = 0.15
    trend_min_r_squared: float = 0.25

    # Activity Planner operational guidance rules (NOT medically validated exposure limits)
    exercise_min_hours: int = 2
    exercise_max_hours: int = 3
    exercise_max_aqi: int = 100

    errands_min_hours: int = 1
    errands_max_hours: int = 2
    errands_max_aqi: int = 150

    general_min_hours: int = 2
    general_max_hours: int = 4
    general_max_aqi: int = 150

    # Provisional qualitative data-quality tier boundaries
    quality_insufficient_min_hours: int = 6
    quality_insufficient_min_pct: float = 25.0
    quality_high_min_pct: float = 90.0
    quality_high_pollutant_min_pct: float = 80.0
    quality_moderate_min_pct: float = 70.0
    quality_moderate_max_gaps: int = 2


INTELLIGENCE_CONFIG = IntelligenceConfig()

POLLUTANT_NOISE_FLOORS: dict[str, float] = {
    "PM2.5": 3.0,
    "PM10": 6.0,
    "NO2": 4.0,
    "O3": 8.0,
    "SO2": 2.0,
}

_SEVERITY_RANKS: dict[RiskCategory, int] = {
    "Unavailable": 0,
    "Good": 1,
    "Moderate": 2,
    "Unhealthy for Sensitive Groups": 3,
    "Unhealthy": 4,
    "Very Unhealthy": 5,
    "Hazardous": 6,
}

_AQI_BAND_ORDER: tuple[AqiBand, ...] = (
    "Good",
    "Moderate",
    "Unhealthy for Sensitive Groups",
    "Unhealthy",
    "Very Unhealthy",
    "Hazardous",
)


@dataclass(frozen=True)
class _ParsedForecastPoint:
    """Internal chronologically parsed forecast hour with timezone-aware datetime."""

    point: HourlyForecastPoint
    local_dt: datetime
    utc_dt: datetime
    valid_aqi: int | None


# ============================================================================
# 1. Defensive AQI Validation & Risk Classification
# ============================================================================


def sanitize_aqi_value(raw_aqi: Any) -> int | None:
    """Validate US AQI strictly in [0, 500]; reject None, bool, negative, >500, or non-finite."""
    if raw_aqi is None or isinstance(raw_aqi, bool):
        return None
    if isinstance(raw_aqi, int):
        return raw_aqi if 0 <= raw_aqi <= 500 else None
    if isinstance(raw_aqi, float):
        if not math.isfinite(raw_aqi):
            return None
        rounded = int(round(raw_aqi))
        return rounded if 0 <= rounded <= 500 else None
    return None


def classify_aqi_risk(raw_aqi: Any) -> tuple[int | None, RiskCategory, int]:
    """Classify a single US AQI value into (valid_aqi, RiskCategory, severity_rank)."""
    valid = sanitize_aqi_value(raw_aqi)
    if valid is None:
        return None, "Unavailable", 0
    band = classify_us_aqi_band(valid)
    if band is None:
        return None, "Unavailable", 0
    return valid, band, _SEVERITY_RANKS[band]


def _parse_and_sort_forecast_points(
    points: list[HourlyForecastPoint],
    provider_tz: tzinfo,
) -> list[_ParsedForecastPoint]:
    """Parse forecast timestamps into timezone-aware datetimes and sort chronologically."""
    parsed: list[_ParsedForecastPoint] = []
    for pt in points:
        try:
            local_dt = parse_aware_provider_datetime(pt.time, provider_tz, field_name="forecast.time")
        except Exception:
            # Skip unparseable timestamps rather than inventing dates
            continue
        valid_aqi = sanitize_aqi_value(pt.us_aqi)
        parsed.append(
            _ParsedForecastPoint(
                point=pt,
                local_dt=local_dt,
                utc_dt=local_dt.astimezone(timezone.utc),
                valid_aqi=valid_aqi,
            )
        )
    parsed.sort(key=lambda item: item.utc_dt)
    return parsed


def _is_contiguous_next_hour(prev_pt: _ParsedForecastPoint, next_pt: _ParsedForecastPoint) -> bool:
    """Return True iff next_pt is exactly 1 hour after prev_pt in UTC time."""
    return (next_pt.utc_dt - prev_pt.utc_dt) == timedelta(hours=1)


def build_hourly_risk_timeline(
    parsed_points: list[_ParsedForecastPoint],
) -> list[HourlyRiskPoint]:
    """Classify every forecast hour deterministically."""
    timeline: list[HourlyRiskPoint] = []
    for item in parsed_points:
        valid_aqi, category, rank = classify_aqi_risk(item.valid_aqi)
        timeline.append(
            HourlyRiskPoint(
                time=item.point.time,
                us_aqi=valid_aqi,
                risk_category=category,
                severity_rank=rank,
            )
        )
    return timeline


# ============================================================================
# 2. Risk-Window Engine (with Single-Hour Spikes)
# ============================================================================


def detect_risk_windows(
    parsed_points: list[_ParsedForecastPoint],
    timezone_name: str,
    config: IntelligenceConfig = INTELLIGENCE_CONFIG,
) -> tuple[list[RiskWindow], list[SingleHourSpike], RiskWindowEvaluationStatus]:
    """Detect contiguous elevated-risk windows (us_aqi >= 101, duration >= 2h) and single-hour spikes.

    - Missing observations (`valid_aqi is None`), timestamp gaps (`Δt != 1h`), or lower-risk hours
      (`< 101`) terminate any active run immediately; runs are never merged across gaps.
    - `duration_hours` is explicitly `len(run)` (exact count of hourly observations included).
    - Midnight crossing is permitted and flagged via `crosses_midnight`.
    """
    # Check whether at least 2 contiguous valid observations exist anywhere in the horizon
    has_contiguous_valid_pair = any(
        parsed_points[i].valid_aqi is not None
        and parsed_points[i + 1].valid_aqi is not None
        and _is_contiguous_next_hour(parsed_points[i], parsed_points[i + 1])
        for i in range(len(parsed_points) - 1)
    )
    if not has_contiguous_valid_pair:
        # Still report isolated single-hour spikes if any single valid hour >= threshold exists
        spikes: list[SingleHourSpike] = []
        for item in parsed_points:
            if item.valid_aqi is not None and item.valid_aqi >= config.risk_window_aqi_threshold:
                band = classify_us_aqi_band(item.valid_aqi)
                if band is not None:
                    spikes.append(
                        SingleHourSpike(
                            time=item.point.time,
                            us_aqi=item.valid_aqi,
                            category=band,
                            timezone=timezone_name,
                        )
                    )
        return [], spikes, "insufficient_data"

    risk_windows: list[RiskWindow] = []
    single_spikes: list[SingleHourSpike] = []

    current_run: list[_ParsedForecastPoint] = []
    run_preceded_by_missing = False

    def _flush_run(followed_by_missing: bool) -> None:
        nonlocal current_run, run_preceded_by_missing
        if not current_run:
            return
        duration = len(current_run)
        if duration >= config.risk_window_min_consecutive_hours:
            aqis = [p.valid_aqi for p in current_run if p.valid_aqi is not None]
            peak_item = max(current_run, key=lambda p: p.valid_aqi if p.valid_aqi is not None else -1)
            peak_aqi = peak_item.valid_aqi or config.risk_window_aqi_threshold
            severity = classify_us_aqi_band(peak_aqi) or "Unhealthy for Sensitive Groups"
            first_item = current_run[0]
            last_item = current_run[-1]
            risk_windows.append(
                RiskWindow(
                    start_time=first_item.point.time,
                    end_time=last_item.point.time,
                    duration_hours=duration,
                    peak_aqi=peak_aqi,
                    peak_time=peak_item.point.time,
                    mean_aqi=round(sum(aqis) / len(aqis), 1),
                    severity_category=severity,
                    timezone=timezone_name,
                    crosses_midnight=first_item.local_dt.date() != last_item.local_dt.date(),
                    interrupted_by_missing_data=run_preceded_by_missing or followed_by_missing,
                )
            )
        else:
            only = current_run[0]
            if only.valid_aqi is not None:
                band = classify_us_aqi_band(only.valid_aqi)
                if band is not None:
                    single_spikes.append(
                        SingleHourSpike(
                            time=only.point.time,
                            us_aqi=only.valid_aqi,
                            category=band,
                            timezone=timezone_name,
                        )
                    )
        current_run = []
        run_preceded_by_missing = False

    for idx, item in enumerate(parsed_points):
        if item.valid_aqi is None:
            _flush_run(followed_by_missing=True)
            continue

        is_elevated = item.valid_aqi >= config.risk_window_aqi_threshold
        if not is_elevated:
            _flush_run(followed_by_missing=False)
            continue

        if not current_run:
            preceded_missing = idx > 0 and (
                parsed_points[idx - 1].valid_aqi is None
                or not _is_contiguous_next_hour(parsed_points[idx - 1], item)
            )
            current_run = [item]
            run_preceded_by_missing = preceded_missing
        else:
            if _is_contiguous_next_hour(current_run[-1], item):
                current_run.append(item)
            else:
                _flush_run(followed_by_missing=True)
                current_run = [item]
                run_preceded_by_missing = True

    _flush_run(followed_by_missing=False)
    return risk_windows, single_spikes, "evaluated"


# ============================================================================
# 3. Shared Candidate-Window Generator & Better-Window Engine
# ============================================================================


def generate_contiguous_windows(
    parsed_points: list[_ParsedForecastPoint],
    *,
    min_hours: int,
    max_hours: int,
    timezone_name: str,
) -> list[CandidateWindow]:
    """Generate all contiguous (`Δt == 1h`) candidate windows of length [min_hours, max_hours]
    where 100% of hours have valid non-null US AQI values.
    """
    if min_hours < 1 or max_hours < min_hours or not parsed_points:
        return []

    candidates: list[CandidateWindow] = []
    total = len(parsed_points)

    for start_idx in range(total):
        if parsed_points[start_idx].valid_aqi is None:
            continue

        for length in range(min_hours, max_hours + 1):
            end_idx = start_idx + length - 1
            if end_idx >= total:
                break

            window_slice = parsed_points[start_idx : end_idx + 1]
            # Validate 100% valid AQI and strict 1-hour contiguity
            is_valid = True
            for k, pt in enumerate(window_slice):
                if pt.valid_aqi is None:
                    is_valid = False
                    break
                if k > 0 and not _is_contiguous_next_hour(window_slice[k - 1], pt):
                    is_valid = False
                    break
            if not is_valid:
                # Extending length further from this start_idx will also fail
                break

            aqis = [pt.valid_aqi for pt in window_slice if pt.valid_aqi is not None]
            max_aqi = max(aqis)
            band = classify_us_aqi_band(max_aqi)
            if band is None:
                continue

            candidates.append(
                CandidateWindow(
                    start_time=window_slice[0].point.time,
                    end_time=window_slice[-1].point.time,
                    duration_hours=len(window_slice),
                    mean_aqi=round(sum(aqis) / len(aqis), 1),
                    min_aqi=min(aqis),
                    max_aqi=max_aqi,
                    category=band,
                    hourly_aqi_values=aqis,
                    timezone=timezone_name,
                    crosses_midnight=window_slice[0].local_dt.date()
                    != window_slice[-1].local_dt.date(),
                )
            )

    return candidates


def _windows_overlap(a: CandidateWindow, b: CandidateWindow, provider_tz: tzinfo) -> bool:
    """Return True if two candidate windows overlap or touch within the same hour."""
    a_start = parse_aware_provider_datetime(a.start_time, provider_tz).astimezone(timezone.utc)
    a_end = parse_aware_provider_datetime(a.end_time, provider_tz).astimezone(timezone.utc)
    b_start = parse_aware_provider_datetime(b.start_time, provider_tz).astimezone(timezone.utc)
    b_end = parse_aware_provider_datetime(b.end_time, provider_tz).astimezone(timezone.utc)
    return not (a_end < b_start or b_end < a_start)


def identify_better_windows(
    parsed_points: list[_ParsedForecastPoint],
    *,
    completeness_percent: float,
    timezone_name: str,
    provider_tz: tzinfo,
    config: IntelligenceConfig = INTELLIGENCE_CONFIG,
) -> BetterWindowResult:
    """Identify comparatively favorable contiguous 2-4h windows within the forecast horizon.

    Decoupled from activity-specific rules. Never claims a window is medically safe.
    """
    if completeness_percent < config.better_window_min_horizon_completeness_pct:
        return BetterWindowResult(
            status="insufficient_data",
            guardrail_max_aqi_ceiling=config.better_window_default_max_aqi_ceiling,
            windows=[],
            note=(
                f"Insufficient forecast completeness ({completeness_percent}% < "
                f"{config.better_window_min_horizon_completeness_pct:.0f}%) to identify comparatively favorable windows."
            ),
        )

    candidates = generate_contiguous_windows(
        parsed_points,
        min_hours=config.better_window_min_hours,
        max_hours=config.better_window_max_hours,
        timezone_name=timezone_name,
    )
    qualifying = [
        c for c in candidates if c.max_aqi <= config.better_window_default_max_aqi_ceiling
    ]
    if not qualifying:
        return BetterWindowResult(
            status="no_qualifying_window",
            guardrail_max_aqi_ceiling=config.better_window_default_max_aqi_ceiling,
            windows=[],
            note=(
                f"No contiguous {config.better_window_min_hours}-{config.better_window_max_hours}h window "
                f"remained at or below the general comparative ceiling of US AQI "
                f"{config.better_window_default_max_aqi_ceiling}."
            ),
        )

    # Deterministic ranking: lowest mean AQI, then lowest peak AQI, then longer duration, then earliest time
    qualifying.sort(
        key=lambda w: (w.mean_aqi, w.max_aqi, -w.duration_hours, w.start_time)
    )

    selected: list[BetterWindow] = []
    primary = qualifying[0]
    selected.append(
        BetterWindow(
            **primary.model_dump(),
            rationale=(
                f"Lowest {primary.duration_hours}-hour mean US AQI ({primary.mean_aqi}, "
                f"range {primary.min_aqi}-{primary.max_aqi}, {primary.category}) across available "
                f"contiguous forecast hours."
            ),
        )
    )

    # Optionally include 1 non-overlapping secondary comparative window
    for cand in qualifying[1:]:
        if (
            cand.mean_aqi <= primary.mean_aqi + config.better_window_secondary_delta_aqi
            and cand.max_aqi <= config.better_window_secondary_max_aqi
            and not _windows_overlap(primary, cand, provider_tz)
        ):
            selected.append(
                BetterWindow(
                    **cand.model_dump(),
                    rationale=(
                        f"Secondary non-overlapping {cand.duration_hours}-hour comparative window "
                        f"(mean US AQI {cand.mean_aqi}, range {cand.min_aqi}-{cand.max_aqi}, {cand.category})."
                    ),
                )
            )
            break

    return BetterWindowResult(
        status="windows_identified",
        guardrail_max_aqi_ceiling=config.better_window_default_max_aqi_ceiling,
        windows=selected,
        note=(
            f"Identified {len(selected)} comparatively lower-AQI forecast window(s) using actual "
            f"available CAMS Global forecast values (informational comparison only; not a medical safety guarantee)."
        ),
    )


# ============================================================================
# 4. Independent Activity Planning Engine
# ============================================================================


def build_activity_recommendations(
    parsed_points: list[_ParsedForecastPoint],
    *,
    completeness_percent: float,
    timezone_name: str,
    config: IntelligenceConfig = INTELLIGENCE_CONFIG,
) -> list[ActivityRecommendation]:
    """Independently evaluate candidate windows for each outdoor activity class.

    All thresholds are AIRWISE operational guidance rules, NOT medically validated exposure limits.
    """
    specs: list[tuple[ActivityType, str, int, int, int]] = [
        (
            "outdoor_exercise",
            "Outdoor Exercise",
            config.exercise_min_hours,
            config.exercise_max_hours,
            config.exercise_max_aqi,
        ),
        (
            "outdoor_errands",
            "Outdoor Errands",
            config.errands_min_hours,
            config.errands_max_hours,
            config.errands_max_aqi,
        ),
        (
            "general_outdoor",
            "General Outdoor Exposure",
            config.general_min_hours,
            config.general_max_hours,
            config.general_max_aqi,
        ),
    ]

    recommendations: list[ActivityRecommendation] = []
    insufficient = completeness_percent < config.better_window_min_horizon_completeness_pct

    for activity_type, label, min_h, max_h, max_aqi_rule in specs:
        rule_desc = (
            f"AIRWISE operational guidance rule (non-medical): contiguous {min_h}-{max_h}h forecast "
            f"window with all hourly US AQI <= {max_aqi_rule}."
        )
        if insufficient:
            recommendations.append(
                ActivityRecommendation(
                    activity_type=activity_type,
                    label=label,
                    status="insufficient_data",
                    operational_rule_description=rule_desc,
                    recommended_window=None,
                    rationale=(
                        f"Insufficient forecast completeness ({completeness_percent}%) to evaluate "
                        f"comparative windows for {label.lower()}."
                    ),
                )
            )
            continue

        candidates = generate_contiguous_windows(
            parsed_points,
            min_hours=min_h,
            max_hours=max_h,
            timezone_name=timezone_name,
        )
        qualifying = [c for c in candidates if c.max_aqi <= max_aqi_rule]
        if not qualifying:
            recommendations.append(
                ActivityRecommendation(
                    activity_type=activity_type,
                    label=label,
                    status="no_qualifying_window",
                    operational_rule_description=rule_desc,
                    recommended_window=None,
                    rationale=(
                        f"No contiguous {min_h}-{max_h}h forecast window met the operational rule "
                        f"(all hours US AQI <= {max_aqi_rule}). Consider postponing, shortening duration, "
                        f"or choosing indoor alternatives."
                    ),
                )
            )
            continue

        qualifying.sort(key=lambda w: (w.mean_aqi, w.max_aqi, -w.duration_hours, w.start_time))
        best = qualifying[0]
        recommendations.append(
            ActivityRecommendation(
                activity_type=activity_type,
                label=label,
                status="window_identified",
                operational_rule_description=rule_desc,
                recommended_window=best,
                rationale=(
                    f"Comparatively favorable {best.duration_hours}-hour window from {best.start_time} "
                    f"to {best.end_time} ({best.timezone}) with mean US AQI {best.mean_aqi} "
                    f"(range {best.min_aqi}-{best.max_aqi}, {best.category})."
                ),
            )
        )

    return recommendations


# ============================================================================
# 5. Trend Signal Engine (Provisional MVP Heuristics)
# ============================================================================


def compute_metric_trend(
    parsed_points: list[_ParsedForecastPoint],
    *,
    metric_name: str,
    unit: str,
    extractor: Any,
    config: IntelligenceConfig = INTELLIGENCE_CONFIG,
) -> MetricTrendSignal:
    """Compute an explainable OLS trend signal for one metric without zero-filling nulls."""
    valid_pairs: list[tuple[datetime, float]] = []
    for item in parsed_points:
        val = extractor(item)
        if val is not None and not isinstance(val, bool):
            fval = float(val)
            if math.isfinite(fval):
                valid_pairs.append((item.utc_dt, fval))

    n = len(valid_pairs)
    if n < config.trend_min_valid_points:
        return MetricTrendSignal(
            metric=metric_name,  # type: ignore[arg-type]
            unit=unit,
            signal="Insufficient data",
            valid_points=n,
            elapsed_span_hours=0.0,
            description=(
                f"Insufficient valid forecast points ({n} < {config.trend_min_valid_points} required) "
                f"to evaluate a directional trend for {metric_name}."
            ),
        )

    t0 = valid_pairs[0][0]
    xs = [(dt - t0).total_seconds() / 3600.0 for dt, _ in valid_pairs]
    ys = [val for _, val in valid_pairs]
    span_hours = round(xs[-1] - xs[0], 2)

    if span_hours < config.trend_min_span_hours:
        return MetricTrendSignal(
            metric=metric_name,  # type: ignore[arg-type]
            unit=unit,
            signal="Insufficient data",
            valid_points=n,
            elapsed_span_hours=span_hours,
            description=(
                f"Forecast time span ({span_hours}h < {config.trend_min_span_hours:.0f}h required) "
                f"is too short to classify a trend for {metric_name}."
            ),
        )

    y_min = min(ys)
    y_max = max(ys)
    if y_max - y_min == 0.0:
        return MetricTrendSignal(
            metric=metric_name,  # type: ignore[arg-type]
            unit=unit,
            signal="Stable",
            valid_points=n,
            elapsed_span_hours=span_hours,
            slope_per_hour=0.0,
            projected_net_change=0.0,
            r_squared=1.0,
            volatility_flag=False,
            description=f"{metric_name} remains constant at {ys[0]:.1f} {unit} across {n} forecast hours.",
        )

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    s_xx = sum((x - mean_x) ** 2 for x in xs)
    if s_xx == 0.0:
        return MetricTrendSignal(
            metric=metric_name,  # type: ignore[arg-type]
            unit=unit,
            signal="Insufficient data",
            valid_points=n,
            elapsed_span_hours=span_hours,
            description=f"Duplicate timestamps prevented trend calculation for {metric_name}.",
        )

    s_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = s_xy / s_xx
    intercept = mean_y - slope * mean_x

    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r_squared = max(0.0, min(1.0, 1.0 - (ss_res / ss_tot))) if ss_tot > 0.0 else 1.0

    net_change = slope * span_hours
    abs_change = abs(net_change)

    if metric_name == "us_aqi":
        exceeds_threshold = (
            abs_change >= config.trend_aqi_min_net_change
            and abs(slope) >= config.trend_aqi_min_slope_per_hour
        )
    else:
        noise_floor = POLLUTANT_NOISE_FLOORS.get(metric_name, 3.0)
        rel_change = (abs_change / mean_y) if mean_y > 0.0 else 0.0
        exceeds_threshold = (
            abs_change >= noise_floor
            and rel_change >= config.trend_pollutant_min_relative_change
        )

    signal: TrendSignal
    volatility_flag = False

    if exceeds_threshold:
        if r_squared < config.trend_min_r_squared:
            signal = "Stable"
            volatility_flag = True
            desc = (
                f"{metric_name} shows high hour-to-hour variability (provisional R²={r_squared:.2f} < "
                f"{config.trend_min_r_squared}) without a consistent directional trend."
            )
        elif net_change > 0:
            signal = "Rising"
            desc = (
                f"{metric_name} shows a rising model trend (+{net_change:.1f} {unit} projected over "
                f"{span_hours:.0f}h across {n} valid forecast hours)."
            )
        else:
            signal = "Falling"
            desc = (
                f"{metric_name} shows a falling model trend ({net_change:.1f} {unit} projected over "
                f"{span_hours:.0f}h across {n} valid forecast hours)."
            )
    else:
        signal = "Stable"
        desc = (
            f"{metric_name} remains broadly stable ({net_change:+.1f} {unit} projected change over "
            f"{span_hours:.0f}h, within provisional stability thresholds)."
        )

    return MetricTrendSignal(
        metric=metric_name,  # type: ignore[arg-type]
        unit=unit,
        signal=signal,
        valid_points=n,
        elapsed_span_hours=span_hours,
        slope_per_hour=round(slope, 3),
        projected_net_change=round(net_change, 2),
        r_squared=round(r_squared, 3),
        volatility_flag=volatility_flag,
        description=desc,
    )


def compute_all_trend_signals(
    parsed_points: list[_ParsedForecastPoint],
    units: Any,
    config: IntelligenceConfig = INTELLIGENCE_CONFIG,
) -> list[MetricTrendSignal]:
    """Compute independent trend signals for Forecast US AQI and all 5 pollutants."""
    metric_specs = [
        ("us_aqi", getattr(units, "us_aqi", "US AQI"), lambda p: p.valid_aqi),
        ("PM2.5", getattr(units, "pm2_5", "µg/m³"), lambda p: p.point.pm2_5),
        ("PM10", getattr(units, "pm10", "µg/m³"), lambda p: p.point.pm10),
        ("NO2", getattr(units, "nitrogen_dioxide", "µg/m³"), lambda p: p.point.no2),
        ("O3", getattr(units, "ozone", "µg/m³"), lambda p: p.point.o3),
        ("SO2", getattr(units, "sulphur_dioxide", "µg/m³"), lambda p: p.point.so2),
    ]
    return [
        compute_metric_trend(
            parsed_points,
            metric_name=name,
            unit=unit,
            extractor=extractor,
            config=config,
        )
        for name, unit, extractor in metric_specs
    ]


# ============================================================================
# 6. Transparent Data-Quality Evidence (No Numeric 0-100 Score)
# ============================================================================


def assess_forecast_data_quality(
    parsed_points: list[_ParsedForecastPoint],
    *,
    cache_hit: bool,
    risk_window_status: RiskWindowEvaluationStatus,
    better_window_status: str,
    trend_signals: list[MetricTrendSignal],
    config: IntelligenceConfig = INTELLIGENCE_CONFIG,
) -> ForecastDataQuality:
    """Assess forecast input completeness, timestamp continuity, and per-module sufficiency."""
    expected_hours = config.expected_horizon_hours
    valid_aqi_hours = sum(1 for p in parsed_points if p.valid_aqi is not None)
    missing_hours = max(0, expected_hours - valid_aqi_hours)
    completeness_pct = (
        round(min(100.0, (valid_aqi_hours / expected_hours) * 100.0), 1)
        if expected_hours > 0
        else 0.0
    )

    # Count timestamp gaps (> 1h) plus internal null AQI slots
    timestamp_gaps = 0
    for i in range(len(parsed_points) - 1):
        delta_hours = (parsed_points[i + 1].utc_dt - parsed_points[i].utc_dt).total_seconds() / 3600.0
        if delta_hours > 1.0:
            timestamp_gaps += max(1, int(round(delta_hours)) - 1)
    null_aqi_slots = sum(1 for p in parsed_points if p.valid_aqi is None)
    total_gap_count = timestamp_gaps + null_aqi_slots

    if valid_aqi_hours == 0:
        continuity: TimestampContinuity = "none"
    elif total_gap_count == 0:
        continuity = "continuous"
    elif total_gap_count <= config.quality_moderate_max_gaps:
        continuity = "minor_gaps"
    else:
        continuity = "major_gaps"

    pollutant_extractors = {
        "PM2.5": lambda p: p.point.pm2_5,
        "PM10": lambda p: p.point.pm10,
        "NO2": lambda p: p.point.no2,
        "O3": lambda p: p.point.o3,
        "SO2": lambda p: p.point.so2,
    }
    pollutant_coverage: dict[str, PollutantCoverageInfo] = {}
    for code, ext in pollutant_extractors.items():
        valid_p = sum(1 for p in parsed_points if ext(p) is not None)
        pct_p = round(min(100.0, (valid_p / expected_hours) * 100.0), 1) if expected_hours > 0 else 0.0
        pollutant_coverage[code] = PollutantCoverageInfo(
            valid_hours=valid_p,
            expected_hours=expected_hours,
            completeness_percent=pct_p,
        )

    all_pollutants_well_covered = all(
        info.completeness_percent >= config.quality_high_pollutant_min_pct
        for info in pollutant_coverage.values()
    )

    # Provisional qualitative tier classification (no arbitrary numeric score)
    tier: DataQualityTier
    if (
        valid_aqi_hours < config.quality_insufficient_min_hours
        or completeness_pct < config.quality_insufficient_min_pct
    ):
        tier = "Insufficient data"
    elif (
        completeness_pct >= config.quality_high_min_pct
        and total_gap_count == 0
        and all_pollutants_well_covered
    ):
        tier = "High"
    elif (
        completeness_pct >= config.quality_moderate_min_pct
        and total_gap_count <= config.quality_moderate_max_gaps
    ):
        tier = "Moderate"
    else:
        tier = "Limited"

    aqi_trend = next((t for t in trend_signals if t.metric == "us_aqi"), None)
    module_sufficiency = ModuleSufficiency(
        risk_windows="sufficient" if risk_window_status == "evaluated" else "insufficient_data",
        better_windows="sufficient" if better_window_status != "insufficient_data" else "insufficient_data",
        trend_signals="sufficient"
        if (aqi_trend is not None and aqi_trend.signal != "Insufficient data")
        else "insufficient_data",
        activity_planner="sufficient"
        if completeness_pct >= config.better_window_min_horizon_completeness_pct
        else "insufficient_data",
    )

    return ForecastDataQuality(
        tier=tier,
        valid_aqi_hours=valid_aqi_hours,
        expected_forecast_hours=expected_hours,
        completeness_percent=completeness_pct,
        missing_hours_count=missing_hours,
        timestamp_continuity=continuity,
        gap_count=total_gap_count,
        pollutant_coverage=pollutant_coverage,
        cache_hit=cache_hit,
        module_sufficiency=module_sufficiency,
    )


# ============================================================================
# 7. Deterministic Daily Intelligence Summary
# ============================================================================


def build_daily_intelligence_summary(
    *,
    location_name: str,
    timezone_name: str,
    parsed_points: list[_ParsedForecastPoint],
    risk_windows: list[RiskWindow],
    single_spikes: list[SingleHourSpike],
    risk_window_status: RiskWindowEvaluationStatus,
    better_windows: BetterWindowResult,
    data_quality: ForecastDataQuality,
) -> DailyIntelligenceSummary:
    """Assemble an honest, strictly deterministic daily forecast intelligence summary."""
    valid_points = [p for p in parsed_points if p.valid_aqi is not None]
    if not valid_points:
        return DailyIntelligenceSummary(
            peak_forecast_risk="Unavailable",
            peak_aqi=None,
            peak_time=None,
            mean_aqi=None,
            min_aqi=None,
            dominant_category="Unavailable",
            category_distribution=[],
            risk_window_evaluation_status="insufficient_data",
            risk_windows_count=0,
            single_hour_spikes_count=0,
            better_windows_count=0,
            forecast_completeness_percent=data_quality.completeness_percent,
            data_quality_tier=data_quality.tier,
            deterministic_summary=(
                f"Insufficient forecast data to evaluate Peak Forecast Risk or risk windows for "
                f"{location_name} ({timezone_name}). Zero valid forecast US AQI hours were available."
            ),
        )

    aqis = [p.valid_aqi for p in valid_points if p.valid_aqi is not None]
    peak_item = max(valid_points, key=lambda p: p.valid_aqi if p.valid_aqi is not None else -1)
    peak_aqi = peak_item.valid_aqi
    peak_time = peak_item.point.time
    mean_aqi = round(sum(aqis) / len(aqis), 1)
    min_aqi = min(aqis)
    _, peak_risk_category, _ = classify_aqi_risk(peak_aqi)

    counts: dict[AqiBand, int] = {}
    for val in aqis:
        band = classify_us_aqi_band(val)
        if band is not None:
            counts[band] = counts.get(band, 0) + 1

    distribution: list[CategoryDistributionEntry] = [
        CategoryDistributionEntry(
            category=band,
            hours=counts[band],
            percentage=round((counts[band] / len(aqis)) * 100.0, 1),
        )
        for band in _AQI_BAND_ORDER
        if band in counts
    ]
    dominant_category: RiskCategory = (
        max(distribution, key=lambda d: (d.hours, _SEVERITY_RANKS[d.category])).category
        if distribution
        else "Unavailable"
    )

    # Build strictly factual narrative distinguishing 0 detected windows vs insufficient data
    parts: list[str] = [
        f"Across {len(aqis)}/{data_quality.expected_forecast_hours} available forecast hours in "
        f"{location_name} ({timezone_name}), Peak Forecast Risk is {peak_risk_category} "
        f"(peak US AQI {peak_aqi} at {peak_time}; mean {mean_aqi}, minimum {min_aqi})."
    ]

    if risk_window_status == "insufficient_data":
        parts.append("Insufficient contiguous forecast data to evaluate elevated-risk windows.")
    elif risk_windows:
        top_win = max(risk_windows, key=lambda w: w.peak_aqi)
        parts.append(
            f"Detected {len(risk_windows)} elevated-risk window(s) (≥2 consecutive hours at US AQI ≥101), "
            f"peaking at {top_win.peak_aqi} between {top_win.start_time} and {top_win.end_time} "
            f"({top_win.duration_hours}h)."
        )
    else:
        parts.append(
            "No qualifying elevated-risk windows (≥2 consecutive hours at US AQI ≥101) were detected "
            "in the available forecast horizon."
        )
        if single_spikes:
            parts.append(
                f"{len(single_spikes)} isolated single-hour spike(s) reached US AQI ≥101."
            )

    if better_windows.windows:
        best = better_windows.windows[0]
        parts.append(
            f"Comparatively lower AQI is modeled from {best.start_time} to {best.end_time} "
            f"(mean US AQI {best.mean_aqi}, {best.category})."
        )

    parts.append(
        f"Forecast data-quality tier is {data_quality.tier} "
        f"({data_quality.completeness_percent}% completeness; measures input coverage, not forecast accuracy)."
    )

    return DailyIntelligenceSummary(
        peak_forecast_risk=peak_risk_category,
        peak_aqi=peak_aqi,
        peak_time=peak_time,
        mean_aqi=mean_aqi,
        min_aqi=min_aqi,
        dominant_category=dominant_category,
        category_distribution=distribution,
        risk_window_evaluation_status=risk_window_status,
        risk_windows_count=len(risk_windows),
        single_hour_spikes_count=len(single_spikes),
        better_windows_count=len(better_windows.windows),
        forecast_completeness_percent=data_quality.completeness_percent,
        data_quality_tier=data_quality.tier,
        deterministic_summary=" ".join(parts),
    )


# ============================================================================
# 8. Top-Level Orchestrator
# ============================================================================


def compute_predictive_intelligence_from_forecast(
    aq: AirQualityResponse,
    *,
    config: IntelligenceConfig = INTELLIGENCE_CONFIG,
    generated_at_iso: str | None = None,
) -> PredictiveIntelligenceResponse:
    """Run the complete deterministic Phase 7 analytical pipeline over an authoritative AirQualityResponse."""
    provider_tz = resolve_timezone(aq.timezone)
    parsed_points = _parse_and_sort_forecast_points(
        aq.hourly_forecast.points,
        provider_tz,
    )

    hourly_risk_timeline = build_hourly_risk_timeline(parsed_points)
    risk_windows, single_spikes, risk_window_status = detect_risk_windows(
        parsed_points,
        aq.timezone,
        config=config,
    )
    trend_signals = compute_all_trend_signals(
        parsed_points,
        aq.units,
        config=config,
    )

    # Pre-compute completeness percentage for better-window & activity-planner sufficiency gates
    valid_aqi_count = sum(1 for p in parsed_points if p.valid_aqi is not None)
    completeness_pct = (
        round(min(100.0, (valid_aqi_count / config.expected_horizon_hours) * 100.0), 1)
        if config.expected_horizon_hours > 0
        else 0.0
    )

    better_windows = identify_better_windows(
        parsed_points,
        completeness_percent=completeness_pct,
        timezone_name=aq.timezone,
        provider_tz=provider_tz,
        config=config,
    )
    activity_recommendations = build_activity_recommendations(
        parsed_points,
        completeness_percent=completeness_pct,
        timezone_name=aq.timezone,
        config=config,
    )
    data_quality = assess_forecast_data_quality(
        parsed_points,
        cache_hit=aq.provenance.cache_hit,
        risk_window_status=risk_window_status,
        better_window_status=better_windows.status,
        trend_signals=trend_signals,
        config=config,
    )
    daily_summary = build_daily_intelligence_summary(
        location_name=aq.location.display_name,
        timezone_name=aq.timezone,
        parsed_points=parsed_points,
        risk_windows=risk_windows,
        single_spikes=single_spikes,
        risk_window_status=risk_window_status,
        better_windows=better_windows,
        data_quality=data_quality,
    )

    now_iso = generated_at_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return PredictiveIntelligenceResponse(
        location=aq.location,
        observation_time=aq.observation_time,
        retrieval_time=aq.retrieval_time,
        generated_at=now_iso,
        timezone=aq.timezone,
        timezone_abbreviation=aq.timezone_abbreviation,
        horizon_hours=len(parsed_points),
        hourly_risk_timeline=hourly_risk_timeline,
        daily_summary=daily_summary,
        risk_windows=risk_windows,
        single_hour_spikes=single_spikes,
        better_windows=better_windows,
        trend_signals=trend_signals,
        activity_recommendations=activity_recommendations,
        data_quality=data_quality,
        provenance=aq.provenance,
        attribution=aq.attribution,
    )


def fetch_predictive_intelligence(
    location_id: str = "lagos-ng",
    *,
    config: IntelligenceConfig = INTELLIGENCE_CONFIG,
) -> PredictiveIntelligenceResponse:
    """Fetch authoritative Open-Meteo forecast for `location_id` and compute deterministic intelligence."""
    aq = fetch_open_meteo_air_quality(location_id=location_id)
    return compute_predictive_intelligence_from_forecast(aq, config=config)
