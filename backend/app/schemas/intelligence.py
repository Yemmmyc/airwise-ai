"""Pydantic v2 response schemas for Phase 7: Deterministic Predictive Intelligence & Risk Insights.

All outputs are strictly deterministic analytical interpretations derived from verified
Open-Meteo CAMS Global hourly forecast inputs. Zero AI generation, zero fabricated values,
and zero numeric 0-100 confidence scores.
"""

from typing import Literal
from pydantic import BaseModel, Field

from app.schemas.air_quality import DataAttribution, DataProvenance
from app.schemas.dashboard import AqiBand, LocationOption


RiskCategory = Literal[
    "Good",
    "Moderate",
    "Unhealthy for Sensitive Groups",
    "Unhealthy",
    "Very Unhealthy",
    "Hazardous",
    "Unavailable",
]
TrendSignal = Literal["Rising", "Stable", "Falling", "Insufficient data"]
DataQualityTier = Literal["High", "Moderate", "Limited", "Insufficient data"]
TimestampContinuity = Literal["continuous", "minor_gaps", "major_gaps", "none"]
ModuleSufficiencyStatus = Literal["sufficient", "insufficient_data"]
ActivityType = Literal["outdoor_exercise", "outdoor_errands", "general_outdoor"]
ActivityRecommendationStatus = Literal[
    "window_identified",
    "no_qualifying_window",
    "insufficient_data",
]
RiskWindowEvaluationStatus = Literal["evaluated", "insufficient_data"]
BetterWindowStatus = Literal["windows_identified", "no_qualifying_window", "insufficient_data"]


class HourlyRiskPoint(BaseModel):
    """Deterministic US EPA AQI risk classification for a single future forecast hour."""

    time: str = Field(..., description="Forecast hour local ISO-8601 timestamp")
    us_aqi: int | None = Field(default=None, description="Verified US AQI value or None if unavailable")
    risk_category: RiskCategory = Field(..., description="US EPA AQI category or 'Unavailable'")
    severity_rank: int = Field(
        ...,
        ge=0,
        le=6,
        description="Deterministic rank: 0=Unavailable, 1=Good .. 6=Hazardous",
    )


class CategoryDistributionEntry(BaseModel):
    """Hour count and percentage for one US EPA AQI category across valid forecast hours."""

    category: AqiBand
    hours: int = Field(..., ge=0)
    percentage: float = Field(..., ge=0.0, le=100.0)


class RiskWindow(BaseModel):
    """Elevated-risk contiguous forecast window (>= 2 consecutive hourly observations at US AQI >= 101)."""

    start_time: str = Field(..., description="Local timestamp of the first elevated hour in the window")
    end_time: str = Field(..., description="Local timestamp of the last elevated hour in the window")
    duration_hours: int = Field(
        ...,
        ge=2,
        description="Exact count of contiguous hourly observations included in the window",
    )
    peak_aqi: int = Field(..., ge=101, le=500, description="Maximum US AQI observed within the window")
    peak_time: str = Field(..., description="Local timestamp of peak_aqi within the window")
    mean_aqi: float = Field(..., ge=101.0, le=500.0, description="Mean US AQI across window observations")
    severity_category: AqiBand = Field(..., description="US EPA category corresponding to peak_aqi")
    timezone: str = Field(..., description="IANA timezone of start_time, end_time, and peak_time")
    crosses_midnight: bool = Field(
        ...,
        description="True when start_time and end_time fall on different local calendar dates",
    )
    interrupted_by_missing_data: bool = Field(
        default=False,
        description="True when this window immediately preceded or followed a missing/null observation",
    )


class SingleHourSpike(BaseModel):
    """Isolated single elevated forecast hour (US AQI >= 101) that did not meet the 2-hour window minimum."""

    time: str = Field(..., description="Local timestamp of the isolated elevated hour")
    us_aqi: int = Field(..., ge=101, le=500)
    category: AqiBand
    timezone: str


class CandidateWindow(BaseModel):
    """Contiguous forecast window with 100% valid AQI observations."""

    start_time: str
    end_time: str
    duration_hours: int = Field(
        ...,
        ge=1,
        description="Exact count of contiguous hourly observations included in the window",
    )
    mean_aqi: float = Field(..., ge=0.0, le=500.0)
    min_aqi: int = Field(..., ge=0, le=500)
    max_aqi: int = Field(..., ge=0, le=500)
    category: AqiBand = Field(..., description="US EPA band of max_aqi within the window")
    hourly_aqi_values: list[int] = Field(
        ...,
        description="Exact chronological US AQI values for each hour in the window",
    )
    timezone: str
    crosses_midnight: bool


class BetterWindow(CandidateWindow):
    """Comparatively favorable contiguous forecast window (never described as medically safe)."""

    rationale: str = Field(
        ...,
        description="Transparent deterministic explanation of why this window was ranked favorably",
    )


class BetterWindowResult(BaseModel):
    """Output of the independent Better-Window Engine."""

    status: BetterWindowStatus
    guardrail_max_aqi_ceiling: int = Field(
        ...,
        description="Configurable general comparative ceiling used by the Better-Window Engine",
    )
    windows: list[BetterWindow] = Field(default_factory=list)
    note: str = Field(..., description="Transparent explanation of selection or why no window qualified")


class MetricTrendSignal(BaseModel):
    """Independent deterministic trend signal for forecast US AQI or one atmospheric pollutant."""

    metric: Literal["us_aqi", "PM2.5", "PM10", "NO2", "O3", "SO2"]
    unit: str
    signal: TrendSignal
    valid_points: int = Field(..., ge=0)
    elapsed_span_hours: float = Field(..., ge=0.0)
    slope_per_hour: float | None = None
    projected_net_change: float | None = None
    r_squared: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Provisional linearity/noise-suppression heuristic only (NOT forecast accuracy)",
    )
    volatility_flag: bool = Field(
        default=False,
        description="True when net change exceeded threshold but high variability suppressed directional signal",
    )
    description: str = Field(..., description="Plain-language deterministic summary of the signal")
    heuristic_note: str = Field(
        default="Classified using provisional MVP engineering heuristics (not empirically calibrated forecast accuracy).",
    )


class ActivityRecommendation(BaseModel):
    """Independent comparative operational guidance for one general outdoor activity type."""

    activity_type: ActivityType
    label: str
    status: ActivityRecommendationStatus
    operational_rule_description: str = Field(
        ...,
        description="Explicit AIRWISE operational rule (duration and ceiling; not a medically validated exposure limit)",
    )
    recommended_window: CandidateWindow | None = None
    rationale: str = Field(
        ...,
        description="Comparative explanation of why this window was selected or why none qualified",
    )
    is_medical_advice: Literal[False] = Field(default=False)
    disclaimer: str = Field(
        default=(
            "Comparative informational guidance based on AIRWISE operational heuristics and CAMS Global "
            "(~45 km grid) forecast estimates. Not medical advice, not a diagnosis, and does not guarantee "
            "street-level or personal safety."
        ),
    )


class PollutantCoverageInfo(BaseModel):
    """Non-null forecast coverage for an individual pollutant."""

    valid_hours: int = Field(..., ge=0)
    expected_hours: int = Field(..., ge=0)
    completeness_percent: float = Field(..., ge=0.0, le=100.0)


class ModuleSufficiency(BaseModel):
    """Analytical sufficiency evaluated independently per intelligence module."""

    risk_windows: ModuleSufficiencyStatus
    better_windows: ModuleSufficiencyStatus
    trend_signals: ModuleSufficiencyStatus
    activity_planner: ModuleSufficiencyStatus


class ForecastDataQuality(BaseModel):
    """Transparent forecast input data-quality evidence (no arbitrary 0-100 numeric score)."""

    tier: DataQualityTier = Field(
        ...,
        description="Qualitative data-quality tier: High, Moderate, Limited, or Insufficient data",
    )
    valid_aqi_hours: int = Field(..., ge=0)
    expected_forecast_hours: int = Field(..., ge=0)
    completeness_percent: float = Field(..., ge=0.0, le=100.0)
    missing_hours_count: int = Field(..., ge=0)
    timestamp_continuity: TimestampContinuity
    gap_count: int = Field(..., ge=0, description="Number of timestamp gaps (> 1h) or missing AQI slots")
    pollutant_coverage: dict[str, PollutantCoverageInfo] = Field(default_factory=dict)
    cache_hit: bool = Field(..., description="Whether underlying Open-Meteo forecast came from the 300s live cache")
    source_provider: str = Field(default="Open-Meteo Air Quality API (CAMS Global)")
    module_sufficiency: ModuleSufficiency
    disclosure: str = Field(
        default=(
            "Data-quality tiers reflect available forecast input completeness and timestamp continuity only; "
            "they do not measure statistical forecast accuracy."
        ),
    )


class DailyIntelligenceSummary(BaseModel):
    """Deterministic daily forecast risk summary anchored on Peak Forecast Risk."""

    peak_forecast_risk: RiskCategory = Field(
        ...,
        description="Peak Forecast Risk category derived from maximum hourly forecast US AQI (does not imply uniform all-day risk)",
    )
    peak_aqi: int | None = Field(default=None, ge=0, le=500)
    peak_time: str | None = Field(default=None, description="Local timestamp of peak_aqi")
    mean_aqi: float | None = Field(default=None, ge=0.0, le=500.0)
    min_aqi: int | None = Field(default=None, ge=0, le=500)
    dominant_category: RiskCategory = Field(
        ...,
        description="Most frequent US EPA category across valid forecast hours (or 'Unavailable')",
    )
    category_distribution: list[CategoryDistributionEntry] = Field(default_factory=list)
    risk_window_evaluation_status: RiskWindowEvaluationStatus
    risk_windows_count: int = Field(..., ge=0)
    single_hour_spikes_count: int = Field(..., ge=0)
    better_windows_count: int = Field(..., ge=0)
    forecast_completeness_percent: float = Field(..., ge=0.0, le=100.0)
    data_quality_tier: DataQualityTier
    deterministic_summary: str = Field(
        ...,
        description="Concise deterministic narrative built strictly from actual computed fields",
    )


class PredictiveIntelligenceResponse(BaseModel):
    """Top-level response contract for GET /api/v1/air-quality/intelligence."""

    location: LocationOption
    provider: str = Field(default="Open-Meteo Air Quality API (CAMS Global)")
    data_mode: Literal["predictive_intelligence"] = Field(default="predictive_intelligence")
    data_label: Literal["ANALYTICAL INTERPRETATION — BASED ON OPEN-METEO CAMS GLOBAL FORECAST"] = Field(
        default="ANALYTICAL INTERPRETATION — BASED ON OPEN-METEO CAMS GLOBAL FORECAST",
    )
    observation_time: str = Field(
        ...,
        description="Provider current model observation timestamp from the authoritative forecast call",
    )
    retrieval_time: str = Field(
        ...,
        description="ISO-8601 UTC retrieval timestamp of the underlying Open-Meteo forecast",
    )
    generated_at: str = Field(
        ...,
        description="ISO-8601 UTC timestamp when deterministic intelligence was computed",
    )
    timezone: str
    timezone_abbreviation: str | None = None
    horizon_hours: int = Field(..., ge=0, description="Number of future forecast hours evaluated")
    hourly_risk_timeline: list[HourlyRiskPoint] = Field(default_factory=list)
    daily_summary: DailyIntelligenceSummary
    risk_windows: list[RiskWindow] = Field(default_factory=list)
    single_hour_spikes: list[SingleHourSpike] = Field(default_factory=list)
    better_windows: BetterWindowResult
    trend_signals: list[MetricTrendSignal] = Field(default_factory=list)
    activity_recommendations: list[ActivityRecommendation] = Field(default_factory=list)
    data_quality: ForecastDataQuality
    provenance: DataProvenance
    attribution: DataAttribution = Field(default_factory=DataAttribution)
    is_demo_data: Literal[False] = Field(default=False)
    is_ai_generated: Literal[False] = Field(default=False)
    disclaimer: str = Field(
        default=(
            "ANALYTICAL INTERPRETATION — BASED ON OPEN-METEO CAMS GLOBAL FORECAST: All risk classifications, "
            "windows, trend signals, and activity guidance are deterministic rule-based interpretations of "
            "Open-Meteo CAMS Global atmospheric model forecasts (~0.4° / ~45 km spatial resolution, 3-hourly "
            "native model output interpolated to 1-hourly API timestamps). AIRWISE AI has not trained a new "
            "atmospheric forecasting model. Outputs are not physical roadside sensor measurements, do not "
            "imply causal explanations, and are not medical advice or guarantees of safety."
        ),
    )
