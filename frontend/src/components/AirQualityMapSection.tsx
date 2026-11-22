"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { fetchLiveAirQuality, isRequestCanceledError } from "@/lib/api";
import { FALLBACK_LOCATIONS } from "@/lib/demoFallback";
import { AirQualityResponse, AqiBand } from "@/types/dashboard";
import type { CityMapDataStatus, CityMapState } from "@/components/LeafletMapCanvas";

const LeafletMapCanvas = dynamic(
  () => import("@/components/LeafletMapCanvas"),
  {
    ssr: false,
    loading: () => (
      <div className="w-full h-[360px] sm:h-[420px] rounded-xl border border-theme-border bg-[#0B1415] flex items-center justify-center text-sm text-theme-muted">
        Initializing interactive map canvas...
      </div>
    ),
  }
);

interface AirQualityMapSectionProps {
  selectedLocationId: string;
  onSelectLocation: (locationId: string) => void;
  isDashboardDemoMode: boolean;
  latestSelectedCityData: AirQualityResponse | null;
}

function getBandBadgeStyle(band: AqiBand | null): string {
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
      return "bg-slate-900/90 text-slate-300 border-slate-600/50";
  }
}

export default function AirQualityMapSection({
  selectedLocationId,
  onSelectLocation,
  isDashboardDemoMode,
  latestSelectedCityData,
}: AirQualityMapSectionProps) {
  const [cityStates, setCityStates] = useState<Record<string, CityMapState>>(() => {
    const initial: Record<string, CityMapState> = {};
    for (const loc of FALLBACK_LOCATIONS) {
      initial[loc.id] = {
        location: loc,
        status: "loading",
        data: null,
        errorMessage: null,
      };
    }
    return initial;
  });
  const [isRefreshingAll, setIsRefreshingAll] = useState<boolean>(false);

  const lastKnownMapRef = useRef<Record<string, AirQualityResponse>>({});
  const abortRef = useRef<AbortController | null>(null);

  const fetchAllCities = useCallback(async () => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    setIsRefreshingAll(true);

    const results = await Promise.allSettled(
      FALLBACK_LOCATIONS.map((loc) =>
        fetchLiveAirQuality(loc.id, controller.signal).then((data) => ({
          id: loc.id,
          data,
        }))
      )
    );

    if (controller.signal.aborted) {
      return;
    }

    setCityStates((prev) => {
      const next: Record<string, CityMapState> = { ...prev };
      FALLBACK_LOCATIONS.forEach((loc, idx) => {
        const res = results[idx];
        if (res.status === "fulfilled") {
          lastKnownMapRef.current[loc.id] = res.value.data;
          next[loc.id] = {
            location: loc,
            status: "live-model",
            data: res.value.data,
            errorMessage: null,
          };
        } else {
          if (isRequestCanceledError(res.reason)) return;
          const errMsg =
            res.reason instanceof Error
              ? res.reason.message
              : "Live model data unavailable";
          const cached = lastKnownMapRef.current[loc.id];
          if (cached) {
            next[loc.id] = {
              location: loc,
              status: "stale-cached",
              data: cached,
              errorMessage: errMsg,
            };
          } else {
            next[loc.id] = {
              location: loc,
              status: "unavailable",
              data: null,
              errorMessage: errMsg,
            };
          }
        }
      });
      return next;
    });

    setIsRefreshingAll(false);
  }, []);

  useEffect(() => {
    void fetchAllCities();
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, [fetchAllCities]);

  // Synchronize whenever the main dashboard loads fresh verified data for the selected city
  useEffect(() => {
    if (!latestSelectedCityData) return;
    const locId = latestSelectedCityData.location.id;
    lastKnownMapRef.current[locId] = latestSelectedCityData;
    setCityStates((prev) => {
      const existing = prev[locId];
      if (!existing) return prev;
      return {
        ...prev,
        [locId]: {
          location: latestSelectedCityData.location,
          status: "live-model",
          data: latestSelectedCityData,
          errorMessage: null,
        },
      };
    });
  }, [latestSelectedCityData]);

  // Never populate live map markers with demo values when user explicitly activates Demo Mode
  const orderedCityList: CityMapState[] = FALLBACK_LOCATIONS.map((loc) => {
    const raw = cityStates[loc.id];
    if (isDashboardDemoMode) {
      return {
        location: loc,
        status: "demo-mode" as CityMapDataStatus,
        data: null,
        errorMessage:
          "Dashboard is in explicit DEMO DATA mode. Live map markers are paused so demo values are never plotted as live readings.",
      };
    }
    return raw;
  });

  const activeCityState =
    orderedCityList.find((c) => c.location.id === selectedLocationId) ??
    orderedCityList[0];

  const hasAnyError = orderedCityList.some(
    (c) => c.status === "unavailable" || c.status === "stale-cached"
  );

  return (
    <section
      id="section-map"
      aria-labelledby="heading-aq-map"
      className="rounded-2xl bg-theme-card border border-theme-border p-6 space-y-5"
    >
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-theme-border pb-4">
        <div>
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span className="rounded bg-teal-500/15 border border-theme-accent/40 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider text-theme-mint">
              Air Quality Intelligence Map
            </span>
            <span className="rounded bg-theme-secondary border border-theme-border px-2.5 py-0.5 text-xs font-medium text-theme-muted">
              4 Configured Cities • No GPS / Location Permissions Requested
            </span>
          </div>
          <h2 id="heading-aq-map" className="text-xl font-bold text-theme-text">
            Regional Model-Based Air Quality Overview (Lagos, Abuja, Nairobi, Accra)
          </h2>
          <p className="text-xs sm:text-sm text-theme-muted mt-1">
            Select any map marker or city card below to synchronize the entire dashboard. Markers plot verified Open-Meteo CAMS Global (~45 km regional grid) model estimates—never physical street-level sensors and never demo values.
          </p>
        </div>

        <button
          type="button"
          onClick={() => void fetchAllCities()}
          disabled={isRefreshingAll || isDashboardDemoMode}
          className="self-start md:self-auto rounded-lg border border-theme-border bg-theme-secondary px-3.5 py-2 text-xs font-semibold text-theme-mint hover:border-theme-accent hover:bg-[#213B37] focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint disabled:opacity-50 transition-colors shrink-0"
        >
          {isRefreshingAll ? "Refreshing 4 Cities..." : "Refresh All Map Markers"}
        </button>
      </div>

      {/* Explicit Demo Mode / Partial Outage Notice */}
      {isDashboardDemoMode && (
        <div
          role="status"
          className="rounded-xl border border-amber-400/45 bg-theme-secondary/80 p-3.5 text-xs sm:text-sm text-amber-200"
        >
          <strong>EXPLICIT DEMO MODE ACTIVE:</strong> Live map markers do not display simulated demo numbers. Switch back to Live Model Data in the top banner to display verified Open-Meteo CAMS Global AQI markers.
        </div>
      )}

      {!isDashboardDemoMode && hasAnyError && (
        <div
          role="alert"
          className="rounded-xl border border-amber-400/40 bg-theme-secondary/80 p-3.5 text-xs text-theme-muted"
        >
          <strong className="text-amber-300">Partial Provider Notice:</strong> One or more cities could not be refreshed from FastAPI. Stale responses are clearly labelled{" "}
          <strong className="text-theme-text">CACHED / STALE</strong> and missing cities show{" "}
          <strong className="text-theme-text">DATA UNAVAILABLE</strong>.
        </div>
      )}

      {/* Map Canvas + Accompanying City Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-stretch">
        {/* Left: Interactive Leaflet Map + Legend */}
        <div className="lg:col-span-8 flex flex-col justify-between space-y-3">
          <LeafletMapCanvas
            cities={orderedCityList}
            selectedLocationId={selectedLocationId}
            onSelectLocation={onSelectLocation}
          />

          {/* AQI Map Legend & Tile Attribution */}
          <div className="rounded-xl bg-theme-secondary border border-theme-border p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-[11px] text-theme-muted">
            <div className="flex flex-wrap items-center gap-2.5" aria-label="Map AQI color legend">
              <span className="font-bold text-theme-text uppercase tracking-wider">AQI Legend:</span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" aria-hidden="true" />
                Good (0–50)
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-yellow-400" aria-hidden="true" />
                Moderate (51–100)
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-orange-400" aria-hidden="true" />
                USG (101–150)
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-red-400" aria-hidden="true" />
                Unhealthy (151–200)
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-purple-400" aria-hidden="true" />
                Very Unhealthy (201+)
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-slate-400" aria-hidden="true" />
                Unavailable
              </span>
            </div>
            <span className="text-[10px] text-theme-muted shrink-0">
              Basemap: OpenStreetMap &amp; CARTO Dark Matter
            </span>
          </div>
        </div>

        {/* Right: Accessible City Selection List & Selected City Info Panel */}
        <div className="lg:col-span-4 flex flex-col justify-between gap-4">
          {/* Accompanying Accessible Location List */}
          <div className="rounded-xl bg-theme-secondary border border-theme-border p-4 space-y-2.5">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold uppercase tracking-wider text-theme-mint">
                Configured Cities (Select to Focus)
              </h3>
              <span className="text-[11px] text-theme-muted">Synced</span>
            </div>

            <ul
              aria-label="Configured African cities air quality status"
              className="space-y-2 list-none m-0 p-0"
            >
              {orderedCityList.map((city) => {
                const isSelected = city.location.id === selectedLocationId;
                const hasAqi =
                  (city.status === "live-model" || city.status === "stale-cached") &&
                  city.data?.aqi.status === "available" &&
                  city.data.aqi.value !== null;

                return (
                  <li key={city.location.id}>
                    <button
                      type="button"
                      onClick={() => onSelectLocation(city.location.id)}
                      aria-pressed={isSelected}
                      className={`w-full text-left rounded-xl p-3 border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint ${
                        isSelected
                          ? "bg-[#14B8A6]/15 border-theme-mint shadow-sm"
                          : "bg-theme-card border-theme-border hover:border-theme-accent/60"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <div className="text-sm font-bold text-theme-text">
                            {city.location.display_name}
                          </div>
                          <div className="text-[11px] text-theme-muted">
                            {city.location.latitude.toFixed(2)}°, {city.location.longitude.toFixed(2)}° •{" "}
                            {city.data?.observation_time
                              ? city.data.observation_time
                              : city.status === "loading"
                              ? "Loading..."
                              : "Timestamp unavailable"}
                          </div>
                        </div>

                        <div className="text-right shrink-0">
                          {hasAqi && city.data ? (
                            <span
                              className={`inline-block rounded-lg border px-2.5 py-0.5 text-xs font-extrabold ${getBandBadgeStyle(
                                city.data.aqi.band
                              )}`}
                            >
                              AQI {city.data.aqi.value}
                            </span>
                          ) : city.status === "loading" ? (
                            <span className="text-xs text-theme-muted italic">...</span>
                          ) : city.status === "demo-mode" ? (
                            <span className="rounded-lg border border-amber-400/40 bg-amber-950/60 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                              DEMO MODE
                            </span>
                          ) : (
                            <span className="rounded-lg border border-slate-600/50 bg-slate-900 px-2 py-0.5 text-[10px] font-bold text-slate-300">
                              UNAVAILABLE
                            </span>
                          )}
                        </div>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          {/* Selected City Detail Card */}
          <div className="rounded-xl bg-[#0B1415]/90 border border-theme-border p-4 space-y-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="font-bold uppercase tracking-wider text-theme-mint">
                Selected Marker Details
              </span>
              <span className="rounded bg-theme-secondary border border-theme-border px-2 py-0.5 text-[10px] font-semibold uppercase text-theme-text">
                {activeCityState.status === "live-model"
                  ? "Live Model"
                  : activeCityState.status === "stale-cached"
                  ? "Cached / Stale"
                  : activeCityState.status === "demo-mode"
                  ? "Demo Mode"
                  : activeCityState.status === "loading"
                  ? "Loading"
                  : "Data Unavailable"}
              </span>
            </div>

            <div className="text-sm font-bold text-theme-text">
              {activeCityState.location.display_name} ({activeCityState.location.id})
            </div>

            {activeCityState.data &&
            (activeCityState.status === "live-model" ||
              activeCityState.status === "stale-cached") ? (
              <div className="space-y-1 text-theme-muted">
                <div>
                  US AQI:{" "}
                  <strong className="text-theme-text">
                    {activeCityState.data.aqi.status === "available" &&
                    activeCityState.data.aqi.value !== null
                      ? `${activeCityState.data.aqi.value} (${activeCityState.data.aqi.band ?? "Model"})`
                      : "DATA UNAVAILABLE"}
                  </strong>
                </div>
                <div>
                  Observation:{" "}
                  <strong className="text-theme-text">
                    {activeCityState.data.observation_time} ({activeCityState.data.timezone})
                  </strong>
                </div>
                <div>
                  PM2.5:{" "}
                  <strong className="text-theme-mint">
                    {activeCityState.data.pm2_5.status === "available" &&
                    activeCityState.data.pm2_5.value !== null
                      ? `${activeCityState.data.pm2_5.value} ${activeCityState.data.pm2_5.unit}`
                      : "DATA UNAVAILABLE"}
                  </strong>
                </div>
              </div>
            ) : (
              <p className="text-theme-muted">
                {activeCityState.errorMessage ??
                  "Verified live model data is loading or currently unavailable for this location."}
              </p>
            )}

            <p className="pt-2 border-t border-theme-border/70 text-[11px] text-theme-muted leading-snug">
              <strong className="text-theme-text">Spatial Scope:</strong> CAMS Global regional atmospheric model (~0.4° / ~45 km resolution, 3-hourly native output). Not a street-level physical sensor reading.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
