"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import AirQualityMapSection from "@/components/AirQualityMapSection";
import AssistantPanel from "@/components/AssistantPanel";
import HistoricalTrendsSection from "@/components/HistoricalTrendsSection";
import PredictiveIntelligenceSection from "@/components/PredictiveIntelligenceSection";
import {
  fetchBackendHealth,
  fetchDashboardData,
  fetchLiveAirQuality,
  isRequestCanceledError,
} from "@/lib/api";
import {
  FALLBACK_LOCATIONS,
  getClientFallbackDashboard,
} from "@/lib/demoFallback";
import {
  AirQualityResponse,
  AqiBand,
  DashboardResponse,
  HealthResponse,
  PollutantMeasurement,
  PollutantStatus,
  PriorityLevel,
} from "@/types/dashboard";

/**
 * Operational mode of the dashboard:
 * - 'loading': Fetching live model data from FastAPI GET /api/v1/air-quality
 * - 'live-model': Displaying verified live model estimates from Open-Meteo (CAMS Global)
 * - 'stale-cached': A refresh failed, so the last successful live response for the SAME
 *                   location is shown with an explicit CACHED / STALE badge
 * - 'unavailable': Live API request failed and no cached live response exists for this
 *                  location; displays DATA UNAVAILABLE without silently substituting demo values
 * - 'demo-fallback': User explicitly activated the DEMO DATA fallback mode
 */
type ViewMode =
  | "loading"
  | "live-model"
  | "stale-cached"
  | "unavailable"
  | "demo-fallback";

interface DisplayPollutantCard {
  code: "PM2.5" | "PM10" | "NO2" | "O3" | "SO2";
  name: string;
  value: number | null;
  unit: string;
  availability: "available" | "loading" | "demo-excluded" | "unavailable";
  concentrationLevel: PollutantStatus | "Loading" | "Demo Excluded" | "Unavailable";
  whoGuidelineRef: string;
  sourceHint: string;
  originBadge:
    | "Live Model"
    | "Cached Model"
    | "Demo Sample"
    | "Loading"
    | "Demo Excluded"
    | "Data Unavailable";
}

const POLLUTANT_REFERENCE_METADATA: Record<
  "PM2.5" | "PM10" | "NO2" | "O3" | "SO2",
  {
    whoGuidelineRef: string;
    sourceHint: string;
    thresholds: { low: number; moderate: number; elevated: number };
  }
> = {
  "PM2.5": {
    whoGuidelineRef: "WHO 24-hr guideline reference: 15 µg/m³",
    sourceHint:
      "Combustion emissions (vehicular exhaust, diesel generators, biomass burning)",
    thresholds: { low: 15, moderate: 35, elevated: 55 },
  },
  PM10: {
    whoGuidelineRef: "WHO 24-hr guideline reference: 45 µg/m³",
    sourceHint:
      "Resuspended road dust, regional Harmattan/dust transport, construction aerosols",
    thresholds: { low: 45, moderate: 100, elevated: 150 },
  },
  NO2: {
    whoGuidelineRef: "WHO 24-hr guideline reference: 25 µg/m³",
    sourceHint:
      "High-temperature urban transport and power generation combustion",
    thresholds: { low: 25, moderate: 50, elevated: 100 },
  },
  O3: {
    whoGuidelineRef: "WHO 8-hr peak guideline reference: 100 µg/m³",
    sourceHint:
      "Daytime photochemical reaction of NOx and VOCs under solar radiation",
    thresholds: { low: 60, moderate: 100, elevated: 140 },
  },
  SO2: {
    whoGuidelineRef: "WHO 24-hr guideline reference: 40 µg/m³",
    sourceHint:
      "Sulphur-bearing diesel/heavy fuel oil combustion and industrial point sources",
    thresholds: { low: 20, moderate: 40, elevated: 80 },
  },
};

function classifyConcentrationLevel(
  code: "PM2.5" | "PM10" | "NO2" | "O3" | "SO2",
  value: number | null
): PollutantStatus | "Unavailable" {
  if (value === null || Number.isNaN(value)) {
    return "Unavailable";
  }
  const { low, moderate, elevated } = POLLUTANT_REFERENCE_METADATA[code].thresholds;
  if (value <= low) return "Low";
  if (value <= moderate) return "Moderate";
  if (value <= elevated) return "Elevated";
  return "High";
}

/**
 * Status badge colours preserving required AQI semantic hierarchy on dark surfaces:
 * - Good: green
 * - Moderate: yellow
 * - Unhealthy for Sensitive Groups: orange
 * - Unhealthy: red
 * - Very Unhealthy / Hazardous: purple
 */
function getAqiBadgeStyle(band: AqiBand | null): string {
  switch (band) {
    case "Good":
      return "bg-emerald-950/90 text-emerald-300 border-emerald-500/50";
    case "Moderate":
      return "bg-yellow-950/90 text-yellow-300 border-yellow-500/50";
    case "Unhealthy for Sensitive Groups":
      return "bg-orange-950/90 text-orange-300 border-orange-500/50";
    case "Unhealthy":
      return "bg-red-950/90 text-red-300 border-red-500/50";
    case "Very Unhealthy":
    case "Hazardous":
      return "bg-purple-950/90 text-purple-300 border-purple-500/50";
    default:
      return "bg-theme-secondary text-theme-muted border-theme-border";
  }
}

function getAqiAccentIndicatorStyle(band: AqiBand | null): string {
  switch (band) {
    case "Good":
      return "bg-emerald-400";
    case "Moderate":
      return "bg-yellow-400";
    case "Unhealthy for Sensitive Groups":
      return "bg-orange-400";
    case "Unhealthy":
      return "bg-red-400";
    case "Very Unhealthy":
    case "Hazardous":
      return "bg-purple-400";
    default:
      return "bg-slate-400";
  }
}

function getAqiBarColorStyle(aqi: number | null): string {
  if (aqi === null) return "bg-slate-600/50 border-slate-500/40";
  if (aqi <= 50) return "bg-emerald-500/80 border-emerald-400";
  if (aqi <= 100) return "bg-yellow-500/80 border-yellow-400";
  if (aqi <= 150) return "bg-orange-500/80 border-orange-400";
  if (aqi <= 200) return "bg-red-500/80 border-red-400";
  return "bg-purple-500/80 border-purple-400";
}

function getPollutantStatusStyle(
  status: PollutantStatus | "Loading" | "Demo Excluded" | "Unavailable"
): string {
  switch (status) {
    case "Low":
      return "bg-emerald-950/85 text-emerald-300 border-emerald-500/40";
    case "Moderate":
      return "bg-yellow-950/85 text-yellow-300 border-yellow-500/40";
    case "Elevated":
      return "bg-orange-950/85 text-orange-300 border-orange-500/40";
    case "High":
      return "bg-red-950/85 text-red-300 border-red-500/40";
    case "Loading":
      return "bg-teal-950/85 text-theme-mint border-theme-accent/40";
    case "Demo Excluded":
      return "bg-amber-950/75 text-amber-200 border-amber-500/40";
    case "Unavailable":
      return "bg-slate-900/90 text-slate-300 border-slate-600/50";
  }
}

function getPriorityBadgeStyle(priority: PriorityLevel): string {
  switch (priority) {
    case "High":
      return "bg-orange-950/85 text-orange-300 border-orange-500/40";
    case "Medium":
      return "bg-teal-950/90 text-theme-mint border-theme-accent/45";
    case "Informational":
      return "bg-theme-secondary text-theme-muted border-theme-border";
  }
}

function formatHourLabel(isoTime: string): string {
  const parts = isoTime.split("T");
  if (parts.length === 2) {
    return parts[1].slice(0, 5);
  }
  return isoTime;
}

function formatDateShort(isoTime: string): string {
  const parts = isoTime.split("T");
  return parts[0] ?? isoTime;
}

export default function DashboardClient() {
  const [selectedLocationId, setSelectedLocationId] = useState<string>("lagos-ng");
  const [viewMode, setViewMode] = useState<ViewMode>("loading");
  const [liveAirQuality, setLiveAirQuality] = useState<AirQualityResponse | null>(null);
  const [demoDashboard, setDemoDashboard] = useState<DashboardResponse>(() =>
    getClientFallbackDashboard("lagos-ng")
  );
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activePromptId, setActivePromptId] = useState<string>("prompt-outdoor-jog");
  const [activeSection, setActiveSection] = useState<string>("overview");

  // Concurrency & stale-cache refs to prevent race conditions during rapid location switching
  const requestSeqRef = useRef<number>(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const lastKnownByLocationRef = useRef<Record<string, AirQualityResponse>>({});
  const isDemoModeRef = useRef<boolean>(false);

  const loadLiveLocationData = useCallback(async (locationId: string) => {
    isDemoModeRef.current = false;

    // Cancel any in-flight request from a previous location selection
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    requestSeqRef.current += 1;
    const currentSeq = requestSeqRef.current;

    setViewMode("loading");
    setErrorMessage(null);

    // Clear mismatched location data immediately so another city's values never linger during load
    setLiveAirQuality((prev) => (prev?.location.id === locationId ? prev : null));

    const localDemo = getClientFallbackDashboard(locationId);
    setDemoDashboard(localDemo);
    if (localDemo.assistant_preview.sample_prompts.length > 0) {
      setActivePromptId(localDemo.assistant_preview.sample_prompts[0].id);
    }

    const [healthResult, liveResult, dashboardResult] = await Promise.allSettled([
      fetchBackendHealth(controller.signal),
      fetchLiveAirQuality(locationId, controller.signal),
      fetchDashboardData(locationId, controller.signal),
    ]);

    // Ignore results if a newer location request was started while this one was in flight
    if (currentSeq !== requestSeqRef.current || controller.signal.aborted) {
      return;
    }

    if (healthResult.status === "fulfilled") {
      setHealth(healthResult.value);
    } else if (!isRequestCanceledError(healthResult.reason)) {
      setHealth(null);
    }

    if (dashboardResult.status === "fulfilled") {
      setDemoDashboard(dashboardResult.value);
    }

    if (liveResult.status === "fulfilled") {
      const livePayload = liveResult.value;
      lastKnownByLocationRef.current[locationId] = livePayload;
      setLiveAirQuality(livePayload);
      setViewMode("live-model");
    } else {
      if (isRequestCanceledError(liveResult.reason)) {
        return;
      }

      const reason =
        liveResult.reason instanceof Error
          ? liveResult.reason.message
          : "Unable to fetch live model air quality data from FastAPI backend.";
      setErrorMessage(reason);

      // Preserve last successful response ONLY for the same location and mark it as cached/stale.
      // Never silently replace unavailable live readings with demo values.
      const cachedForCity = lastKnownByLocationRef.current[locationId];
      if (cachedForCity) {
        setLiveAirQuality(cachedForCity);
        setViewMode("stale-cached");
      } else {
        setLiveAirQuality(null);
        setViewMode("unavailable");
      }
    }
  }, []);

  useEffect(() => {
    if (isDemoModeRef.current) {
      const fallbackData = getClientFallbackDashboard(selectedLocationId);
      setDemoDashboard(fallbackData);
      if (fallbackData.assistant_preview.sample_prompts.length > 0) {
        setActivePromptId(fallbackData.assistant_preview.sample_prompts[0].id);
      }
      return;
    }

    void loadLiveLocationData(selectedLocationId);
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [loadLiveLocationData, selectedLocationId]);

  const handleLocationChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedLocationId(event.target.value);
  };

  const handleQuickLocationSelect = (locationId: string) => {
    if (locationId === selectedLocationId) {
      if (!isDemoModeRef.current) {
        void loadLiveLocationData(locationId);
      }
    } else {
      setSelectedLocationId(locationId);
    }
  };

  const handleActivateExplicitDemoFallback = () => {
    isDemoModeRef.current = true;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    requestSeqRef.current += 1;
    const fallbackData = getClientFallbackDashboard(selectedLocationId);
    setDemoDashboard(fallbackData);
    if (fallbackData.assistant_preview.sample_prompts.length > 0) {
      setActivePromptId(fallbackData.assistant_preview.sample_prompts[0].id);
    }
    setViewMode("demo-fallback");
  };

  const activeLocation =
    (liveAirQuality?.location.id === selectedLocationId
      ? liveAirQuality.location
      : null) ??
    FALLBACK_LOCATIONS.find((loc) => loc.id === selectedLocationId) ??
    FALLBACK_LOCATIONS[0];

  const isLiveOrCached =
    (viewMode === "live-model" || viewMode === "stale-cached") &&
    liveAirQuality !== null &&
    liveAirQuality.location.id === selectedLocationId;
  const isLoadingLive = viewMode === "loading";
  const isDemoMode = viewMode === "demo-fallback";
  const isUnavailableMode = viewMode === "unavailable";

  // Build the 5 pollutant cards (PM2.5, PM10, NO2, O3, SO2) without ever mixing live and demo values
  const pollutantCards: DisplayPollutantCard[] = React.useMemo(() => {
    if (isLiveOrCached && liveAirQuality) {
      const originBadge =
        viewMode === "stale-cached" ? "Cached Model" : "Live Model";
      const items: PollutantMeasurement[] = [
        liveAirQuality.pm2_5,
        liveAirQuality.pm10,
        liveAirQuality.no2,
        liveAirQuality.o3,
        liveAirQuality.so2,
      ];
      return items.map((m) => {
        const isAvailable = m.status === "available" && m.value !== null;
        return {
          code: m.code,
          name: m.name,
          value: isAvailable ? m.value : null,
          unit: m.unit,
          availability: isAvailable ? "available" : "unavailable",
          concentrationLevel: isAvailable
            ? classifyConcentrationLevel(m.code, m.value)
            : "Unavailable",
          whoGuidelineRef: POLLUTANT_REFERENCE_METADATA[m.code].whoGuidelineRef,
          sourceHint: POLLUTANT_REFERENCE_METADATA[m.code].sourceHint,
          originBadge: isAvailable ? originBadge : "Data Unavailable",
        };
      });
    }

    if (isDemoMode) {
      const codes: Array<"PM2.5" | "PM10" | "NO2" | "O3" | "SO2"> = [
        "PM2.5",
        "PM10",
        "NO2",
        "O3",
        "SO2",
      ];
      return codes.map((code) => {
        const match = demoDashboard.pollutants.find((p) => p.code === code);
        if (match) {
          return {
            code,
            name: match.name,
            value: match.value,
            unit: match.unit,
            availability: "available",
            concentrationLevel: match.status,
            whoGuidelineRef: match.who_guideline_ref,
            sourceHint: match.source_hint,
            originBadge: "Demo Sample",
          };
        }
        return {
          code,
          name: "Sulphur Dioxide",
          value: null,
          unit: "µg/m³",
          availability: "demo-excluded",
          concentrationLevel: "Demo Excluded",
          whoGuidelineRef: POLLUTANT_REFERENCE_METADATA[code].whoGuidelineRef,
          sourceHint: POLLUTANT_REFERENCE_METADATA[code].sourceHint,
          originBadge: "Demo Excluded",
        };
      });
    }

    const codes: Array<{
      code: "PM2.5" | "PM10" | "NO2" | "O3" | "SO2";
      name: string;
    }> = [
      { code: "PM2.5", name: "Fine Particulate Matter (<2.5 µm)" },
      { code: "PM10", name: "Coarse Particulate Matter (<10 µm)" },
      { code: "NO2", name: "Nitrogen Dioxide" },
      { code: "O3", name: "Ground-Level Ozone" },
      { code: "SO2", name: "Sulphur Dioxide" },
    ];

    // Live request in progress: display explicit loading state (never DATA UNAVAILABLE or demo values)
    if (isLoadingLive) {
      return codes.map(({ code, name }) => ({
        code,
        name,
        value: null,
        unit: "µg/m³",
        availability: "loading",
        concentrationLevel: "Loading",
        whoGuidelineRef: POLLUTANT_REFERENCE_METADATA[code].whoGuidelineRef,
        sourceHint: POLLUTANT_REFERENCE_METADATA[code].sourceHint,
        originBadge: "Loading",
      }));
    }

    // Request failed / unavailable mode: never show demo numbers
    return codes.map(({ code, name }) => ({
      code,
      name,
      value: null,
      unit: "µg/m³",
      availability: "unavailable",
      concentrationLevel: "Unavailable",
      whoGuidelineRef: POLLUTANT_REFERENCE_METADATA[code].whoGuidelineRef,
      sourceHint: POLLUTANT_REFERENCE_METADATA[code].sourceHint,
      originBadge: "Data Unavailable",
    }));
  }, [isLiveOrCached, isLoadingLive, liveAirQuality, viewMode, isDemoMode, demoDashboard]);

  const futureForecastPoints = isLiveOrCached
    ? liveAirQuality?.hourly_forecast.points ?? []
    : [];

  const historicalModelCount = isLiveOrCached
    ? liveAirQuality?.hourly_forecast.historical_hours_count ?? 0
    : 0;

  const selectedPrompt =
    demoDashboard.assistant_preview.sample_prompts.find(
      (p) => p.id === activePromptId
    ) ?? demoDashboard.assistant_preview.sample_prompts[0];

  return (
    <div className="min-h-screen flex flex-col lg:flex-row bg-theme-main text-theme-text">
      {/* Skip to main content link for keyboard accessibility */}
      <a
        href="#main-dashboard"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-lg focus:bg-theme-accent focus:px-4 focus:py-2 focus:text-sm focus:font-bold focus:text-[#0B1415] focus:shadow-lg"
      >
        Skip to main dashboard content
      </a>

      {/* Left Sidebar / Responsive Navigation (#092C29) */}
      <aside
        aria-label="Primary Sidebar Navigation"
        className="w-full lg:w-72 bg-theme-sidebar text-theme-text lg:min-h-screen flex flex-col justify-between border-b lg:border-b-0 lg:border-r border-theme-border shrink-0"
      >
        <div className="p-5 lg:p-6">
          {/* Brand Identity */}
          <div className="flex items-center justify-between lg:justify-start gap-3">
            <div className="flex items-center gap-3.5">
              <div
                aria-hidden="true"
                className="h-10 w-10 rounded-xl bg-gradient-to-br from-theme-mint to-theme-accent flex items-center justify-center shadow-sm border border-theme-mint/40 text-[#092C29] font-black text-base tracking-tight"
              >
                AW
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-bold tracking-tight text-lg text-theme-text">
                    AIRWISE AI
                  </span>
                  {viewMode === "live-model" && (
                    <span className="rounded-full bg-emerald-500/15 border border-emerald-400/40 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-300">
                      CAMS Model
                    </span>
                  )}
                  {viewMode === "stale-cached" && (
                    <span className="rounded-full bg-amber-500/15 border border-amber-400/40 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-300">
                      Cached
                    </span>
                  )}
                  {viewMode === "demo-fallback" && (
                    <span className="rounded-full bg-amber-500/15 border border-amber-400/40 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-300">
                      Demo
                    </span>
                  )}
                  {viewMode === "unavailable" && (
                    <span className="rounded-full bg-red-500/15 border border-red-400/40 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-red-300">
                      Offline
                    </span>
                  )}
                </div>
                <p className="text-xs text-theme-muted">
                  Urban Air Quality Intelligence
                </p>
              </div>
            </div>
          </div>

          {/* Navigation Links */}
          <nav aria-label="Dashboard sections" className="mt-7">
            <p className="hidden lg:block text-[11px] font-semibold uppercase tracking-wider text-theme-muted mb-2.5 px-3">
              Environmental Modules
            </p>
            <ul className="flex lg:flex-col gap-1.5 overflow-x-auto pb-2 lg:pb-0">
              {[
                {
                  id: "overview",
                  label: "AQI Summary",
                  href: "#section-summary",
                },
                {
                  id: "map",
                  label: "Intelligence Map",
                  href: "#section-map",
                },
                {
                  id: "pollutants",
                  label: "Pollutant Cards (5)",
                  href: "#section-pollutants",
                },
                {
                  id: "forecast",
                  label: "Hourly Forecast",
                  href: "#section-forecast",
                },
                {
                  id: "intelligence",
                  label: "Risk Intelligence",
                  href: "#section-intelligence",
                },
                {
                  id: "history",
                  label: "Historical Trends",
                  href: "#section-history",
                },
                {
                  id: "provenance",
                  label: "Model Provenance",
                  href: "#section-provenance",
                },
                {
                  id: "advisory",
                  label: "Health Advisory",
                  href: "#section-advisory",
                },
                {
                  id: "recommendations",
                  label: "Daily Planning",
                  href: "#section-recommendations",
                },
                {
                  id: "assistant",
                  label: "AIRWISE AI Assistant",
                  href: "#section-assistant",
                },
              ].map((item) => {
                const isActive = activeSection === item.id;
                return (
                  <li key={item.id} className="shrink-0">
                    <a
                      href={item.href}
                      onClick={() => setActiveSection(item.id)}
                      aria-current={isActive ? "true" : undefined}
                      className={`flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint ${
                        isActive
                          ? "bg-[#14B8A6]/15 text-theme-mint border-[#14B8A6]/50 shadow-sm"
                          : "border-transparent text-theme-text/85 hover:bg-theme-secondary/70 hover:text-theme-text hover:border-theme-border"
                      }`}
                    >
                      <span
                        aria-hidden="true"
                        className={`h-1.5 w-1.5 rounded-full ${
                          isActive ? "bg-theme-mint" : "bg-theme-muted/60"
                        }`}
                      />
                      <span>{item.label}</span>
                    </a>
                  </li>
                );
              })}
            </ul>
          </nav>
        </div>

        {/* Sidebar System Status Footer */}
        <div className="p-5 lg:p-6 border-t border-theme-border bg-[#072220] space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="text-theme-muted">Data Integrity Mode</span>
            {viewMode === "live-model" && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-400/40 px-2.5 py-0.5 font-semibold text-emerald-300">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
                LIVE MODEL
              </span>
            )}
            {viewMode === "stale-cached" && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/15 border border-amber-400/40 px-2.5 py-0.5 font-semibold text-amber-300">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400" aria-hidden="true" />
                CACHED / STALE
              </span>
            )}
            {viewMode === "demo-fallback" && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/15 border border-amber-400/40 px-2.5 py-0.5 font-semibold text-amber-300">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400" aria-hidden="true" />
                DEMO / SAMPLE
              </span>
            )}
            {viewMode === "unavailable" && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/15 border border-red-400/40 px-2.5 py-0.5 font-semibold text-red-300">
                <span className="h-1.5 w-1.5 rounded-full bg-red-400" aria-hidden="true" />
                DATA UNAVAILABLE
              </span>
            )}
            {viewMode === "loading" && (
              <span className="text-theme-muted italic">Syncing...</span>
            )}
          </div>

          <div className="flex items-center justify-between text-xs">
            <span className="text-theme-muted">FastAPI Backend</span>
            {viewMode === "live-model" && (
              <span className="inline-flex items-center gap-1.5 text-theme-mint font-medium">
                <span className="h-2 w-2 rounded-full bg-emerald-400" aria-hidden="true" />
                Connected ({health?.version ?? "v0.2.0"})
              </span>
            )}
            {viewMode === "loading" && (
              <span className="text-theme-muted italic">Checking...</span>
            )}
            {viewMode === "stale-cached" && (
              <span className="inline-flex items-center gap-1.5 text-amber-300 font-medium">
                <span className="h-2 w-2 rounded-full bg-amber-400" aria-hidden="true" />
                Stale Cache Retained
              </span>
            )}
            {viewMode === "unavailable" && (
              <span className="inline-flex items-center gap-1.5 text-red-300 font-medium">
                <span className="h-2 w-2 rounded-full bg-red-400" aria-hidden="true" />
                Provider Unreachable
              </span>
            )}
            {viewMode === "demo-fallback" && (
              <span className="inline-flex items-center gap-1.5 text-amber-300 font-medium">
                <span className="h-2 w-2 rounded-full bg-amber-400" aria-hidden="true" />
                Demo Fallback Active
              </span>
            )}
          </div>

          <p className="text-[11px] leading-relaxed text-theme-muted">
            {isLiveOrCached
              ? "Open-Meteo CAMS Global (~0.4° / 45 km, 3-hourly native model output). Not physical roadside station telemetry."
              : "Live readings are never mixed with demo values. Missing or unreachable data is explicitly flagged."}
          </p>
        </div>
      </aside>

      {/* Main Content Area (#0B1415) */}
      <main id="main-dashboard" className="flex-1 min-w-0 bg-theme-main">
        {/* Persistent Top Data Provenance & Disclosure Banner */}
        <div
          role="region"
          aria-label="Environmental data provenance disclosure notice"
          aria-live="polite"
          className="bg-theme-card border-b border-theme-border px-4 py-3 sm:px-8"
        >
          <div className="max-w-7xl mx-auto flex flex-col xl:flex-row xl:items-center xl:justify-between gap-3">
            <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 min-w-0">
              {viewMode === "live-model" && liveAirQuality && (
                <>
                  <span className="inline-flex self-start sm:self-auto max-w-full sm:shrink-0 items-center rounded-md bg-emerald-500/20 border border-emerald-400/50 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-emerald-300">
                    {liveAirQuality.data_label}
                  </span>
                  <p className="min-w-0 text-xs sm:text-sm font-medium text-theme-text">
                    {liveAirQuality.provider} —{" "}
                    <span className="font-normal text-theme-muted">
                      {liveAirQuality.disclaimer}
                    </span>
                  </p>
                </>
              )}

              {viewMode === "stale-cached" && liveAirQuality && (
                <>
                  <span className="inline-flex self-start sm:self-auto max-w-full sm:shrink-0 items-center rounded-md bg-amber-500/20 border border-amber-400/50 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-amber-300">
                    CACHED / STALE — {liveAirQuality.data_label}
                  </span>
                  <p className="min-w-0 text-xs sm:text-sm font-medium text-theme-text">
                    Showing last verified model response from{" "}
                    {liveAirQuality.retrieval_time} —{" "}
                    <span className="font-normal text-theme-muted">
                      Live refresh failed ({errorMessage}). No demo values were substituted.
                    </span>
                  </p>
                </>
              )}

              {viewMode === "unavailable" && (
                <>
                  <span className="inline-flex self-start sm:self-auto max-w-full sm:shrink-0 items-center rounded-md bg-red-500/20 border border-red-400/50 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-red-300">
                    DATA UNAVAILABLE
                  </span>
                  <p className="min-w-0 text-xs sm:text-sm font-medium text-theme-text">
                    Live Open-Meteo model data could not be loaded for{" "}
                    {activeLocation.display_name}.{" "}
                    <span className="font-normal text-theme-muted">
                      Demo values are never silently substituted as live measurements. You may retry or switch to explicit Demo Data mode.
                    </span>
                  </p>
                </>
              )}

              {viewMode === "demo-fallback" && (
                <>
                  <span className="inline-flex self-start sm:self-auto max-w-full sm:shrink-0 items-center rounded-md bg-amber-500/20 border border-amber-400/50 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-amber-300">
                    DEMO DATA
                  </span>
                  <p className="min-w-0 text-xs sm:text-sm font-medium text-theme-text">
                    {demoDashboard.data_source_label} —{" "}
                    <span className="font-normal text-theme-muted">
                      {demoDashboard.disclaimer}
                    </span>
                  </p>
                </>
              )}

              {viewMode === "loading" && (
                <>
                  <span className="inline-flex self-start sm:self-auto max-w-full sm:shrink-0 items-center rounded-md bg-theme-secondary border border-theme-accent/50 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-theme-mint">
                    SYNCING LIVE MODEL
                  </span>
                  <p className="min-w-0 text-xs sm:text-sm font-medium text-theme-muted">
                    Requesting Open-Meteo CAMS Global model estimates for{" "}
                    <strong className="text-theme-text">
                      {activeLocation.display_name}
                    </strong>{" "}
                    from FastAPI backend...
                  </p>
                </>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2 shrink-0 self-start xl:self-auto">
              <button
                type="button"
                onClick={() => void loadLiveLocationData(selectedLocationId)}
                disabled={viewMode === "loading"}
                className="rounded-lg border border-theme-border bg-theme-secondary px-3.5 py-1.5 text-xs font-semibold text-theme-mint hover:border-theme-accent hover:bg-[#213B37] focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint disabled:opacity-50 transition-colors"
              >
                {isDemoMode ? "Switch to Live Model Data" : "Refresh Live Model"}
              </button>
              {!isDemoMode && (
                <button
                  type="button"
                  onClick={handleActivateExplicitDemoFallback}
                  className="rounded-lg border border-amber-500/40 bg-amber-950/40 px-3 py-1.5 text-xs font-semibold text-amber-300 hover:bg-amber-950/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 transition-colors"
                >
                  Use Demo Data Mode
                </button>
              )}
            </div>
          </div>
        </div>

        <div
          aria-busy={viewMode === "loading"}
          className="max-w-7xl mx-auto px-4 sm:px-8 py-6 sm:py-8 space-y-8"
        >
          {/* Top Header & Location Selector (Default: Lagos, Nigeria) */}
          <header className="flex flex-col lg:flex-row lg:items-end justify-between gap-5 border-b border-theme-border pb-6">
            <div className="space-y-2">
              <div className="inline-flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wider text-theme-mint">
                <span className="h-2 w-2 rounded-full bg-theme-accent" aria-hidden="true" />
                <span>Urban Environmental Intelligence</span>
                <span aria-hidden="true">•</span>
                <span>
                  {isLiveOrCached
                    ? "LIVE PROVIDER DATA — MODEL-BASED ESTIMATE"
                    : isDemoMode
                    ? "DEMO DATA FALLBACK MODE"
                    : viewMode === "loading"
                    ? "LOADING LIVE MODEL"
                    : "DATA UNAVAILABLE"}
                </span>
              </div>
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-theme-text">
                {activeLocation.display_name} Air Quality Dashboard
              </h1>
              <p className="text-xs sm:text-sm text-theme-muted">
                Configured Coordinates: {activeLocation.latitude.toFixed(4)}°,{" "}
                {activeLocation.longitude.toFixed(4)}° • Timezone:{" "}
                <strong className="text-theme-text font-semibold">
                  {isLiveOrCached && liveAirQuality
                    ? liveAirQuality.timezone
                    : activeLocation.timezone}
                </strong>
                {isLiveOrCached && liveAirQuality?.timezone_abbreviation
                  ? ` (${liveAirQuality.timezone_abbreviation})`
                  : ""}
              </p>

              {/* Quick City Switcher Pills for Rapid Interaction & Feedback */}
              <div
                role="group"
                aria-label="Quick urban location switcher"
                className="pt-1 flex flex-wrap items-center gap-2"
              >
                {FALLBACK_LOCATIONS.map((loc) => {
                  const isSelected = loc.id === selectedLocationId;
                  return (
                    <button
                      key={loc.id}
                      type="button"
                      onClick={() => handleQuickLocationSelect(loc.id)}
                      aria-pressed={isSelected}
                      className={`rounded-lg px-3 py-1.5 text-xs font-semibold border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint ${
                        isSelected
                          ? "bg-[#14B8A6]/20 text-theme-mint border-theme-accent shadow-sm"
                          : "bg-theme-card text-theme-muted border-theme-border hover:bg-theme-secondary hover:text-theme-text"
                      }`}
                    >
                      {loc.city}, {loc.country}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Accessible Select Dropdown connected to lagos-ng, abuja-ng, nairobi-ke, accra-gh */}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 bg-theme-card p-3.5 rounded-xl border border-theme-border shrink-0">
              <div className="flex flex-col">
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <label
                    htmlFor="location-selector"
                    className="text-xs font-semibold text-theme-muted"
                  >
                    Monitored Urban Location
                  </label>
                  {viewMode === "loading" && (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-theme-mint">
                      <span
                        aria-hidden="true"
                        className="h-2.5 w-2.5 rounded-full border-2 border-theme-mint border-t-transparent animate-spin"
                      />
                      Updating...
                    </span>
                  )}
                </div>
                <select
                  id="location-selector"
                  name="location"
                  value={selectedLocationId}
                  onChange={handleLocationChange}
                  aria-describedby="location-selector-hint"
                  className="rounded-lg border border-theme-border bg-theme-secondary px-3.5 py-2 text-sm font-semibold text-theme-text focus:border-theme-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint"
                >
                  {FALLBACK_LOCATIONS.map((loc) => (
                    <option
                      key={loc.id}
                      value={loc.id}
                      className="bg-[#142321] text-[#F1F5F4]"
                    >
                      {loc.display_name} ({loc.region})
                    </option>
                  ))}
                </select>
                <span
                  id="location-selector-hint"
                  className="mt-1 text-[11px] text-theme-muted"
                >
                  Location ID: <code className="text-theme-mint">{selectedLocationId}</code>
                </span>
              </div>
            </div>
          </header>

          {/* Loading State Banner */}
          {viewMode === "loading" && (
            <div
              role="status"
              aria-live="polite"
              className="rounded-xl border border-theme-accent/40 bg-theme-card p-4 flex items-center gap-3 text-theme-text"
            >
              <div
                aria-hidden="true"
                className="h-4 w-4 rounded-full border-2 border-theme-mint border-t-transparent animate-spin shrink-0"
              />
              <p className="text-sm font-medium text-theme-text">
                Fetching Open-Meteo CAMS Global model estimates for{" "}
                <strong>{activeLocation.display_name}</strong> from FastAPI (
                <code>/api/v1/air-quality?location_id={selectedLocationId}</code>)...
              </p>
            </div>
          )}

          {/* Stale / Cached Warning Banner */}
          {viewMode === "stale-cached" && liveAirQuality && (
            <div
              role="alert"
              aria-live="assertive"
              className="rounded-xl border border-amber-400/50 bg-theme-card p-4 sm:p-5 text-theme-text"
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-amber-500/20 border border-amber-400/50 px-2 py-0.5 text-xs font-bold uppercase text-amber-300">
                      Cached / Stale Live Model Response
                    </span>
                    <h2 className="text-sm font-bold text-theme-text">
                      Refresh Failed — Preserving Last Verified Model Estimate for{" "}
                      {liveAirQuality.location.display_name}
                    </h2>
                  </div>
                  <p className="text-xs sm:text-sm text-theme-muted">
                    Error: {errorMessage}. Showing cached model observation from{" "}
                    <strong className="text-theme-text">
                      {liveAirQuality.observation_time}
                    </strong>{" "}
                    (retrieved at {liveAirQuality.retrieval_time}). Demo values were not mixed.
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => void loadLiveLocationData(selectedLocationId)}
                    className="rounded-lg bg-theme-accent px-3.5 py-2 text-xs font-bold text-[#0B1415] hover:bg-theme-mint focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint transition-colors"
                  >
                    Retry Live API
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Error / Data Unavailable Banner (No Silent Demo Fallback) */}
          {isUnavailableMode && (
            <div
              role="alert"
              aria-live="assertive"
              className="rounded-xl border border-red-500/40 bg-theme-card p-4 sm:p-5 text-theme-text"
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-red-500/20 border border-red-400/40 px-2 py-0.5 text-xs font-bold uppercase text-red-300">
                      DATA UNAVAILABLE
                    </span>
                    <h2 className="text-sm font-bold text-theme-text">
                      Live Air Quality Endpoint Unreachable — No Demo Data Substituted
                    </h2>
                  </div>
                  <p className="text-xs sm:text-sm text-theme-muted">
                    Could not retrieve live model estimates from{" "}
                    <code>GET /api/v1/air-quality?location_id={selectedLocationId}</code> (
                    {errorMessage}). To uphold data integrity, AIRWISE AI displays{" "}
                    <strong className="text-theme-text">DATA UNAVAILABLE</strong> rather than
                    silently presenting sample demo values as live measurements.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2.5 shrink-0">
                  <button
                    type="button"
                    onClick={() => void loadLiveLocationData(selectedLocationId)}
                    className="rounded-lg bg-theme-accent px-3.5 py-2 text-xs font-bold text-[#0B1415] hover:bg-theme-mint focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint transition-colors"
                  >
                    Retry Live Endpoint
                  </button>
                  <button
                    type="button"
                    onClick={handleActivateExplicitDemoFallback}
                    className="rounded-lg border border-amber-400/50 bg-theme-secondary px-3.5 py-2 text-xs font-semibold text-amber-300 hover:border-amber-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 transition-colors"
                  >
                    Switch to Explicit Demo Mode
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Explicit Demo Mode Notice Banner */}
          {isDemoMode && (
            <div
              role="status"
              aria-live="polite"
              className="rounded-xl border border-amber-400/40 bg-theme-card p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-theme-text"
            >
              <p className="text-xs sm:text-sm text-theme-muted">
                <strong className="text-amber-300">DEMO DATA FALLBACK ACTIVE:</strong> You have explicitly selected simulated sample scenarios for{" "}
                <span className="text-theme-text font-medium">
                  {activeLocation.display_name}
                </span>
                . These numbers are not live Open-Meteo CAMS outputs.
              </p>
              <button
                type="button"
                onClick={() => void loadLiveLocationData(selectedLocationId)}
                className="self-start sm:self-auto rounded-lg border border-theme-accent/50 bg-theme-secondary px-3.5 py-1.5 text-xs font-semibold text-theme-mint hover:bg-[#213B37] focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint transition-colors"
              >
                Load Live Open-Meteo Data
              </button>
            </div>
          )}

          {/* 1. Air Quality Summary Area */}
          <section
            id="section-summary"
            aria-labelledby="heading-aqi-summary"
            className="rounded-2xl bg-theme-card border border-theme-border overflow-hidden"
          >
            <div className="bg-theme-secondary/90 border-b border-theme-border px-6 py-4 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <span
                  aria-hidden="true"
                  className={`h-2.5 w-2.5 rounded-full ${
                    isLiveOrCached
                      ? getAqiAccentIndicatorStyle(liveAirQuality?.aqi.band ?? null)
                      : isDemoMode
                      ? getAqiAccentIndicatorStyle(demoDashboard.summary.aqi_band)
                      : "bg-slate-500"
                  }`}
                />
                <h2
                  id="heading-aqi-summary"
                  className="text-base font-bold tracking-tight text-theme-text"
                >
                  Urban Air Quality Summary — {activeLocation.display_name}
                </h2>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {isLiveOrCached && liveAirQuality && (
                  <>
                    <span className="rounded-full bg-emerald-500/15 border border-emerald-400/40 px-3 py-1 text-xs font-bold text-emerald-300">
                      {viewMode === "stale-cached"
                        ? "CACHED / STALE — LIVE PROVIDER DATA"
                        : liveAirQuality.data_label}
                    </span>
                    <span className="rounded-full bg-theme-card border border-theme-border px-3 py-1 text-xs font-medium text-theme-muted">
                      Model Observation: {liveAirQuality.observation_time} (
                      {liveAirQuality.timezone_abbreviation ?? liveAirQuality.timezone})
                    </span>
                  </>
                )}
                {isDemoMode && (
                  <span className="rounded-full bg-amber-500/15 border border-amber-400/40 px-3 py-1 text-xs font-bold text-amber-300">
                    DEMO DATA — {demoDashboard.summary.reference_timestamp_label}
                  </span>
                )}
                {isUnavailableMode && (
                  <span className="rounded-full bg-red-500/15 border border-red-400/40 px-3 py-1 text-xs font-bold text-red-300">
                    DATA UNAVAILABLE
                  </span>
                )}
              </div>
            </div>

            <div className="p-6 grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
              {/* Headline AQI Metric Box */}
              <div className="lg:col-span-4 rounded-xl bg-theme-secondary border border-theme-border p-5 flex flex-col justify-between">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-theme-mint">
                    {isLiveOrCached
                      ? liveAirQuality?.aqi.standard ?? "US EPA AQI (Model Output)"
                      : isDemoMode
                      ? "Sample US EPA AQI"
                      : "US EPA AQI"}
                  </span>
                  {isLiveOrCached && (
                    <span className="rounded bg-emerald-500/15 border border-emerald-400/40 px-2 py-0.5 text-[11px] font-bold uppercase text-emerald-300">
                      {viewMode === "stale-cached" ? "Cached Model" : "Current Model"}
                    </span>
                  )}
                  {isDemoMode && (
                    <span className="rounded bg-amber-500/15 border border-amber-400/40 px-2 py-0.5 text-[11px] font-bold uppercase text-amber-300">
                      Demo Metric
                    </span>
                  )}
                  {isUnavailableMode && (
                    <span className="rounded bg-red-500/15 border border-red-400/40 px-2 py-0.5 text-[11px] font-bold uppercase text-red-300">
                      Unavailable
                    </span>
                  )}
                </div>

                {/* AQI Value Display */}
                <div className="my-5 flex items-baseline gap-3">
                  {isLiveOrCached && liveAirQuality ? (
                    liveAirQuality.aqi.status === "available" &&
                    liveAirQuality.aqi.value !== null ? (
                      <>
                        <span
                          className="text-5xl font-black tracking-tight text-theme-text"
                          aria-label={`US AQI value ${liveAirQuality.aqi.value}`}
                        >
                          {liveAirQuality.aqi.value}
                        </span>
                        <span className="text-xs font-semibold text-theme-muted">
                          {liveAirQuality.aqi.unit} (0–500 scale)
                        </span>
                      </>
                    ) : (
                      <span className="text-2xl font-bold text-slate-300">
                        DATA UNAVAILABLE
                      </span>
                    )
                  ) : isDemoMode ? (
                    <>
                      <span
                        className="text-5xl font-black tracking-tight text-theme-text"
                        aria-label={`Demo AQI value ${demoDashboard.summary.aqi_value}`}
                      >
                        {demoDashboard.summary.aqi_value}
                      </span>
                      <span className="text-xs font-semibold text-theme-muted">
                        / 500 (Demo)
                      </span>
                    </>
                  ) : (
                    <span className="text-2xl font-bold text-slate-300">
                      {viewMode === "loading" ? "Loading..." : "DATA UNAVAILABLE"}
                    </span>
                  )}
                </div>

                {/* AQI Category Band & Scale Legend Bar */}
                <div className="space-y-3">
                  {isLiveOrCached && liveAirQuality ? (
                    <>
                      <span
                        className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1 text-xs font-bold ${getAqiBadgeStyle(
                          liveAirQuality.aqi.band
                        )}`}
                      >
                        <span
                          aria-hidden="true"
                          className={`h-2 w-2 rounded-full ${getAqiAccentIndicatorStyle(
                            liveAirQuality.aqi.band
                          )}`}
                        />
                        {liveAirQuality.aqi.band ?? "Classification Unavailable"}
                      </span>
                      <p className="text-xs text-theme-muted">
                        Temporal Classification:{" "}
                        <strong className="font-bold text-theme-mint">
                          {liveAirQuality.current_conditions.classification}
                        </strong>{" "}
                        (Current Analysis)
                      </p>
                    </>
                  ) : isDemoMode ? (
                    <>
                      <span
                        className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1 text-xs font-bold ${getAqiBadgeStyle(
                          demoDashboard.summary.aqi_band
                        )}`}
                      >
                        <span
                          aria-hidden="true"
                          className={`h-2 w-2 rounded-full ${getAqiAccentIndicatorStyle(
                            demoDashboard.summary.aqi_band
                          )}`}
                        />
                        {demoDashboard.summary.aqi_band}
                      </span>
                      <p className="text-xs text-theme-muted">
                        Dominant Pollutant (Demo):{" "}
                        <strong className="font-bold text-amber-300">
                          {demoDashboard.summary.dominant_pollutant}
                        </strong>
                      </p>
                    </>
                  ) : (
                    <span className="inline-block rounded-lg border border-slate-600/50 bg-slate-900/90 px-3 py-1 text-xs font-bold text-slate-300">
                      DATA UNAVAILABLE
                    </span>
                  )}

                  {/* Accessible US EPA AQI Reference Scale Legend */}
                  <div
                    aria-label="US EPA AQI Category Reference Legend"
                    className="pt-2.5 border-t border-theme-border/80 flex flex-wrap gap-1.5 text-[10px] text-theme-muted"
                  >
                    <span className="inline-flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
                      0–50 Good
                    </span>
                    <span>•</span>
                    <span className="inline-flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-yellow-400" aria-hidden="true" />
                      51–100 Mod
                    </span>
                    <span>•</span>
                    <span className="inline-flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-orange-400" aria-hidden="true" />
                      101–150 USG
                    </span>
                    <span>•</span>
                    <span className="inline-flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-red-400" aria-hidden="true" />
                      151–200 Unhealthy
                    </span>
                    <span>•</span>
                    <span className="inline-flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-purple-400" aria-hidden="true" />
                      201+ Very Unhealthy
                    </span>
                  </div>
                </div>
              </div>

              {/* Timestamps, Provider Provenance & Methodology Summary */}
              <div className="lg:col-span-8 flex flex-col justify-between space-y-4">
                <div className="rounded-xl bg-theme-secondary border border-theme-border p-4">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-theme-mint mb-1.5">
                    {isLiveOrCached
                      ? "Atmospheric Model Summary & Provenance"
                      : isDemoMode
                      ? "Scenario Interpretation (Explicit Demo Data)"
                      : "Live Provider Status"}
                  </h3>
                  <p className="text-sm sm:text-base font-medium text-theme-text leading-relaxed">
                    {isLiveOrCached && liveAirQuality
                      ? liveAirQuality.disclaimer
                      : isDemoMode
                      ? demoDashboard.summary.summary_statement
                      : "Live model estimates are currently unavailable. No demo values are displayed in live mode."}
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="rounded-xl border border-theme-border p-4 bg-theme-secondary/60">
                    <span className="block text-xs font-semibold uppercase tracking-wider text-theme-muted">
                      Model Observation Time
                    </span>
                    <p className="mt-1.5 text-sm font-bold text-theme-text">
                      {isLiveOrCached && liveAirQuality
                        ? `${liveAirQuality.observation_time} (${liveAirQuality.timezone})`
                        : isDemoMode
                        ? "Demo Baseline Scenario"
                        : "DATA UNAVAILABLE"}
                    </p>
                  </div>

                  <div className="rounded-xl border border-theme-border p-4 bg-theme-secondary/60">
                    <span className="block text-xs font-semibold uppercase tracking-wider text-theme-muted">
                      UTC Retrieval Timestamp
                    </span>
                    <p className="mt-1.5 text-sm font-bold text-theme-text">
                      {isLiveOrCached && liveAirQuality
                        ? liveAirQuality.retrieval_time
                        : isDemoMode
                        ? "Offline Sample Dataset"
                        : "DATA UNAVAILABLE"}
                    </p>
                  </div>

                  <div className="rounded-xl border border-theme-border p-4 bg-theme-secondary/60">
                    <span className="block text-xs font-semibold uppercase tracking-wider text-theme-muted">
                      Spatial & Temporal Resolution
                    </span>
                    <p className="mt-1.5 text-xs font-semibold text-theme-mint leading-snug">
                      {isLiveOrCached && liveAirQuality
                        ? `${liveAirQuality.provenance.spatial_resolution} • ${liveAirQuality.provenance.source_temporal_resolution}`
                        : isDemoMode
                        ? "Simulated Demo Scenario"
                        : "CAMS Global (~45 km / 3-hourly)"}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* 1.5 Air Quality Intelligence Map (Synchronized with Location Selector) */}
          <AirQualityMapSection
            selectedLocationId={selectedLocationId}
            onSelectLocation={handleQuickLocationSelect}
            isDashboardDemoMode={isDemoMode}
            latestSelectedCityData={isLiveOrCached ? liveAirQuality : null}
          />

          {/* 2. Pollutant Breakdown Cards (PM2.5, PM10, NO2, O3, SO2) */}
          <section id="section-pollutants" aria-labelledby="heading-pollutants">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
              <div>
                <h2 id="heading-pollutants" className="text-xl font-bold text-theme-text">
                  Atmospheric Pollutant Concentrations (PM2.5, PM10, NO2, O3, SO2)
                </h2>
                <p className="text-sm text-theme-muted" aria-live="polite">
                  {isLiveOrCached
                    ? `Current CAMS Global model estimates (~45 km grid average) for ${activeLocation.display_name}. Missing variables are reported individually as DATA UNAVAILABLE.`
                    : isLoadingLive
                    ? `Loading live CAMS Global model estimates for ${activeLocation.display_name}...`
                    : isDemoMode
                    ? `Explicit demo pollutant profiles for ${activeLocation.display_name}.`
                    : `Live pollutant readings for ${activeLocation.display_name} are currently unavailable.`}
                </p>
              </div>
              <span className="self-start sm:self-auto rounded-md bg-theme-secondary border border-theme-border px-3 py-1 text-xs font-semibold text-theme-mint">
                5 Monitored Pollutants
              </span>
            </div>

            <div
              className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4"
              aria-busy={isLoadingLive}
            >
              {pollutantCards.map((pollutant) => (
                <article
                  key={pollutant.code}
                  aria-label={`${pollutant.code} measurement card`}
                  className="rounded-2xl bg-theme-card border border-theme-border p-5 flex flex-col justify-between hover:border-theme-accent/60 transition-colors"
                >
                  <div>
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <span className="inline-block text-lg font-extrabold text-theme-mint">
                          {pollutant.code}
                        </span>
                        <h3 className="text-xs font-medium text-theme-muted">
                          {pollutant.name}
                        </h3>
                      </div>
                      <span
                        className={`rounded-full border px-2.5 py-0.5 text-[11px] font-bold shrink-0 ${getPollutantStatusStyle(
                          pollutant.concentrationLevel
                        )}`}
                      >
                        {pollutant.concentrationLevel === "Unavailable"
                          ? "DATA UNAVAILABLE"
                          : pollutant.concentrationLevel}
                      </span>
                    </div>

                    <div className="my-5 flex items-baseline gap-1.5 flex-wrap">
                      {pollutant.availability === "available" &&
                      pollutant.value !== null ? (
                        <>
                          <span className="text-3xl font-black text-theme-text">
                            {pollutant.value}
                          </span>
                          <span className="text-xs font-semibold text-theme-muted">
                            {pollutant.unit}
                          </span>
                        </>
                      ) : pollutant.availability === "loading" ? (
                        <span
                          role="status"
                          className="text-sm font-semibold text-theme-mint py-1 animate-pulse"
                        >
                          Loading live model...
                        </span>
                      ) : pollutant.availability === "demo-excluded" ? (
                        <span className="text-sm font-semibold text-amber-200 py-1">
                          Not included in demo scenario
                        </span>
                      ) : (
                        <span className="text-base font-bold text-slate-300 py-1">
                          DATA UNAVAILABLE
                        </span>
                      )}

                      <span
                        className={`ml-auto text-[10px] font-bold uppercase rounded px-1.5 py-0.5 border ${
                          pollutant.originBadge === "Live Model"
                            ? "text-emerald-300 bg-emerald-500/15 border-emerald-400/35"
                            : pollutant.originBadge === "Cached Model"
                            ? "text-amber-300 bg-amber-500/15 border-amber-400/35"
                            : pollutant.originBadge === "Demo Sample" ||
                              pollutant.originBadge === "Demo Excluded"
                            ? "text-amber-300 bg-amber-500/15 border-amber-400/35"
                            : pollutant.originBadge === "Loading"
                            ? "text-theme-mint bg-teal-500/15 border-theme-accent/40"
                            : "text-slate-300 bg-slate-800 border-slate-600/50"
                        }`}
                      >
                        {pollutant.originBadge}
                      </span>
                    </div>
                  </div>

                  <div className="pt-3.5 border-t border-theme-border space-y-1.5 text-xs">
                    <p className="font-semibold text-theme-mint">
                      {pollutant.whoGuidelineRef}
                    </p>
                    <p className="text-theme-muted leading-snug">
                      <strong className="text-theme-text">Typical Source:</strong>{" "}
                      {pollutant.sourceHint}
                    </p>
                  </div>
                </article>
              ))}
            </div>
          </section>

          {/* 3. Future Hourly Forecast Timeline (Strictly > observation_time) */}
          <section
            id="section-forecast"
            aria-labelledby="heading-hourly-forecast"
            className="rounded-2xl bg-theme-card border border-theme-border p-6"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-theme-border pb-4">
              <div>
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <span className="rounded bg-teal-500/15 border border-theme-accent/40 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider text-theme-mint">
                    HOURLY FORECAST (FUTURE MODEL POINTS ONLY)
                  </span>
                  {isLiveOrCached && (
                    <span className="rounded bg-theme-secondary border border-theme-border px-2.5 py-0.5 text-xs font-medium text-theme-muted">
                      HISTORICAL MODEL DATA EXCLUDED ({historicalModelCount} earlier hours omitted)
                    </span>
                  )}
                </div>
                <h2
                  id="heading-hourly-forecast"
                  className="text-xl font-bold text-theme-text"
                >
                  Future Hourly Atmospheric Model Forecast — {activeLocation.display_name}
                </h2>
                <p className="text-xs sm:text-sm text-theme-muted mt-1">
                  Displays only future timestamps strictly later than the current model observation time (
                  <code>{liveAirQuality?.observation_time ?? "current_model"}</code>). Interpolated to 1-hourly API intervals from 3-hourly CAMS Global model fields.
                </p>
              </div>

              {isLiveOrCached && liveAirQuality && (
                <div className="text-xs text-theme-muted shrink-0 bg-theme-secondary border border-theme-border rounded-xl px-3.5 py-2">
                  <div>
                    Future Hours Returned:{" "}
                    <strong className="text-theme-mint">
                      {futureForecastPoints.length} hrs
                    </strong>
                  </div>
                  <div>
                    Timezone:{" "}
                    <strong className="text-theme-text">
                      {liveAirQuality.timezone}
                    </strong>
                  </div>
                </div>
              )}
            </div>

            {isLiveOrCached && futureForecastPoints.length > 0 ? (
              <div className="mt-5 space-y-4">
                {/* Visual AQI Bar Timeline */}
                <div
                  role="list"
                  aria-label="Future hourly forecast timeline cards"
                  className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3"
                >
                  {futureForecastPoints.slice(0, 12).map((point, index) => {
                    const barHeightPercent =
                      point.us_aqi !== null
                        ? Math.max(15, Math.min(100, Math.round((point.us_aqi / 200) * 100)))
                        : 15;
                    const hoursAhead = index + 1;
                    return (
                      <div
                        key={point.time}
                        role="listitem"
                        className="rounded-xl bg-theme-secondary border border-theme-border p-3.5 flex flex-col justify-between"
                      >
                        <div className="flex items-center justify-between gap-1 text-xs">
                          <span className="font-bold text-theme-text">
                            {formatHourLabel(point.time)}
                          </span>
                          <span className="text-[10px] font-semibold uppercase text-theme-mint bg-theme-card border border-theme-border rounded px-1.5 py-0.5">
                            +{hoursAhead}h Forecast
                          </span>
                        </div>
                        <span className="text-[11px] text-theme-muted">
                          {formatDateShort(point.time)}
                        </span>

                        {/* Mini visual bar */}
                        <div className="my-3 h-14 w-full bg-theme-card rounded-lg p-1.5 flex items-end border border-theme-border/70">
                          <div
                            aria-hidden="true"
                            style={{ height: `${barHeightPercent}%` }}
                            className={`w-full rounded border transition-all ${getAqiBarColorStyle(
                              point.us_aqi
                            )}`}
                          />
                        </div>

                        <div className="space-y-1 text-xs">
                          <div className="flex items-baseline justify-between">
                            <span className="text-theme-muted">US AQI</span>
                            <span className="font-extrabold text-theme-text">
                              {point.us_aqi !== null ? point.us_aqi : "N/A"}
                            </span>
                          </div>
                          <div className="flex items-baseline justify-between text-[11px]">
                            <span className="text-theme-muted">PM2.5</span>
                            <span className="font-semibold text-theme-mint">
                              {point.pm2_5 !== null ? `${point.pm2_5} µg/m³` : "N/A"}
                            </span>
                          </div>
                          <div className="flex items-baseline justify-between text-[11px]">
                            <span className="text-theme-muted">PM10</span>
                            <span className="font-medium text-theme-text">
                              {point.pm10 !== null ? `${point.pm10} µg/m³` : "N/A"}
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Accessible Tabular Summary for Remaining / Full 24h Forecast Window */}
                <details className="rounded-xl bg-theme-secondary/70 border border-theme-border p-4 group">
                  <summary className="cursor-pointer text-xs sm:text-sm font-semibold text-theme-mint focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint rounded px-1 py-0.5">
                    View Full Future Hourly Forecast Table ({futureForecastPoints.length} future model points)
                  </summary>
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full text-left border-collapse text-xs">
                      <caption className="sr-only">
                        Future hourly atmospheric model forecast values for {activeLocation.display_name} in timezone {liveAirQuality.timezone}. Historical hours are excluded.
                      </caption>
                      <thead>
                        <tr className="border-b border-theme-border text-theme-muted uppercase">
                          <th scope="col" className="py-2 pr-3">
                            Local Timestamp ({liveAirQuality.timezone_abbreviation ?? liveAirQuality.timezone})
                          </th>
                          <th scope="col" className="py-2 px-3">Classification</th>
                          <th scope="col" className="py-2 px-3">US AQI</th>
                          <th scope="col" className="py-2 px-3">PM2.5 (µg/m³)</th>
                          <th scope="col" className="py-2 px-3">PM10 (µg/m³)</th>
                          <th scope="col" className="py-2 px-3">NO2 (µg/m³)</th>
                          <th scope="col" className="py-2 px-3">O3 (µg/m³)</th>
                          <th scope="col" className="py-2 pl-3">SO2 (µg/m³)</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-theme-border/60">
                        {futureForecastPoints.map((pt) => (
                          <tr key={pt.time} className="hover:bg-theme-card/50">
                            <th
                              scope="row"
                              className="py-2 pr-3 font-semibold text-theme-text whitespace-nowrap"
                            >
                              {pt.time}
                            </th>
                            <td className="py-2 px-3">
                              <span className="rounded bg-teal-500/15 border border-theme-accent/40 px-2 py-0.5 text-[11px] font-semibold text-theme-mint">
                                {pt.classification}
                              </span>
                            </td>
                            <td className="py-2 px-3 font-bold text-theme-text">
                              {pt.us_aqi ?? "DATA UNAVAILABLE"}
                            </td>
                            <td className="py-2 px-3 text-theme-text">
                              {pt.pm2_5 ?? "DATA UNAVAILABLE"}
                            </td>
                            <td className="py-2 px-3 text-theme-text">
                              {pt.pm10 ?? "DATA UNAVAILABLE"}
                            </td>
                            <td className="py-2 px-3 text-theme-text">
                              {pt.no2 ?? "DATA UNAVAILABLE"}
                            </td>
                            <td className="py-2 px-3 text-theme-text">
                              {pt.o3 ?? "DATA UNAVAILABLE"}
                            </td>
                            <td className="py-2 pl-3 text-theme-text">
                              {pt.so2 ?? "DATA UNAVAILABLE"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </div>
            ) : (
              <div className="mt-5 rounded-xl bg-theme-secondary border border-theme-border p-5 text-sm text-theme-muted">
                {isDemoMode
                  ? "Hourly model forecast series is not displayed in Demo Data mode so simulated values are never confused with CAMS Global model forecasts."
                  : viewMode === "loading"
                  ? "Loading future hourly model forecast series..."
                  : "DATA UNAVAILABLE — No future hourly forecast points are currently available from the provider."}
              </div>
            )}
          </section>

          {/* 3.25 Deterministic Predictive Intelligence & Risk Insights */}
          <PredictiveIntelligenceSection
            selectedLocation={activeLocation}
            isDashboardDemoMode={isDemoMode}
          />

          {/* 3.5 Historical Air Quality Trends & 4-City Comparison */}
          <HistoricalTrendsSection
            selectedLocation={activeLocation}
            isDashboardDemoMode={isDemoMode}
          />

          {/* 4. Data Provenance, CAMS Global Resolution & Attribution Section */}
          <section
            id="section-provenance"
            aria-labelledby="heading-provenance"
            className="rounded-2xl bg-theme-card border border-theme-border p-6"
          >
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-theme-border pb-4">
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-theme-mint">
                  Scientific Transparency & Attribution
                </span>
                <h2 id="heading-provenance" className="text-xl font-bold text-theme-text mt-0.5">
                  Atmospheric Model Provenance & CAMS Global Specifications
                </h2>
              </div>
              <span className="rounded-full bg-theme-secondary border border-theme-border px-3 py-1 text-xs font-semibold text-theme-mint">
                Not Physical Roadside Sensor Telemetry
              </span>
            </div>

            <div className="mt-5 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="rounded-xl bg-theme-secondary border border-theme-border p-4">
                <span className="text-xs font-semibold uppercase tracking-wider text-theme-muted">
                  Spatial Grid Resolution
                </span>
                <p className="mt-1.5 text-sm font-bold text-theme-text">
                  {liveAirQuality?.provenance.spatial_resolution ??
                    "Approximately 0.4° (~45 km)"}
                </p>
                <p className="mt-1 text-xs text-theme-muted">
                  Regional background grid cell estimate; does not resolve street-canyon traffic micro-hotspots or exact street-corner exposure.
                </p>
              </div>

              <div className="rounded-xl bg-theme-secondary border border-theme-border p-4">
                <span className="text-xs font-semibold uppercase tracking-wider text-theme-muted">
                  Native Source Temporal Resolution
                </span>
                <p className="mt-1.5 text-sm font-bold text-theme-text">
                  {liveAirQuality?.provenance.source_temporal_resolution ??
                    "3-hourly underlying atmospheric model output"}
                </p>
                <p className="mt-1 text-xs text-theme-muted">
                  {liveAirQuality?.provenance.api_timestamp_interval ??
                    "1-hourly API timestamps are interpolated from 3-hourly CAMS Global fields (not independent hourly physical measurements)."}
                </p>
              </div>

              <div className="rounded-xl bg-theme-secondary border border-theme-border p-4">
                <span className="text-xs font-semibold uppercase tracking-wider text-theme-muted">
                  Model Domain & Horizon
                </span>
                <p className="mt-1.5 text-sm font-bold text-theme-text">
                  CAMS Global (<code>{liveAirQuality?.provenance.model_domain ?? "cams_global"}</code>)
                </p>
                <p className="mt-1 text-xs text-theme-muted">
                  Forecast availability:{" "}
                  {liveAirQuality?.provenance.forecast_availability ??
                    "Up to 5 days, subject to provider availability"}
                  .
                </p>
              </div>

              <div className="rounded-xl bg-theme-secondary border border-theme-border p-4">
                <span className="text-xs font-semibold uppercase tracking-wider text-theme-muted">
                  Grid Cell Center Coordinates
                </span>
                <p className="mt-1.5 text-sm font-bold text-theme-text">
                  {liveAirQuality?.provenance.provider_latitude !== null &&
                  liveAirQuality?.provenance.provider_latitude !== undefined &&
                  liveAirQuality?.provenance.provider_longitude !== null &&
                  liveAirQuality?.provenance.provider_longitude !== undefined
                    ? `${liveAirQuality.provenance.provider_latitude.toFixed(4)}°, ${liveAirQuality.provenance.provider_longitude.toFixed(4)}°`
                    : `${activeLocation.latitude.toFixed(4)}°, ${activeLocation.longitude.toFixed(4)}°`}
                </p>
                <p className="mt-1 text-xs text-theme-muted">
                  Physical Station Measurement:{" "}
                  <strong className="text-theme-mint">False (Model Output)</strong>
                </p>
              </div>
            </div>

            {/* Official Backend Attribution Strings */}
            <div className="mt-4 rounded-xl bg-theme-secondary/80 border border-theme-border p-4 space-y-2 text-xs">
              <div className="font-bold uppercase tracking-wider text-theme-mint">
                Mandatory Data Attribution
              </div>
              <p className="text-theme-text">
                <strong>Provider Attribution:</strong>{" "}
                {liveAirQuality?.attribution.provider_attribution ??
                  "Weather and air quality data by Open-Meteo.com (https://open-meteo.com/en/docs/air-quality-api)"}
              </p>
              <p className="text-theme-muted">
                <strong className="text-theme-text">Copernicus CAMS Attribution:</strong>{" "}
                {liveAirQuality?.attribution.cams_attribution ??
                  "Contains modified Copernicus Atmosphere Monitoring Service (CAMS) information (https://atmosphere.copernicus.eu/). Neither the European Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or data it contains."}
              </p>
            </div>
          </section>

          {/* 5. Health Advisory Panel & 6. Daily Recommendations Preview */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Health Advisory Panel */}
            <section
              id="section-advisory"
              aria-labelledby="heading-health-advisory"
              className="lg:col-span-6 rounded-2xl bg-theme-card border border-theme-border p-6 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between gap-2 mb-3">
                  <span className="text-xs font-bold uppercase tracking-wider text-theme-mint">
                    Informational Health Guidance
                  </span>
                  <span className="rounded bg-amber-500/15 border border-amber-400/40 px-2.5 py-0.5 text-xs font-semibold text-amber-300">
                    Not Medical Advice • ~45 km Grid Scope
                  </span>
                </div>
                <h2
                  id="heading-health-advisory"
                  className="text-xl font-bold text-theme-text"
                >
                  {isLiveOrCached && liveAirQuality
                    ? `General Health Guidance for ${activeLocation.display_name} (Model AQI: ${
                        liveAirQuality.aqi.band ?? "Unavailable"
                      })`
                    : demoDashboard.health_advisory.headline}
                </h2>

                {/* Explicit Medical & Spatial Resolution Limitation Notice */}
                <div className="mt-3 rounded-xl bg-theme-secondary/80 border border-theme-border p-3.5 text-xs text-theme-muted leading-relaxed">
                  <strong className="text-theme-text">Important Scope Notice:</strong>{" "}
                  This guidance is general environmental health information, not a medical diagnosis or treatment plan. Because CAMS Global estimates represent an{" "}
                  <strong className="text-theme-mint">approximately 0.4° (~45 km) regional grid cell</strong>, they cannot measure your exact street-level or indoor personal exposure. Consult a qualified healthcare professional for personal medical advice.
                </div>

                <div className="mt-4 space-y-3">
                  {demoDashboard.health_advisory.groups.map((group) => (
                    <div
                      key={group.audience}
                      className="rounded-xl bg-theme-secondary border border-theme-border p-4"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                        <h3 className="text-sm font-bold text-theme-text">
                          {group.audience}
                        </h3>
                        <span className="text-xs font-semibold text-theme-mint bg-theme-card border border-theme-border rounded-md px-2.5 py-0.5">
                          Informational Guidance
                        </span>
                      </div>
                      <p className="text-xs sm:text-sm text-theme-muted leading-relaxed">
                        {group.guidance}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            {/* Daily Recommendations Preview */}
            <section
              id="section-recommendations"
              aria-labelledby="heading-daily-recommendations"
              className="lg:col-span-6 rounded-2xl bg-theme-card border border-theme-border p-6 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between gap-2 mb-3">
                  <span className="text-xs font-bold uppercase tracking-wider text-theme-mint">
                    Actionable Urban Planning
                  </span>
                  <span className="rounded bg-theme-secondary border border-theme-border px-2.5 py-0.5 text-xs font-semibold text-theme-mint">
                    General Exposure Reduction Tips
                  </span>
                </div>
                <h2
                  id="heading-daily-recommendations"
                  className="text-xl font-bold text-theme-text"
                >
                  Daily Exposure Reduction Recommendations
                </h2>
                <p className="mt-2 text-sm text-theme-muted">
                  General behavioral practices to help commuters, households, and outdoor residents in{" "}
                  {activeLocation.city} reduce exposure near localized emission sources (which can exceed ~45 km regional model averages).
                </p>

                <div className="mt-5 space-y-3">
                  {demoDashboard.daily_recommendations.map((rec) => (
                    <article
                      key={rec.id}
                      className="rounded-xl border border-theme-border bg-theme-secondary p-4 hover:border-theme-accent/50 transition-colors"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                        <div className="flex items-center gap-2">
                          <span className="rounded-md bg-theme-card border border-theme-border px-2.5 py-0.5 text-xs font-semibold text-theme-mint">
                            {rec.category}
                          </span>
                          <span className="text-xs font-semibold text-theme-muted">
                            {rec.time_window}
                          </span>
                        </div>
                        <span
                          className={`rounded-full border px-2.5 py-0.5 text-xs font-bold ${getPriorityBadgeStyle(
                            rec.priority
                          )}`}
                        >
                          {rec.priority} Priority
                        </span>
                      </div>
                      <h3 className="text-sm font-bold text-theme-text">
                        {rec.title}
                      </h3>
                      <p className="mt-1 text-xs sm:text-sm text-theme-muted leading-relaxed">
                        {rec.description}
                      </p>
                    </article>
                  ))}
                </div>
              </div>
            </section>
          </div>

          {/* 7. Gemini-Powered AIRWISE AI Assistant */}
          <AssistantPanel
            selectedLocation={activeLocation}
            observationTime={isLiveOrCached ? liveAirQuality?.observation_time : null}
            usAqi={isLiveOrCached ? liveAirQuality?.aqi.value : null}
            aqiBand={isLiveOrCached ? liveAirQuality?.aqi.band : null}
          />
        </div>
      </main>
    </div>
  );
}
