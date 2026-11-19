/**
 * Client-side demo fallback dataset used ONLY when the FastAPI backend is unreachable
 * or when the user explicitly switches to local demo fallback mode.
 *
 * Every string and flag explicitly marks this payload as offline sample/demo data.
 */

import { DashboardResponse, LocationOption } from "@/types/dashboard";

export const FALLBACK_LOCATIONS: LocationOption[] = [
  {
    id: "lagos-ng",
    city: "Lagos",
    region: "Lagos State",
    country: "Nigeria",
    display_name: "Lagos, Nigeria",
    latitude: 6.5244,
    longitude: 3.3792,
    timezone: "Africa/Lagos",
  },
  {
    id: "abuja-ng",
    city: "Abuja",
    region: "Federal Capital Territory",
    country: "Nigeria",
    display_name: "Abuja, Nigeria",
    latitude: 9.0765,
    longitude: 7.3986,
    timezone: "Africa/Lagos",
  },
  {
    id: "nairobi-ke",
    city: "Nairobi",
    region: "Nairobi County",
    country: "Kenya",
    display_name: "Nairobi, Kenya",
    latitude: -1.2921,
    longitude: 36.8219,
    timezone: "Africa/Nairobi",
  },
  {
    id: "accra-gh",
    city: "Accra",
    region: "Greater Accra",
    country: "Ghana",
    display_name: "Accra, Ghana",
    latitude: 5.6037,
    longitude: -0.187,
    timezone: "Africa/Accra",
  },
];

export function getClientFallbackDashboard(locationId: string = "lagos-ng"): DashboardResponse {
  const selected =
    FALLBACK_LOCATIONS.find((loc) => loc.id === locationId) ?? FALLBACK_LOCATIONS[0];

  const isLagos = selected.id === "lagos-ng";

  return {
    is_demo_data: true,
    data_mode: "demo",
    data_source_label:
      "DEMO DATA (LOCAL FALLBACK) — Simulated Urban Scenario (Backend API Offline / No Live Provider)",
    disclaimer:
      "All AQI numbers, pollutant concentrations, and health advisories are deterministic sample/demo data for UI foundation preview. They are NOT real-time air quality measurements.",
    selected_location: selected,
    available_locations: FALLBACK_LOCATIONS,
    summary: {
      aqi_value: isLagos ? 112 : 84,
      aqi_band: isLagos ? "Unhealthy for Sensitive Groups" : "Moderate",
      dominant_pollutant: isLagos ? "PM2.5" : "PM10",
      summary_statement: isLagos
        ? "DEMO SCENARIO: Elevated fine particulate matter modeled for peak traffic corridors across Lagos Mainland and Island approaches. Sensitive groups should reduce prolonged roadside exposure."
        : `DEMO SCENARIO: Moderate particulate levels modeled for ${selected.display_name} urban corridors. Explicitly sample data.`,
      reference_timestamp_label:
        "Sample Scenario: Weekday Morning Commute Baseline (Not Live Telemetry)",
      weather_context: isLagos
        ? "Sample meteorology: Warm humid coastal airflow (29°C, 76% RH, light SW breeze)"
        : "Sample meteorology: Urban baseline scenario (28°C, 55% RH, moderate breeze)",
    },
    pollutants: [
      {
        code: "PM2.5",
        name: "Fine Particulate Matter (<2.5 µm)",
        value: isLagos ? 39.8 : 24.5,
        unit: "µg/m³",
        status: isLagos ? "Elevated" : "Moderate",
        who_guideline_ref: "24-hr reference benchmark: 15 µg/m³",
        source_hint:
          "Vehicular exhaust, diesel backup generators, and peri-urban biomass combustion",
      },
      {
        code: "PM10",
        name: "Coarse Particulate Matter (<10 µm)",
        value: isLagos ? 78.4 : 88.0,
        unit: "µg/m³",
        status: "Moderate",
        who_guideline_ref: "24-hr reference benchmark: 45 µg/m³",
        source_hint:
          "Unpaved road dust resuspension, construction activity, and transit corridors",
      },
      {
        code: "NO2",
        name: "Nitrogen Dioxide",
        value: isLagos ? 34.2 : 21.0,
        unit: "µg/m³",
        status: isLagos ? "Elevated" : "Low",
        who_guideline_ref: "24-hr reference benchmark: 25 µg/m³",
        source_hint: "Congested arterial road corridors during peak commuter flow",
      },
      {
        code: "O3",
        name: "Ground-Level Ozone",
        value: 46.0,
        unit: "µg/m³",
        status: "Low",
        who_guideline_ref: "8-hr peak reference benchmark: 100 µg/m³",
        source_hint: "Secondary photochemical formation during midday solar radiation",
      },
    ],
    health_advisory: {
      headline: `Demo Health Advisory for ${selected.display_name}`,
      general_advice:
        "These recommendations demonstrate how AIRWISE AI translates particulate and gas thresholds into practical urban public health guidance. Do not use this demo dataset for medical decisions.",
      groups: [
        {
          audience: "Sensitive Groups (Asthma, COPD, Children, Older Adults)",
          risk_level: "Elevated in sample scenario",
          guidance:
            "Limit prolonged outdoor exertion adjacent to heavy traffic corridors during peak hours. Keep prescribed rescue inhalers accessible.",
        },
        {
          audience: "Outdoor Workers & Transit Commuters",
          risk_level: "Moderate to Elevated",
          guidance:
            "Consider well-fitted particulate respirators (KN95/FFP2) when stationed in slow-moving traffic or generator-dense commercial zones.",
        },
        {
          audience: "General Population",
          risk_level: "Low to Moderate",
          guidance:
            "Normal outdoor activities are acceptable away from congested highways; shift high-intensity cardio to parks or breeze-flushed windows.",
        },
      ],
    },
    daily_recommendations: [
      {
        id: "rec-commute-window",
        time_window: "06:30 – 09:30 Local (Sample Peak)",
        title: "Mitigate In-Cabin Commute Exposure",
        description: `In this ${selected.city} demo scenario, use vehicle air recirculation when queued on major arterials to lower cabin PM2.5 and NO2 ingress.`,
        priority: "High",
        category: "Commute",
      },
      {
        id: "rec-ventilation-window",
        time_window: "13:00 – 16:00 Local (Sample Dispersion Window)",
        title: "Schedule Natural Indoor Ventilation",
        description:
          "Afternoon thermal mixing and sea/land breezes typically aid vertical pollutant dispersion. Prefer cross-ventilating homes away from active diesel generators.",
        priority: "Medium",
        category: "Ventilation",
      },
      {
        id: "rec-outdoor-fitness",
        time_window: "16:30 – 18:00 Local",
        title: "Select Low-Traffic Green Corridors for Exercise",
        description:
          "Route outdoor runs or walks at least 150–200 meters setback from main highways to cut ultrafine particulate exposure.",
        priority: "Medium",
        category: "Exercise",
      },
    ],
    assistant_preview: {
      status_label: "Preview Mode — Sample Context Only (LLM & Live Sensors Not Connected)",
      capabilities_summary: `The AIRWISE AI Assistant synthesizes hyper-local pollutant readings, meteorological context, and WHO health benchmarks for ${selected.display_name}. Below are deterministic sample Q&A previews.`,
      sample_prompts: [
        {
          id: "prompt-outdoor-jog",
          question: `Is it safe to go for an outdoor run in ${selected.city} under these sample conditions?`,
          preview_answer: `[DEMO PREVIEW] With a sample AQI of ${isLagos ? 112 : 84}, healthy adults can exercise outdoors if they avoid major road intersections. Individuals with respiratory sensitivity should prefer indoor workouts or wait for afternoon dispersion windows.`,
        },
        {
          id: "prompt-pm25-driver",
          question: `What is driving the sample PM2.5 reading in ${selected.display_name}?`,
          preview_answer: `[DEMO PREVIEW] In this simulated ${selected.city} scenario, fine particulates (PM2.5) are modeled from commuter traffic exhaust, commercial diesel generators, and localized dust or biomass sources.`,
        },
        {
          id: "prompt-school-guidance",
          question:
            "What precautions should schools take during an 'Unhealthy for Sensitive Groups' scenario?",
          preview_answer:
            "[DEMO PREVIEW] Schools should keep outdoor physical education moderate, monitor students with asthma during peak morning traffic hours, and close street-facing windows during rush hour.",
        },
      ],
    },
  };
}
