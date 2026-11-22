import type { Page, Route } from "@playwright/test";
import type {
  AirQualityResponse,
  AirQualityUnits,
  AssistantResponse,
  AssistantStatusResponse,
  DashboardResponse,
  DataAttribution,
  DataProvenance,
  HealthResponse,
  HistoricalAirQualityResponse,
  HistoricalCityComparisonResponse,
  HistoricalRangeDays,
  LocationOption,
  PredictiveIntelligenceResponse,
} from "../../src/types/dashboard";

/**
 * 1x1 transparent PNG used to stub Leaflet CARTO basemap tiles so browser QA
 * runs 100% offline and deterministically without external tile requests.
 */
const TRANSPARENT_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";
const TRANSPARENT_PNG_BUFFER = Buffer.from(TRANSPARENT_PNG_BASE64, "base64");

export const CANONICAL_LOCATIONS: Record<string, LocationOption> = {
  "lagos-ng": {
    id: "lagos-ng",
    city: "Lagos",
    region: "Lagos State",
    country: "Nigeria",
    display_name: "Lagos, Nigeria",
    latitude: 6.5244,
    longitude: 3.3792,
    timezone: "Africa/Lagos",
  },
  "abuja-ng": {
    id: "abuja-ng",
    city: "Abuja",
    region: "FCT",
    country: "Nigeria",
    display_name: "Abuja, Nigeria",
    latitude: 9.0765,
    longitude: 7.3986,
    timezone: "Africa/Lagos",
  },
  "nairobi-ke": {
    id: "nairobi-ke",
    city: "Nairobi",
    region: "Nairobi County",
    country: "Kenya",
    display_name: "Nairobi, Kenya",
    latitude: -1.2921,
    longitude: 36.8219,
    timezone: "Africa/Nairobi",
  },
  "accra-gh": {
    id: "accra-gh",
    city: "Accra",
    region: "Greater Accra",
    country: "Ghana",
    display_name: "Accra, Ghana",
    latitude: 5.6037,
    longitude: -0.187,
    timezone: "Africa/Accra",
  },
};

const DEFAULT_UNITS: AirQualityUnits = {
  us_aqi: "US AQI",
  pm2_5: "µg/m³",
  pm10: "µg/m³",
  nitrogen_dioxide: "µg/m³",
  ozone: "µg/m³",
  sulphur_dioxide: "µg/m³",
};

const DEFAULT_ATTRIBUTION: DataAttribution = {
  provider_attribution: "Air quality data by Open-Meteo.com (CC BY 4.0)",
  cams_attribution:
    "Contains modified Copernicus Atmosphere Monitoring Service (CAMS) information",
  sources: ["Open-Meteo Air Quality API", "Copernicus CAMS Global"],
};

function getLocation(locationId: string): LocationOption {
  return CANONICAL_LOCATIONS[locationId] ?? CANONICAL_LOCATIONS["lagos-ng"];
}

function buildProvenance(
  location: LocationOption,
  cacheHit = false
): DataProvenance {
  return {
    data_label: "LIVE PROVIDER DATA — MODEL-BASED ESTIMATE",
    provider_name: "Open-Meteo Air Quality API",
    endpoint_url: "https://air-quality-api.open-meteo.com/v1/air-quality",
    model_domain: "CAMS Global",
    spatial_resolution: "~40 km (0.4°)",
    source_temporal_resolution: "3-hourly CAMS Global interpolated to hourly",
    api_timestamp_interval: "1 hour",
    forecast_availability: "Up to 5 days",
    model_metadata: {
      domain: "CAMS Global",
      spatial_resolution: "~40 km (0.4°)",
      source_temporal_resolution: "3-hourly CAMS Global interpolated to hourly",
      api_timestamp_interval: "1 hour",
      forecast_availability: "Up to 5 days",
    },
    attribution: DEFAULT_ATTRIBUTION,
    methodology:
      "Gridded atmospheric composition model estimate; not a physical ground monitoring station.",
    is_physical_station_measurement: false,
    is_demo_data: false,
    cache_hit: cacheHit,
    provider_latitude: location.latitude,
    provider_longitude: location.longitude,
  };
}

export function buildMockHealthResponse(
  overrides: Partial<HealthResponse> = {}
): HealthResponse {
  return {
    status: "ok",
    service: "airwise-ai-backend",
    version: "0.7.0",
    environment: "local",
    data_mode: "demo",
    live_provider_connected: true,
    ...overrides,
  };
}

export function buildMockAirQualityResponse(
  locationId = "lagos-ng",
  overrides: Partial<AirQualityResponse> = {}
): AirQualityResponse {
  const location = getLocation(locationId);
  const baseAqiByCity: Record<string, number> = {
    "lagos-ng": 78,
    "abuja-ng": 62,
    "nairobi-ke": 44,
    "accra-gh": 56,
  };
  const baseAqi = baseAqiByCity[location.id] ?? 78;
  const band = baseAqi <= 50 ? "Good" : "Moderate";

  const forecastPoints = Array.from({ length: 24 }, (_, idx) => {
    const hour = String(idx).padStart(2, "0");
    return {
      classification: "hourly_forecast" as const,
      time: `2026-11-21T${hour}:00`,
      us_aqi: baseAqi + (idx % 6) * 5,
      pm2_5: 22.4 + (idx % 5) * 1.5,
      pm10: 48.2 + (idx % 5) * 2.0,
      no2: 18.5 + (idx % 4) * 1.2,
      o3: 54.0 + (idx % 6) * 3.0,
      so2: 6.4 + (idx % 3) * 0.5,
    };
  });

  const currentPoint = {
    classification: "current_model" as const,
    time: "2026-11-21T12:00",
    us_aqi: baseAqi,
    pm2_5: 24.8,
    pm10: 51.3,
    no2: 19.2,
    o3: 58.6,
    so2: 6.8,
  };

  return {
    location,
    provider: "Open-Meteo (CAMS Global)",
    data_mode: "live_model",
    data_label: "LIVE PROVIDER DATA — MODEL-BASED ESTIMATE",
    observation_time: "2026-11-21T12:00",
    retrieval_time: "2026-11-21T12:05:00Z",
    timezone: location.timezone,
    timezone_abbreviation: location.id === "nairobi-ke" ? "EAT" : location.id === "accra-gh" ? "GMT" : "WAT",
    aqi: {
      value: baseAqi,
      standard: "US EPA AQI (Open-Meteo Model Output)",
      unit: "US AQI",
      band,
      status: "available",
    },
    pm2_5: {
      code: "PM2.5",
      parameter: "pm2_5",
      name: "Fine Particulate Matter (PM2.5)",
      value: 24.8,
      unit: "µg/m³",
      status: "available",
    },
    pm10: {
      code: "PM10",
      parameter: "pm10",
      name: "Coarse Particulate Matter (PM10)",
      value: 51.3,
      unit: "µg/m³",
      status: "available",
    },
    no2: {
      code: "NO2",
      parameter: "nitrogen_dioxide",
      name: "Nitrogen Dioxide (NO2)",
      value: 19.2,
      unit: "µg/m³",
      status: "available",
    },
    o3: {
      code: "O3",
      parameter: "ozone",
      name: "Ozone (O3)",
      value: 58.6,
      unit: "µg/m³",
      status: "available",
    },
    so2: {
      code: "SO2",
      parameter: "sulphur_dioxide",
      name: "Sulphur Dioxide (SO2)",
      value: 6.8,
      unit: "µg/m³",
      status: "available",
    },
    units: DEFAULT_UNITS,
    current_conditions: {
      classification: "current_model",
      observation_time: "2026-11-21T12:00",
      interval_seconds: 3600,
      aqi: {
        value: baseAqi,
        standard: "US EPA AQI (Open-Meteo Model Output)",
        unit: "US AQI",
        band,
        status: "available",
      },
      pm2_5: {
        code: "PM2.5",
        parameter: "pm2_5",
        name: "Fine Particulate Matter (PM2.5)",
        value: 24.8,
        unit: "µg/m³",
        status: "available",
      },
      pm10: {
        code: "PM10",
        parameter: "pm10",
        name: "Coarse Particulate Matter (PM10)",
        value: 51.3,
        unit: "µg/m³",
        status: "available",
      },
      no2: {
        code: "NO2",
        parameter: "nitrogen_dioxide",
        name: "Nitrogen Dioxide (NO2)",
        value: 19.2,
        unit: "µg/m³",
        status: "available",
      },
      o3: {
        code: "O3",
        parameter: "ozone",
        name: "Ozone (O3)",
        value: 58.6,
        unit: "µg/m³",
        status: "available",
      },
      so2: {
        code: "SO2",
        parameter: "sulphur_dioxide",
        name: "Sulphur Dioxide (SO2)",
        value: 6.8,
        unit: "µg/m³",
        status: "available",
      },
    },
    hourly_forecast: {
      classification: "hourly_forecast",
      hours_returned: forecastPoints.length,
      points: forecastPoints,
      historical_hours_count: 0,
      historical_points: [],
      current_hour_point: currentPoint,
    },
    hourly_timeline: [currentPoint, ...forecastPoints],
    provenance: buildProvenance(location),
    attribution: DEFAULT_ATTRIBUTION,
    disclaimer:
      "Model-based estimate from Open-Meteo CAMS Global (~40 km resolution). Not a ground-station measurement or medical advice.",
    ...overrides,
  };
}

export function buildMockHistoricalResponse(
  locationId = "lagos-ng",
  days: HistoricalRangeDays = 7,
  overrides: Partial<HistoricalAirQualityResponse> = {}
): HistoricalAirQualityResponse {
  const location = getLocation(locationId);
  const dailySummaries = Array.from({ length: days }, (_, idx) => {
    const dayNum = String(14 + idx).padStart(2, "0");
    const dateStr = `2026-11-${dayNum}`;
    const avgAqi = 68 + (idx % 5) * 4;
    return {
      date: dateStr,
      timezone: location.timezone,
      avg_us_aqi: avgAqi,
      max_us_aqi: avgAqi + 16,
      min_us_aqi: avgAqi - 12,
      dominant_aqi_band: "Moderate" as const,
      avg_pm2_5: 21.5 + (idx % 4),
      max_pm2_5: 31.2 + (idx % 4),
      avg_pm10: 46.0 + (idx % 5),
      avg_no2: 17.8,
      avg_o3: 55.2,
      avg_so2: 6.1,
      valid_hours: 24,
      expected_hours: 24,
      missing_hours: 0,
      completeness_percent: 100,
    };
  });

  const hourlyRecords = Array.from({ length: 24 }, (_, idx) => {
    const hour = String(idx).padStart(2, "0");
    return {
      classification: "historical_model" as const,
      timestamp_utc: `2026-11-20T${hour}:00:00Z`,
      local_time: `2026-11-20T${hour}:00`,
      timezone: location.timezone,
      us_aqi: 70 + (idx % 6) * 3,
      pm2_5: 22.0 + (idx % 4),
      pm10: 47.5 + (idx % 5),
      no2: 18.0,
      o3: 56.0,
      so2: 6.2,
      source: "Open-Meteo CAMS Global",
      model_domain: "CAMS Global",
      retrieval_time: "2026-11-21T12:05:00Z",
    };
  });

  return {
    location,
    provider: "Open-Meteo (CAMS Global)",
    data_mode: "historical_model",
    data_label: "HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE",
    range_days: days,
    start_date: dailySummaries[0].date,
    end_date: dailySummaries[dailySummaries.length - 1].date,
    timezone: location.timezone,
    retrieval_time: "2026-11-21T12:05:00Z",
    units: DEFAULT_UNITS,
    hourly_records: hourlyRecords,
    daily_summaries: dailySummaries,
    period_summary: {
      days_requested: days,
      days_with_data: days,
      total_valid_hours: days * 24,
      total_expected_hours: days * 24,
      total_missing_hours: 0,
      completeness_percent: 100,
      avg_us_aqi: 74,
      max_us_aqi: 96,
      min_us_aqi: 56,
      peak_aqi_timestamp: `${dailySummaries[dailySummaries.length - 1].date}T15:00`,
      avg_pm2_5: 23.1,
      max_pm2_5: 34.2,
      avg_pm10: 48.0,
      avg_no2: 17.8,
      avg_o3: 55.2,
      avg_so2: 6.1,
      days_by_aqi_band: { Moderate: days },
    },
    data_completeness_percent: 100,
    origin: {
      storage_origin: "persisted_database_records",
      cache_hit: true,
      served_from_persistence: true,
      persisted_to_database: true,
      fallback_reason: null,
    },
    provenance: buildProvenance(location, true),
    attribution: DEFAULT_ATTRIBUTION,
    is_demo_data: false,
    disclaimer:
      "Historical model estimates persisted locally from Open-Meteo CAMS Global. Not ground-station measurements.",
    ...overrides,
  };
}

export function buildMockHistoricalComparisonResponse(
  days: HistoricalRangeDays = 7,
  overrides: Partial<HistoricalCityComparisonResponse> = {}
): HistoricalCityComparisonResponse {
  const cities = Object.keys(CANONICAL_LOCATIONS).map((id) => {
    const hist = buildMockHistoricalResponse(id, days);
    return {
      location: hist.location,
      status: "available" as const,
      data_label: hist.data_label,
      retrieval_time: hist.retrieval_time,
      origin: hist.origin,
      period_summary: hist.period_summary,
      daily_summaries: hist.daily_summaries,
      error_code: null,
      error_message: null,
      is_demo_data: false as const,
    };
  });

  return {
    range_days: days,
    data_mode: "historical_model",
    data_label: "HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE",
    generated_at: "2026-11-21T12:05:00Z",
    cities_available: cities.length,
    cities_unavailable: 0,
    cities,
    units: DEFAULT_UNITS,
    attribution: DEFAULT_ATTRIBUTION,
    is_demo_data: false,
    disclaimer:
      "Multi-city comparison derived from persisted Open-Meteo CAMS Global model estimates.",
    ...overrides,
  };
}

export function buildMockPredictiveIntelligenceResponse(
  locationId = "lagos-ng",
  overrides: Partial<PredictiveIntelligenceResponse> = {}
): PredictiveIntelligenceResponse {
  const location = getLocation(locationId);
  const hourlyRiskTimeline = Array.from({ length: 24 }, (_, idx) => {
    const hour = String(idx).padStart(2, "0");
    const usAqi = idx >= 14 && idx <= 16 ? 112 + (idx - 14) * 4 : 68 + (idx % 4) * 5;
    const isUsg = usAqi >= 101;
    return {
      time: `2026-11-21T${hour}:00`,
      us_aqi: usAqi,
      risk_category: isUsg
        ? ("Unhealthy for Sensitive Groups" as const)
        : ("Moderate" as const),
      severity_rank: isUsg ? 3 : 2,
    };
  });

  return {
    location,
    provider: "Open-Meteo (CAMS Global)",
    data_mode: "predictive_intelligence",
    data_label:
      "ANALYTICAL INTERPRETATION — BASED ON OPEN-METEO CAMS GLOBAL FORECAST",
    observation_time: "2026-11-21T12:00",
    retrieval_time: "2026-11-21T12:05:00Z",
    generated_at: "2026-11-21T12:05:01Z",
    timezone: location.timezone,
    timezone_abbreviation: location.id === "nairobi-ke" ? "EAT" : location.id === "accra-gh" ? "GMT" : "WAT",
    horizon_hours: 24,
    hourly_risk_timeline: hourlyRiskTimeline,
    daily_summary: {
      peak_forecast_risk: "Unhealthy for Sensitive Groups",
      peak_aqi: 120,
      peak_time: "2026-11-21T16:00",
      mean_aqi: 81.5,
      min_aqi: 68,
      dominant_category: "Moderate",
      category_distribution: [
        { category: "Moderate", hours: 21, percentage: 87.5 },
        {
          category: "Unhealthy for Sensitive Groups",
          hours: 3,
          percentage: 12.5,
        },
      ],
      risk_window_evaluation_status: "evaluated",
      risk_windows_count: 1,
      single_hour_spikes_count: 1,
      better_windows_count: 1,
      forecast_completeness_percent: 100,
      data_quality_tier: "High",
      deterministic_summary: `Peak forecast risk in ${location.display_name} reaches Unhealthy for Sensitive Groups (US AQI 120) around 16:00 local time, with predominantly Moderate conditions across the 24-hour horizon.`,
    },
    risk_windows: [
      {
        start_time: "2026-11-21T14:00",
        end_time: "2026-11-21T16:00",
        duration_hours: 3,
        peak_aqi: 120,
        peak_time: "2026-11-21T16:00",
        mean_aqi: 116,
        severity_category: "Unhealthy for Sensitive Groups",
        timezone: location.timezone,
        crosses_midnight: false,
        interrupted_by_missing_data: false,
      },
    ],
    single_hour_spikes: [
      {
        time: "2026-11-21T19:00",
        us_aqi: 108,
        category: "Unhealthy for Sensitive Groups",
        timezone: location.timezone,
      },
    ],
    better_windows: {
      status: "windows_identified",
      guardrail_max_aqi_ceiling: 100,
      windows: [
        {
          start_time: "2026-11-21T06:00",
          end_time: "2026-11-21T09:00",
          duration_hours: 4,
          mean_aqi: 72.5,
          min_aqi: 68,
          max_aqi: 78,
          category: "Moderate",
          hourly_aqi_values: [68, 73, 78, 71],
          timezone: location.timezone,
          crosses_midnight: false,
          rationale:
            "Lowest multi-hour forecast AQI band remaining at or below US AQI 100.",
        },
      ],
      note: "Comparatively favorable windows represent lower relative forecast AQI, not guaranteed clean air.",
    },
    trend_signals: [
      {
        metric: "us_aqi",
        unit: "US AQI",
        signal: "Rising",
        valid_points: 24,
        elapsed_span_hours: 23,
        slope_per_hour: 0.9,
        projected_net_change: 20.7,
        r_squared: 0.42,
        volatility_flag: false,
        description: "US AQI trends upward into the afternoon peak.",
        heuristic_note: "Deterministic OLS slope over available hourly forecast points.",
      },
      {
        metric: "PM2.5",
        unit: "µg/m³",
        signal: "Stable",
        valid_points: 24,
        elapsed_span_hours: 23,
        slope_per_hour: 0.1,
        projected_net_change: 2.3,
        r_squared: 0.12,
        volatility_flag: false,
        description: "PM2.5 remains relatively steady across the forecast window.",
        heuristic_note: "Deterministic OLS slope over available hourly forecast points.",
      },
    ],
    activity_recommendations: [
      {
        activity_type: "outdoor_exercise",
        label: "Outdoor Exercise",
        status: "window_identified",
        operational_rule_description:
          "Identifies 2+ consecutive hours with max US AQI <= 100.",
        recommended_window: {
          start_time: "2026-11-21T06:00",
          end_time: "2026-11-21T08:00",
          duration_hours: 3,
          mean_aqi: 73,
          min_aqi: 68,
          max_aqi: 78,
          category: "Moderate",
          hourly_aqi_values: [68, 73, 78],
          timezone: location.timezone,
          crosses_midnight: false,
        },
        rationale:
          "Early morning hours offer comparatively lower modeled AQI before afternoon elevation.",
        is_medical_advice: false,
        disclaimer: "General informational planning guidance; not medical advice.",
      },
      {
        activity_type: "outdoor_errands",
        label: "Outdoor Errands",
        status: "window_identified",
        operational_rule_description:
          "Identifies 2+ consecutive hours with max US AQI <= 100.",
        recommended_window: {
          start_time: "2026-11-21T07:00",
          end_time: "2026-11-21T09:00",
          duration_hours: 3,
          mean_aqi: 74,
          min_aqi: 71,
          max_aqi: 78,
          category: "Moderate",
          hourly_aqi_values: [73, 78, 71],
          timezone: location.timezone,
          crosses_midnight: false,
        },
        rationale:
          "Mid-morning remains below elevated afternoon AQI thresholds.",
        is_medical_advice: false,
        disclaimer: "General informational planning guidance; not medical advice.",
      },
      {
        activity_type: "general_outdoor",
        label: "General Outdoor Time",
        status: "window_identified",
        operational_rule_description:
          "Identifies 2+ consecutive hours with max US AQI <= 100.",
        recommended_window: {
          start_time: "2026-11-21T06:00",
          end_time: "2026-11-21T09:00",
          duration_hours: 4,
          mean_aqi: 72.5,
          min_aqi: 68,
          max_aqi: 78,
          category: "Moderate",
          hourly_aqi_values: [68, 73, 78, 71],
          timezone: location.timezone,
          crosses_midnight: false,
        },
        rationale:
          "Morning hours provide the lowest relative modeled AQI over the 24-hour horizon.",
        is_medical_advice: false,
        disclaimer: "General informational planning guidance; not medical advice.",
      },
    ],
    data_quality: {
      tier: "High",
      valid_aqi_hours: 24,
      expected_forecast_hours: 24,
      completeness_percent: 100,
      missing_hours_count: 0,
      timestamp_continuity: "continuous",
      gap_count: 0,
      pollutant_coverage: {
        PM2_5: { valid_hours: 24, expected_hours: 24, completeness_percent: 100 },
        PM10: { valid_hours: 24, expected_hours: 24, completeness_percent: 100 },
      },
      cache_hit: false,
      source_provider: "Open-Meteo CAMS Global",
      module_sufficiency: {
        risk_windows: "sufficient",
        better_windows: "sufficient",
        trend_signals: "sufficient",
        activity_planner: "sufficient",
      },
      disclosure:
        "Derived deterministically from 24 hourly Open-Meteo CAMS Global forecast points.",
    },
    provenance: buildProvenance(location),
    attribution: DEFAULT_ATTRIBUTION,
    is_demo_data: false,
    is_ai_generated: false,
    disclaimer:
      "Deterministic analytical interpretation of Open-Meteo CAMS Global forecast data. Not medical advice or ground-station measurements.",
    ...overrides,
  };
}

export function buildMockPredictiveIntelligenceInsufficientData(
  locationId = "lagos-ng"
): PredictiveIntelligenceResponse {
  const location = getLocation(locationId);
  return {
    location,
    provider: "Open-Meteo (CAMS Global)",
    data_mode: "predictive_intelligence",
    data_label:
      "ANALYTICAL INTERPRETATION — BASED ON OPEN-METEO CAMS GLOBAL FORECAST",
    observation_time: "2026-11-21T12:00",
    retrieval_time: "2026-11-21T12:05:00Z",
    generated_at: "2026-11-21T12:05:01Z",
    timezone: location.timezone,
    timezone_abbreviation:
      location.id === "nairobi-ke"
        ? "EAT"
        : location.id === "accra-gh"
        ? "GMT"
        : "WAT",
    horizon_hours: 24,
    hourly_risk_timeline: [],
    daily_summary: {
      peak_forecast_risk: "Unavailable",
      peak_aqi: null,
      peak_time: null,
      mean_aqi: null,
      min_aqi: null,
      dominant_category: "Unavailable",
      category_distribution: [],
      risk_window_evaluation_status: "insufficient_data",
      risk_windows_count: 0,
      single_hour_spikes_count: 0,
      better_windows_count: 0,
      forecast_completeness_percent: 0,
      data_quality_tier: "Insufficient data",
      deterministic_summary: `Insufficient valid forecast hours available to compute predictive intelligence for ${location.display_name}.`,
    },
    risk_windows: [],
    single_hour_spikes: [],
    better_windows: {
      status: "insufficient_data",
      guardrail_max_aqi_ceiling: 100,
      windows: [],
      note: "Insufficient valid forecast observations to identify comparatively favorable windows.",
    },
    trend_signals: [
      {
        metric: "us_aqi",
        unit: "US AQI",
        signal: "Insufficient data",
        valid_points: 0,
        elapsed_span_hours: 0,
        slope_per_hour: null,
        projected_net_change: null,
        r_squared: null,
        volatility_flag: false,
        description: "Insufficient valid US AQI forecast points for trend analysis.",
        heuristic_note: "Requires at least 6 valid hourly observations.",
      },
    ],
    activity_recommendations: [
      {
        activity_type: "outdoor_exercise",
        label: "Outdoor Exercise",
        status: "insufficient_data",
        operational_rule_description:
          "Identifies 2+ consecutive hours with max US AQI <= 100.",
        recommended_window: null,
        rationale:
          "Insufficient forecast data to evaluate outdoor exercise windows.",
        is_medical_advice: false,
        disclaimer: "General informational planning guidance; not medical advice.",
      },
    ],
    data_quality: {
      tier: "Insufficient data",
      valid_aqi_hours: 0,
      expected_forecast_hours: 24,
      completeness_percent: 0,
      missing_hours_count: 24,
      timestamp_continuity: "none",
      gap_count: 1,
      pollutant_coverage: {},
      cache_hit: false,
      source_provider: "Open-Meteo CAMS Global",
      module_sufficiency: {
        risk_windows: "insufficient_data",
        better_windows: "insufficient_data",
        trend_signals: "insufficient_data",
        activity_planner: "insufficient_data",
      },
      disclosure:
        "No valid hourly US AQI forecast observations were available for this horizon.",
    },
    provenance: buildProvenance(location),
    attribution: DEFAULT_ATTRIBUTION,
    is_demo_data: false,
    is_ai_generated: false,
    disclaimer:
      "Deterministic analytical interpretation of Open-Meteo CAMS Global forecast data. Not medical advice or ground-station measurements.",
  };
}

export function buildMockAssistantStatusResponse(
  overrides: Partial<AssistantStatusResponse> = {}
): AssistantStatusResponse {
  return {
    configured: true,
    status: "ready",
    model: "gemini-2.5-flash",
    sdk: "google-genai",
    message: "Gemini Air Quality Assistant is ready.",
    ...overrides,
  };
}

export function buildMockAssistantResponse(
  locationId = "lagos-ng",
  overrides: Partial<AssistantResponse> = {}
): AssistantResponse {
  const location = getLocation(locationId);
  return {
    status: "ok",
    mode: "ask",
    model: "gemini-2.5-flash",
    location,
    question: "How is air quality today?",
    generated_at: "2026-11-21T12:05:02Z",
    sections: {
      verified_data_summary: `Current modeled US AQI in ${location.display_name} is 78 (Moderate).`,
      forecast_context: "Afternoon AQI may reach 120 between 14:00 and 16:00.",
      ai_interpretation:
        "Moderate conditions overall with an afternoon elevation window.",
      general_health_guidance:
        "Sensitive groups should consider scheduling strenuous outdoor activity earlier in the morning.",
      model_limitations_notice:
        "Based on ~40 km CAMS Global model estimates; not a physical station reading.",
    },
    verified_context: {
      location,
      data_status: "available",
      data_label: "LIVE PROVIDER DATA — MODEL-BASED ESTIMATE",
      observation_time: "2026-11-21T12:00",
      retrieval_time: "2026-11-21T12:05:00Z",
      timezone: location.timezone,
      us_aqi: 78,
      aqi_band: "Moderate",
      pollutants: [
        { code: "PM2.5", value: 24.8, unit: "µg/m³", status: "available" },
      ],
      forecast_summary: {
        hours_available: 24,
        first_forecast_time: "2026-11-21T00:00",
        last_forecast_time: "2026-11-21T23:00",
        min_forecast_aqi: 68,
        max_forecast_aqi: 120,
        lowest_aqi_timestamp: "2026-11-21T06:00",
        highest_aqi_timestamp: "2026-11-21T16:00",
      },
      missing_fields: [],
      error_notice: null,
    },
    city_comparisons: [],
    provenance: buildProvenance(location),
    attribution: DEFAULT_ATTRIBUTION,
    is_ai_generated: true,
    disclaimer: "AI-generated summary grounded in Open-Meteo model estimates.",
    ...overrides,
  };
}

export function buildMockDashboardResponse(
  locationId = "lagos-ng",
  overrides: Partial<DashboardResponse> = {}
): DashboardResponse {
  const location = getLocation(locationId);
  return {
    is_demo_data: true,
    data_mode: "demo",
    data_source_label: "DEMO DATA — ILLUSTRATIVE SAMPLE",
    disclaimer: "Illustrative demo values for offline fallback testing.",
    selected_location: location,
    available_locations: Object.values(CANONICAL_LOCATIONS),
    summary: {
      aqi_value: 74,
      aqi_band: "Moderate",
      dominant_pollutant: "PM2.5",
      summary_statement: "Illustrative moderate air quality sample.",
      reference_timestamp_label: "Demo reference",
      weather_context: "Warm, light coastal breeze",
    },
    pollutants: [
      {
        code: "PM2.5",
        name: "Fine Particulate Matter (PM2.5)",
        value: 23.0,
        unit: "µg/m³",
        status: "Moderate",
        who_guideline_ref: "WHO 24-hr guideline reference: 15 µg/m³",
        source_hint: "Urban combustion",
      },
    ],
    health_advisory: {
      headline: "Moderate air quality",
      general_advice: "Acceptable for most people.",
      groups: [],
    },
    daily_recommendations: [],
    assistant_preview: {
      status_label: "Demo preview",
      capabilities_summary: "Illustrative assistant preview.",
      sample_prompts: [],
    },
    ...overrides,
  };
}

export interface MockEndpointOverride {
  status?: number;
  body?: unknown;
  delayMs?: number;
  abort?: boolean;
}

export interface InstallMockApiOptions {
  /** Override individual endpoints by route key */
  overrides?: Partial<
    Record<
      | "health"
      | "dashboard"
      | "airQuality"
      | "history"
      | "historyCompare"
      | "intelligence"
      | "assistantStatus"
      | "assistantAsk",
      MockEndpointOverride | ((url: URL) => MockEndpointOverride)
    >
  >;
}

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "Content-Type, Accept",
};

async function fulfillJson(
  route: Route,
  body: unknown,
  status = 200,
  delayMs = 0
): Promise<void> {
  if (delayMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: CORS_HEADERS,
    body: JSON.stringify(body),
  });
}

export interface RecordedApiRequest {
  method: string;
  pathname: string;
  searchParams: Record<string, string>;
  postData: unknown;
}

export interface MockApiController {
  requests: RecordedApiRequest[];
  clearRequests: () => void;
}

/**
 * Installs deterministic route interception for all AIRWISE AI backend APIs
 * and Leaflet CARTO map tiles.
 */
export async function installMockApi(
  page: Page,
  options: InstallMockApiOptions = {}
): Promise<MockApiController> {
  const requests: RecordedApiRequest[] = [];

  await page.route("**/*basemaps.cartocdn.com/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/png",
      body: TRANSPARENT_PNG_BUFFER,
    });
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: CORS_HEADERS });
      return;
    }

    const url = new URL(request.url());
    const pathname = url.pathname;
    const searchParams: Record<string, string> = {};
    url.searchParams.forEach((value, k) => {
      searchParams[k] = value;
    });

    let postData: unknown = null;
    if (request.method() === "POST") {
      try {
        postData = request.postDataJSON();
      } catch {
        postData = request.postData();
      }
    }

    requests.push({
      method: request.method(),
      pathname,
      searchParams,
      postData,
    });

    const locationId =
      url.searchParams.get("location_id") ??
      url.searchParams.get("location") ??
      "lagos-ng";
    const daysParam = Number(url.searchParams.get("days") ?? "7");
    const days: HistoricalRangeDays =
      daysParam === 14 || daysParam === 30 ? daysParam : 7;

    let key: keyof NonNullable<InstallMockApiOptions["overrides"]> | null = null;
    let defaultBody: unknown = {};

    if (pathname.endsWith("/api/v1/health")) {
      key = "health";
      defaultBody = buildMockHealthResponse();
    } else if (pathname.endsWith("/api/v1/dashboard")) {
      key = "dashboard";
      defaultBody = buildMockDashboardResponse(locationId);
    } else if (pathname.endsWith("/api/v1/air-quality/intelligence")) {
      key = "intelligence";
      defaultBody = buildMockPredictiveIntelligenceResponse(locationId);
    } else if (pathname.endsWith("/api/v1/air-quality/history/compare")) {
      key = "historyCompare";
      defaultBody = buildMockHistoricalComparisonResponse(days);
    } else if (pathname.endsWith("/api/v1/air-quality/history")) {
      key = "history";
      defaultBody = buildMockHistoricalResponse(locationId, days);
    } else if (pathname.endsWith("/api/v1/air-quality")) {
      key = "airQuality";
      defaultBody = buildMockAirQualityResponse(locationId);
    } else if (pathname.endsWith("/api/v1/assistant/status")) {
      key = "assistantStatus";
      defaultBody = buildMockAssistantStatusResponse();
    } else if (pathname.endsWith("/api/v1/assistant/ask")) {
      key = "assistantAsk";
      const payload = (postData ?? {}) as {
        location_id?: string;
        mode?: AssistantResponse["mode"];
        question?: string;
        pollutant_code?: string | null;
      };
      const reqLocationId = payload.location_id ?? locationId;
      const reqMode = payload.mode ?? "ask";
      const reqQuestion = payload.question ?? "How is air quality today?";
      const cityComparisons =
        reqMode === "city_comparison"
          ? Object.values(CANONICAL_LOCATIONS).map((loc) => {
              const aq = buildMockAirQualityResponse(loc.id);
              return {
                location: loc,
                data_status: "available" as const,
                data_label: aq.data_label,
                observation_time: aq.observation_time,
                retrieval_time: aq.retrieval_time,
                timezone: loc.timezone,
                us_aqi: aq.aqi.value,
                aqi_band: aq.aqi.band,
                pollutants: [
                  {
                    code: "PM2.5" as const,
                    value: aq.pm2_5.value,
                    unit: "µg/m³",
                    status: "available" as const,
                  },
                ],
                forecast_summary: null,
                missing_fields: [],
                error_notice: null,
              };
            })
          : [];

      defaultBody = buildMockAssistantResponse(reqLocationId, {
        mode: reqMode,
        question: reqQuestion,
        city_comparisons: cityComparisons,
        sections: {
          verified_data_summary: `Current modeled US AQI in ${getLocation(reqLocationId).display_name} is ${buildMockAirQualityResponse(reqLocationId).aqi.value} (${buildMockAirQualityResponse(reqLocationId).aqi.band}).${payload.pollutant_code ? ` Focus pollutant: ${payload.pollutant_code}.` : ""}`,
          forecast_context:
            "Afternoon AQI may reach 120 between 14:00 and 16:00.",
          ai_interpretation:
            reqMode === "city_comparison"
              ? "Nairobi currently has the lowest modeled US AQI (44, Good) while Lagos is highest (78, Moderate)."
              : `Grounded interpretation for ${getLocation(reqLocationId).display_name}${payload.pollutant_code ? ` focusing on ${payload.pollutant_code}` : ""}.`,
          general_health_guidance:
            "Sensitive groups should consider scheduling strenuous outdoor activity earlier in the morning.",
          model_limitations_notice:
            "Based on ~40 km CAMS Global model estimates; not a physical station reading.",
        },
      });
    }

    const rawOverride = key ? options.overrides?.[key] : undefined;
    const resolvedOverride =
      typeof rawOverride === "function" ? rawOverride(url) : rawOverride;

    if (resolvedOverride?.abort) {
      await route.abort("failed");
      return;
    }

    await fulfillJson(
      route,
      resolvedOverride?.body !== undefined ? resolvedOverride.body : defaultBody,
      resolvedOverride?.status ?? 200,
      resolvedOverride?.delayMs ?? 0
    );
  });

  return {
    requests,
    clearRequests: () => {
      requests.length = 0;
    },
  };
}
