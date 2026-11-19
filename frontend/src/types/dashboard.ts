/**
 * TypeScript domain models matching the FastAPI Pydantic v2 schemas
 * for both the Day 1 Demo Dashboard and the Phase 2/3 Open-Meteo Air Quality API.
 */

export type DataMode = "demo";
export type AirQualityDataMode = "live_model";
export type ValueAvailabilityStatus = "available" | "unavailable";
export type HourlyPointClassification =
  | "historical_model"
  | "current_model"
  | "hourly_forecast";

export type AqiBand =
  | "Good"
  | "Moderate"
  | "Unhealthy for Sensitive Groups"
  | "Unhealthy"
  | "Very Unhealthy"
  | "Hazardous";

export type PollutantStatus = "Low" | "Moderate" | "Elevated" | "High";

export type PriorityLevel = "High" | "Medium" | "Informational";

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  environment: string;
  data_mode: DataMode;
  live_provider_connected: boolean;
}

export interface LocationOption {
  id: string;
  city: string;
  region: string;
  country: string;
  display_name: string;
  latitude: number;
  longitude: number;
  timezone: string;
}

export interface AirQualitySummary {
  aqi_value: number;
  aqi_band: AqiBand;
  dominant_pollutant: string;
  summary_statement: string;
  reference_timestamp_label: string;
  weather_context: string;
}

export interface PollutantCard {
  code: string;
  name: string;
  value: number;
  unit: string;
  status: PollutantStatus;
  who_guideline_ref: string;
  source_hint: string;
}

export interface HealthGuidanceGroup {
  audience: string;
  risk_level: string;
  guidance: string;
}

export interface HealthAdvisoryPanel {
  headline: string;
  general_advice: string;
  groups: HealthGuidanceGroup[];
}

export interface DailyRecommendation {
  id: string;
  time_window: string;
  title: string;
  description: string;
  priority: PriorityLevel;
  category: string;
}

export interface AssistantSamplePrompt {
  id: string;
  question: string;
  preview_answer: string;
}

export interface AssistantPreview {
  status_label: string;
  capabilities_summary: string;
  sample_prompts: AssistantSamplePrompt[];
}

export interface DashboardResponse {
  is_demo_data: true;
  data_mode: DataMode;
  data_source_label: string;
  disclaimer: string;
  selected_location: LocationOption;
  available_locations: LocationOption[];
  summary: AirQualitySummary;
  pollutants: PollutantCard[];
  health_advisory: HealthAdvisoryPanel;
  daily_recommendations: DailyRecommendation[];
  assistant_preview: AssistantPreview;
}

// ============================================================================
// Phase 2 & 3: Open-Meteo Air Quality Endpoint Schemas (GET /api/v1/air-quality)
// ============================================================================

export interface AirQualityUnits {
  us_aqi: string;
  pm2_5: string;
  pm10: string;
  nitrogen_dioxide: string;
  ozone: string;
  sulphur_dioxide: string;
}

export interface PollutantMeasurement {
  code: "PM2.5" | "PM10" | "NO2" | "O3" | "SO2";
  parameter: string;
  name: string;
  value: number | null;
  unit: string;
  status: ValueAvailabilityStatus;
}

export interface AqiMeasurement {
  value: number | null;
  standard: "US EPA AQI (Open-Meteo Model Output)";
  unit: string;
  band: AqiBand | null;
  status: ValueAvailabilityStatus;
}

export interface CurrentModelConditions {
  classification: "current_model";
  observation_time: string;
  interval_seconds: number | null;
  aqi: AqiMeasurement;
  pm2_5: PollutantMeasurement;
  pm10: PollutantMeasurement;
  no2: PollutantMeasurement;
  o3: PollutantMeasurement;
  so2: PollutantMeasurement;
}

export interface HourlyModelPoint {
  classification: HourlyPointClassification;
  time: string;
  us_aqi: number | null;
  pm2_5: number | null;
  pm10: number | null;
  no2: number | null;
  o3: number | null;
  so2: number | null;
}

export interface HourlyForecastPoint extends HourlyModelPoint {
  classification: "hourly_forecast";
}

export interface HourlyForecastSeries {
  classification: "hourly_forecast";
  hours_returned: number;
  points: HourlyForecastPoint[];
  historical_hours_count: number;
  historical_points: HourlyModelPoint[];
  current_hour_point: HourlyModelPoint | null;
}

export interface CamsGlobalModelMetadata {
  domain: string;
  spatial_resolution: string;
  source_temporal_resolution: string;
  api_timestamp_interval: string;
  forecast_availability: string;
}

export interface DataAttribution {
  provider_attribution: string;
  cams_attribution: string;
  sources: string[];
}

export interface DataProvenance {
  data_label: "LIVE PROVIDER DATA — MODEL-BASED ESTIMATE";
  provider_name: string;
  endpoint_url: string;
  model_domain: string;
  spatial_resolution: string;
  source_temporal_resolution: string;
  api_timestamp_interval: string;
  forecast_availability: string;
  model_metadata: CamsGlobalModelMetadata;
  attribution: DataAttribution;
  methodology: string;
  is_physical_station_measurement: false;
  is_demo_data: false;
  cache_hit: boolean;
  provider_latitude: number | null;
  provider_longitude: number | null;
}

export interface AirQualityResponse {
  location: LocationOption;
  provider: string;
  data_mode: AirQualityDataMode;
  data_label: "LIVE PROVIDER DATA — MODEL-BASED ESTIMATE";
  observation_time: string;
  retrieval_time: string;
  timezone: string;
  timezone_abbreviation: string | null;
  aqi: AqiMeasurement;
  pm2_5: PollutantMeasurement;
  pm10: PollutantMeasurement;
  no2: PollutantMeasurement;
  o3: PollutantMeasurement;
  so2: PollutantMeasurement;
  units: AirQualityUnits;
  current_conditions: CurrentModelConditions;
  hourly_forecast: HourlyForecastSeries;
  hourly_timeline: HourlyModelPoint[];
  provenance: DataProvenance;
  attribution: DataAttribution;
  disclaimer: string;
}

// ============================================================================
// Phase 5: Gemini Air Quality Assistant Schemas
// ============================================================================

export type AssistantMode =
  | "ask"
  | "activity_planner"
  | "pollutant_education"
  | "city_comparison";

export type PollutantCode = "PM2.5" | "PM10" | "NO2" | "O3" | "SO2";

export interface ConversationTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AssistantRequest {
  location_id: string;
  mode: AssistantMode;
  question: string;
  pollutant_code?: PollutantCode | null;
  history?: ConversationTurn[];
}

export interface VerifiedPollutantSnapshot {
  code: PollutantCode;
  value: number | null;
  unit: string;
  status: ValueAvailabilityStatus;
}

export interface VerifiedForecastSummary {
  hours_available: number;
  first_forecast_time: string | null;
  last_forecast_time: string | null;
  min_forecast_aqi: number | null;
  max_forecast_aqi: number | null;
  lowest_aqi_timestamp: string | null;
  highest_aqi_timestamp: string | null;
}

export interface VerifiedCitySnapshot {
  location: LocationOption;
  data_status: ValueAvailabilityStatus;
  data_label: string;
  observation_time: string | null;
  retrieval_time: string | null;
  timezone: string;
  us_aqi: number | null;
  aqi_band: AqiBand | null;
  pollutants: VerifiedPollutantSnapshot[];
  forecast_summary: VerifiedForecastSummary | null;
  missing_fields: string[];
  error_notice: string | null;
}

export interface StructuredAssistantSections {
  verified_data_summary: string;
  forecast_context: string;
  ai_interpretation: string;
  general_health_guidance: string;
  model_limitations_notice: string;
}

export interface AssistantStatusResponse {
  configured: boolean;
  status: "ready" | "assistant_unavailable";
  model: string;
  sdk: string;
  message: string;
}

export interface AssistantResponse {
  status: "ok" | "assistant_unavailable";
  mode: AssistantMode;
  model: string;
  location: LocationOption;
  question: string;
  generated_at: string;
  sections: StructuredAssistantSections;
  verified_context: VerifiedCitySnapshot;
  city_comparisons: VerifiedCitySnapshot[];
  provenance: DataProvenance | null;
  attribution: DataAttribution;
  is_ai_generated: true;
  disclaimer: string;
}

// ============================================================================
// Phase 6.2: Historical Air Quality Trends & Multi-City Comparison Schemas
// ============================================================================

export type HistoricalRangeDays = 7 | 14 | 30;

export type HistoricalStorageOrigin =
  | "fresh_provider_retrieval"
  | "historical_cache"
  | "persisted_database_records"
  | "persisted_database_fallback";

export type HistoricalMetricKey =
  | "us_aqi"
  | "pm2_5"
  | "pm10"
  | "no2"
  | "o3"
  | "so2";

export interface HistoricalHourlyRecord {
  classification: "historical_model";
  timestamp_utc: string;
  local_time: string;
  timezone: string;
  us_aqi: number | null;
  pm2_5: number | null;
  pm10: number | null;
  no2: number | null;
  o3: number | null;
  so2: number | null;
  source: string;
  model_domain: string;
  retrieval_time: string;
}

export interface DailyHistoricalSummary {
  date: string;
  timezone: string;
  avg_us_aqi: number | null;
  max_us_aqi: number | null;
  min_us_aqi: number | null;
  dominant_aqi_band: AqiBand | null;
  avg_pm2_5: number | null;
  max_pm2_5: number | null;
  avg_pm10: number | null;
  avg_no2: number | null;
  avg_o3: number | null;
  avg_so2: number | null;
  valid_hours: number;
  expected_hours: number;
  missing_hours: number;
  completeness_percent: number;
}

export interface HistoricalPeriodSummary {
  days_requested: HistoricalRangeDays;
  days_with_data: number;
  total_valid_hours: number;
  total_expected_hours: number;
  total_missing_hours: number;
  completeness_percent: number;
  avg_us_aqi: number | null;
  max_us_aqi: number | null;
  min_us_aqi: number | null;
  peak_aqi_timestamp: string | null;
  avg_pm2_5: number | null;
  max_pm2_5: number | null;
  avg_pm10: number | null;
  avg_no2: number | null;
  avg_o3: number | null;
  avg_so2: number | null;
  days_by_aqi_band: Record<string, number>;
}

export interface HistoricalDataOriginMetadata {
  storage_origin: HistoricalStorageOrigin;
  cache_hit: boolean;
  served_from_persistence: boolean;
  persisted_to_database: boolean;
  fallback_reason: string | null;
}

export interface HistoricalAirQualityResponse {
  location: LocationOption;
  provider: string;
  data_mode: "historical_model";
  data_label: "HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE";
  range_days: HistoricalRangeDays;
  start_date: string;
  end_date: string;
  timezone: string;
  retrieval_time: string;
  units: AirQualityUnits;
  hourly_records: HistoricalHourlyRecord[];
  daily_summaries: DailyHistoricalSummary[];
  period_summary: HistoricalPeriodSummary;
  data_completeness_percent: number;
  origin: HistoricalDataOriginMetadata;
  provenance: DataProvenance;
  attribution: DataAttribution;
  is_demo_data: false;
  disclaimer: string;
}

export interface CityHistoricalComparisonItem {
  location: LocationOption;
  status: "available" | "unavailable";
  data_label: string;
  retrieval_time: string | null;
  origin: HistoricalDataOriginMetadata | null;
  period_summary: HistoricalPeriodSummary | null;
  daily_summaries: DailyHistoricalSummary[];
  error_code: string | null;
  error_message: string | null;
  is_demo_data: false;
}

export interface HistoricalCityComparisonResponse {
  range_days: HistoricalRangeDays;
  data_mode: "historical_model";
  data_label: "HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE";
  generated_at: string;
  cities_available: number;
  cities_unavailable: number;
  cities: CityHistoricalComparisonItem[];
  units: AirQualityUnits;
  attribution: DataAttribution;
  is_demo_data: false;
  disclaimer: string;
}


