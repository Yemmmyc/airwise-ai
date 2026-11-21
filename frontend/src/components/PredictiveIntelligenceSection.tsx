"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchPredictiveIntelligence,
  isRequestCanceledError,
} from "@/lib/api";
import {
  DataQualityTier,
  LocationOption,
  PredictiveIntelligenceResponse,
  RiskCategory,
  TrendSignal,
} from "@/types/dashboard";

interface PredictiveIntelligenceSectionProps {
  selectedLocation: LocationOption;
  isDashboardDemoMode: boolean;
}

function getRiskBadgeStyle(category: RiskCategory): string {
  switch (category) {
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

function getQualityBadgeStyle(tier: DataQualityTier): string {
  switch (tier) {
    case "High":
      return "bg-emerald-500/15 text-emerald-300 border-emerald-400/45";
    case "Moderate":
      return "bg-teal-500/15 text-theme-mint border-theme-accent/45";
    case "Limited":
      return "bg-amber-500/15 text-amber-300 border-amber-400/45";
    case "Insufficient data":
      return "bg-red-500/15 text-red-300 border-red-400/45";
  }
}

function getTrendBadge(signal: TrendSignal): {
  symbol: string;
  label: string;
  style: string;
} {
  switch (signal) {
    case "Rising":
      return {
        symbol: "↗",
        label: "Rising",
        style: "bg-orange-950/85 text-orange-300 border-orange-500/45",
      };
    case "Falling":
      return {
        symbol: "↘",
        label: "Falling",
        style: "bg-emerald-950/85 text-emerald-300 border-emerald-500/45",
      };
    case "Stable":
      return {
        symbol: "→",
        label: "Stable",
        style: "bg-teal-950/85 text-theme-mint border-theme-accent/45",
      };
    case "Insufficient data":
      return {
        symbol: "—",
        label: "Insufficient data",
        style: "bg-slate-900/90 text-slate-300 border-slate-600/50",
      };
  }
}

function formatWindowRange(startTime: string, endTime: string): string {
  const startParts = startTime.split("T");
  const endParts = endTime.split("T");
  if (startParts.length === 2 && endParts.length === 2) {
    if (startParts[0] === endParts[0]) {
      return `${startParts[0]} • ${startParts[1]} – ${endParts[1]}`;
    }
    return `${startParts[0]} ${startParts[1]} → ${endParts[0]} ${endParts[1]}`;
  }
  return `${startTime} – ${endTime}`;
}

export default function PredictiveIntelligenceSection({
  selectedLocation,
  isDashboardDemoMode,
}: PredictiveIntelligenceSectionProps) {
  const [intelligence, setIntelligence] =
    useState<PredictiveIntelligenceResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const seqRef = useRef<number>(0);

  const loadIntelligence = useCallback(async (locationId: string) => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;
    seqRef.current += 1;
    const seq = seqRef.current;

    setLoading(true);
    setErrorMessage(null);
    setIntelligence((prev) => (prev?.location.id === locationId ? prev : null));

    try {
      const res = await fetchPredictiveIntelligence(locationId, controller.signal);
      if (seq !== seqRef.current || controller.signal.aborted) return;
      setIntelligence(res);
    } catch (err) {
      if (isRequestCanceledError(err)) return;
      if (seq !== seqRef.current) return;
      setIntelligence(null);
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "Unable to load predictive intelligence from FastAPI backend."
      );
    } finally {
      if (seq === seqRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (isDashboardDemoMode) return;
    void loadIntelligence(selectedLocation.id);
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, [isDashboardDemoMode, selectedLocation.id, loadIntelligence]);

  return (
    <section
      id="section-intelligence"
      aria-labelledby="heading-predictive-intelligence"
      className="rounded-2xl bg-theme-card border border-theme-border p-6 space-y-6"
    >
      {/* Header & Data-Quality Tier */}
      <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4 border-b border-theme-border pb-5">
        <div>
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <span className="rounded bg-teal-500/15 border border-theme-accent/45 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider text-theme-mint">
              ANALYTICAL INTERPRETATION — BASED ON OPEN-METEO CAMS GLOBAL FORECAST
            </span>
            {intelligence && !isDashboardDemoMode && (
              <span
                className={`rounded border px-2.5 py-0.5 text-[11px] font-bold ${getQualityBadgeStyle(
                  intelligence.data_quality.tier
                )}`}
                title={intelligence.data_quality.disclosure}
              >
                Data Quality: {intelligence.data_quality.tier} ({intelligence.data_quality.completeness_percent}%)
              </span>
            )}
          </div>

          <h2
            id="heading-predictive-intelligence"
            className="text-xl sm:text-2xl font-bold text-theme-text"
          >
            Predictive Risk Intelligence &amp; Activity Planner — {selectedLocation.display_name}
          </h2>
          <p className="mt-1 text-xs sm:text-sm text-theme-muted max-w-3xl">
            Deterministic rule-based interpretation of the next 24 forecast hours from Open-Meteo CAMS Global (~45 km grid, 3-hourly native resolution). Identifies Peak Forecast Risk, elevated-risk windows, comparatively favorable windows, and provisional trend signals without AI fabrication or medical claims.
          </p>
        </div>

        {!isDashboardDemoMode && (
          <button
            type="button"
            disabled={loading}
            onClick={() => void loadIntelligence(selectedLocation.id)}
            className="self-start lg:self-auto rounded-xl border border-theme-border bg-theme-secondary px-3.5 py-2 text-xs font-semibold text-theme-mint hover:border-theme-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint disabled:opacity-50 transition-colors shrink-0"
          >
            {loading ? "Evaluating..." : "Refresh Risk Insights"}
          </button>
        )}
      </div>

      {/* Explicit Demo Mode Isolation */}
      {isDashboardDemoMode ? (
        <div
          role="status"
          aria-live="polite"
          className="rounded-xl border border-amber-400/45 bg-theme-secondary/80 p-5 text-xs sm:text-sm text-theme-muted space-y-1.5"
        >
          <p className="font-bold text-amber-300">
            EXPLICIT DEMO MODE ACTIVE — Predictive Intelligence Paused
          </p>
          <p>
            Predictive risk windows, activity planning, and trend signals are computed strictly from verified Open-Meteo CAMS Global forecasts and are paused in Demo Mode so simulated values are never presented as forecast intelligence.
          </p>
        </div>
      ) : loading ? (
        <div
          role="status"
          aria-live="polite"
          className="rounded-xl border border-theme-accent/40 bg-theme-secondary p-4 flex items-center gap-3 text-sm text-theme-text"
        >
          <span
            aria-hidden="true"
            className="h-4 w-4 rounded-full border-2 border-theme-mint border-t-transparent animate-spin shrink-0"
          />
          <span>
            Computing deterministic Peak Forecast Risk, risk windows, and trend signals for{" "}
            <strong>{selectedLocation.display_name}</strong>...
          </span>
        </div>
      ) : errorMessage ? (
        <div
          role="alert"
          aria-live="assertive"
          className="rounded-xl border border-red-500/45 bg-[#0B1415]/90 p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
        >
          <div>
            <span className="inline-block rounded bg-red-500/20 border border-red-400/40 px-2 py-0.5 text-xs font-bold uppercase text-red-300 mb-1">
              DATA UNAVAILABLE
            </span>
            <p className="text-sm font-bold text-theme-text">
              Predictive Intelligence Could Not Be Computed
            </p>
            <p className="text-xs text-theme-muted mt-1">{errorMessage}</p>
          </div>
          <button
            type="button"
            onClick={() => void loadIntelligence(selectedLocation.id)}
            className="self-start sm:self-auto rounded-lg bg-theme-accent px-3.5 py-2 text-xs font-bold text-[#0B1415] hover:bg-theme-mint focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint shrink-0"
          >
            Retry Intelligence API
          </button>
        </div>
      ) : intelligence ? (
        <div className="space-y-6">
          {/* 1. Peak Forecast Risk Summary Banner */}
          <div className="rounded-xl bg-theme-secondary border border-theme-border p-5 space-y-4">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="space-y-1.5">
                <span className="text-[11px] font-bold uppercase tracking-wider text-theme-mint">
                  Peak Forecast Risk (24-Hour Horizon — Not Uniform All-Day Risk)
                </span>
                <div className="flex flex-wrap items-center gap-3">
                  <span
                    className={`inline-flex items-center rounded-lg border px-3 py-1 text-sm font-extrabold ${getRiskBadgeStyle(
                      intelligence.daily_summary.peak_forecast_risk
                    )}`}
                  >
                    {intelligence.daily_summary.peak_forecast_risk}
                  </span>
                  <span className="text-xs sm:text-sm text-theme-text font-semibold">
                    Peak US AQI:{" "}
                    <strong className="text-theme-mint">
                      {intelligence.daily_summary.peak_aqi ?? "Unavailable"}
                    </strong>
                    {intelligence.daily_summary.peak_time
                      ? ` at ${intelligence.daily_summary.peak_time} (${intelligence.timezone})`
                      : ""}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2.5 text-center shrink-0">
                <div className="rounded-lg bg-theme-card border border-theme-border px-3 py-2">
                  <div className="text-[10px] uppercase text-theme-muted font-semibold">Mean AQI</div>
                  <div className="text-base font-black text-theme-text">
                    {intelligence.daily_summary.mean_aqi ?? "N/A"}
                  </div>
                </div>
                <div className="rounded-lg bg-theme-card border border-theme-border px-3 py-2">
                  <div className="text-[10px] uppercase text-theme-muted font-semibold">Min AQI</div>
                  <div className="text-base font-black text-emerald-300">
                    {intelligence.daily_summary.min_aqi ?? "N/A"}
                  </div>
                </div>
                <div className="rounded-lg bg-theme-card border border-theme-border px-3 py-2">
                  <div className="text-[10px] uppercase text-theme-muted font-semibold">Dominant</div>
                  <div className="text-xs font-bold text-theme-mint mt-0.5">
                    {intelligence.daily_summary.dominant_category}
                  </div>
                </div>
              </div>
            </div>

            <p className="text-xs sm:text-sm text-theme-text leading-relaxed border-t border-theme-border pt-3">
              {intelligence.daily_summary.deterministic_summary}
            </p>

            {/* Category Distribution Strip */}
            {intelligence.daily_summary.category_distribution.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-theme-muted font-semibold">Hourly Distribution:</span>
                {intelligence.daily_summary.category_distribution.map((entry) => (
                  <span
                    key={entry.category}
                    className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold ${getRiskBadgeStyle(
                      entry.category
                    )}`}
                  >
                    {entry.category}: {entry.hours}h ({entry.percentage}%)
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* 2. Two-Column Action Grid: Elevated Risk Windows + Comparatively Favorable Windows */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
            {/* Left: Elevated Risk Windows & Single-Hour Spikes */}
            <div className="lg:col-span-6 rounded-xl bg-[#0B1415]/90 border border-theme-border p-5 space-y-4">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-bold uppercase tracking-wider text-theme-mint">
                  Elevated-Risk Windows (US AQI ≥ 101, ≥ 2h)
                </h3>
                <span className="text-xs text-theme-muted">
                  {intelligence.risk_windows.length} window(s)
                </span>
              </div>

              {intelligence.daily_summary.risk_window_evaluation_status === "insufficient_data" ? (
                <div className="rounded-lg bg-theme-secondary border border-theme-border p-4 text-xs text-theme-muted">
                  <strong className="text-amber-300">Insufficient data to evaluate risk windows:</strong>{" "}
                  Fewer than 2 contiguous valid forecast hours are available.
                </div>
              ) : intelligence.risk_windows.length === 0 ? (
                <div className="rounded-lg bg-theme-secondary border border-theme-border p-4 text-xs text-theme-muted">
                  <strong className="text-theme-text">No qualifying elevated-risk windows detected</strong>{" "}
                  (≥ 2 consecutive forecast hours at US AQI ≥ 101) in the available horizon. Note that absence of detected risk windows is not a guarantee of street-level conditions.
                </div>
              ) : (
                <div className="space-y-3">
                  {intelligence.risk_windows.map((win, idx) => (
                    <article
                      key={`${win.start_time}-${idx}`}
                      className="rounded-xl bg-theme-secondary border border-orange-500/40 p-4 space-y-2 text-xs"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span
                          className={`rounded border px-2 py-0.5 font-bold ${getRiskBadgeStyle(
                            win.severity_category
                          )}`}
                        >
                          {win.severity_category}
                        </span>
                        <div className="flex items-center gap-1.5">
                          <span className="rounded bg-theme-card border border-theme-border px-2 py-0.5 font-semibold text-theme-text">
                            {win.duration_hours}h window
                          </span>
                          {win.crosses_midnight && (
                            <span className="rounded bg-purple-950/80 border border-purple-400/40 px-2 py-0.5 font-semibold text-purple-200">
                              Crosses Midnight
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="text-sm font-bold text-theme-text">
                        {formatWindowRange(win.start_time, win.end_time)}{" "}
                        <span className="text-xs font-normal text-theme-muted">({win.timezone})</span>
                      </div>
                      <div className="flex flex-wrap gap-4 text-theme-muted">
                        <span>
                          Peak AQI: <strong className="text-orange-300">{win.peak_aqi}</strong> ({win.peak_time.split("T")[1] ?? win.peak_time})
                        </span>
                        <span>
                          Mean AQI: <strong className="text-theme-text">{win.mean_aqi}</strong>
                        </span>
                      </div>
                      {win.interrupted_by_missing_data && (
                        <p className="text-[11px] text-amber-300">
                          Window bounded by missing forecast observation(s); never merged across gaps.
                        </p>
                      )}
                    </article>
                  ))}
                </div>
              )}

              {/* Isolated Single-Hour Spikes */}
              {intelligence.single_hour_spikes.length > 0 && (
                <div className="pt-3 border-t border-theme-border space-y-2">
                  <div className="text-xs font-bold uppercase tracking-wider text-amber-300">
                    Isolated Single-Hour Spikes ({intelligence.single_hour_spikes.length})
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {intelligence.single_hour_spikes.map((spike) => (
                      <span
                        key={spike.time}
                        className="rounded-lg bg-theme-secondary border border-amber-400/40 px-2.5 py-1 text-xs text-theme-text"
                      >
                        {spike.time} — <strong>AQI {spike.us_aqi}</strong> ({spike.category})
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Right: Comparatively Favorable Windows */}
            <div className="lg:col-span-6 rounded-xl bg-[#0B1415]/90 border border-theme-border p-5 space-y-4">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-bold uppercase tracking-wider text-theme-mint">
                  Comparatively Favorable Windows (2–4h)
                </h3>
                <span className="text-xs text-theme-muted">
                  Ceiling ≤ {intelligence.better_windows.guardrail_max_aqi_ceiling} AQI
                </span>
              </div>

              {intelligence.better_windows.windows.length === 0 ? (
                <div className="rounded-lg bg-theme-secondary border border-theme-border p-4 text-xs text-theme-muted">
                  <strong className="text-amber-300">No comparatively favorable window identified:</strong>{" "}
                  {intelligence.better_windows.note}
                </div>
              ) : (
                <div className="space-y-3">
                  {intelligence.better_windows.windows.map((bw, idx) => (
                    <article
                      key={`${bw.start_time}-${idx}`}
                      className="rounded-xl bg-theme-secondary border border-emerald-500/35 p-4 space-y-2 text-xs"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span
                          className={`rounded border px-2 py-0.5 font-bold ${getRiskBadgeStyle(
                            bw.category
                          )}`}
                        >
                          {bw.category}
                        </span>
                        <span className="rounded bg-theme-card border border-theme-border px-2 py-0.5 font-semibold text-theme-mint">
                          {bw.duration_hours}h comparative window
                        </span>
                      </div>
                      <div className="text-sm font-bold text-theme-text">
                        {formatWindowRange(bw.start_time, bw.end_time)}{" "}
                        <span className="text-xs font-normal text-theme-muted">({bw.timezone})</span>
                      </div>
                      <p className="text-theme-muted leading-snug">{bw.rationale}</p>
                      <div className="text-[11px] text-theme-muted">
                        Hourly AQI values:{" "}
                        <code className="text-theme-mint">[{bw.hourly_aqi_values.join(", ")}]</code>
                      </div>
                    </article>
                  ))}
                  <p className="text-[11px] text-theme-muted">
                    {intelligence.better_windows.note}
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* 3. Independent Activity Planning Cards */}
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-bold uppercase tracking-wider text-theme-mint">
                Comparative Activity Planning (AIRWISE Operational Heuristics — Non-Medical)
              </h3>
              <span className="text-[11px] text-theme-muted">
                Evaluated independently per activity duration &amp; ceiling
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {intelligence.activity_recommendations.map((rec) => (
                <article
                  key={rec.activity_type}
                  className="rounded-xl bg-theme-secondary border border-theme-border p-4 flex flex-col justify-between space-y-3"
                >
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <h4 className="text-sm font-bold text-theme-text">{rec.label}</h4>
                      <span
                        className={`rounded border px-2 py-0.5 text-[10px] font-bold uppercase ${
                          rec.status === "window_identified"
                            ? "bg-emerald-500/15 text-emerald-300 border-emerald-400/40"
                            : "bg-amber-500/15 text-amber-300 border-amber-400/40"
                        }`}
                      >
                        {rec.status === "window_identified"
                          ? "Window Found"
                          : rec.status === "insufficient_data"
                          ? "Insufficient Data"
                          : "No Qualifying Window"}
                      </span>
                    </div>

                    {rec.recommended_window ? (
                      <div className="rounded-lg bg-theme-card border border-theme-border p-3 text-xs space-y-1">
                        <div className="font-bold text-theme-mint">
                          {formatWindowRange(
                            rec.recommended_window.start_time,
                            rec.recommended_window.end_time
                          )}
                        </div>
                        <div className="text-theme-muted">
                          Mean AQI: <strong className="text-theme-text">{rec.recommended_window.mean_aqi}</strong> • Max:{" "}
                          <strong className="text-theme-text">{rec.recommended_window.max_aqi}</strong> (
                          {rec.recommended_window.duration_hours}h)
                        </div>
                      </div>
                    ) : null}

                    <p className="text-xs text-theme-text leading-relaxed">{rec.rationale}</p>
                  </div>

                  <p className="text-[10px] text-theme-muted border-t border-theme-border/80 pt-2 leading-snug">
                    {rec.operational_rule_description}
                  </p>
                </article>
              ))}
            </div>
          </div>

          {/* 4. Compact 6-Metric Trend Signal Strip (Non-Color Symbols + Text) */}
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-bold uppercase tracking-wider text-theme-mint">
                24-Hour Forecast Trend Signals (Provisional MVP Heuristics)
              </h3>
              <span className="text-[11px] text-theme-muted">
                Independent per metric • Elapsed-hour OLS without zero-filling
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {intelligence.trend_signals.map((trend) => {
                const badge = getTrendBadge(trend.signal);
                return (
                  <div
                    key={trend.metric}
                    title={trend.description}
                    className="rounded-xl bg-[#0B1415]/90 border border-theme-border p-3.5 space-y-2"
                  >
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-xs font-extrabold text-theme-text">
                        {trend.metric === "us_aqi" ? "US AQI" : trend.metric}
                      </span>
                      <span className="text-[10px] text-theme-muted">{trend.valid_points} pts</span>
                    </div>
                    <div
                      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-bold ${badge.style}`}
                    >
                      <span aria-hidden="true">{badge.symbol}</span>
                      <span>{badge.label}</span>
                    </div>
                    <p className="text-[11px] text-theme-muted leading-snug">
                      {trend.projected_net_change !== null
                        ? `Δ ${trend.projected_net_change > 0 ? "+" : ""}${trend.projected_net_change} ${trend.unit}`
                        : "Insufficient valid points"}
                      {trend.volatility_flag ? " (High variability)" : ""}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 5. Transparent Data-Quality Evidence & Disclosure Footer */}
          <details className="rounded-xl bg-theme-secondary/80 border border-theme-border p-4 text-xs text-theme-muted">
            <summary className="cursor-pointer font-semibold text-theme-mint focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint rounded px-1">
              Forecast Data-Quality Evidence ({intelligence.data_quality.tier} • {intelligence.data_quality.valid_aqi_hours}/{intelligence.data_quality.expected_forecast_hours} valid hours • {intelligence.data_quality.timestamp_continuity})
            </summary>
            <div className="mt-3 space-y-3">
              <p className="text-theme-text leading-relaxed">
                <strong>Important Data-Quality Disclosure:</strong> {intelligence.data_quality.disclosure}
              </p>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="rounded-lg bg-theme-card border border-theme-border p-2.5">
                  <div className="text-[10px] uppercase">Completeness</div>
                  <div className="text-sm font-bold text-theme-text">
                    {intelligence.data_quality.completeness_percent}% ({intelligence.data_quality.missing_hours_count} missing)
                  </div>
                </div>
                <div className="rounded-lg bg-theme-card border border-theme-border p-2.5">
                  <div className="text-[10px] uppercase">Continuity</div>
                  <div className="text-sm font-bold text-theme-text">
                    {intelligence.data_quality.timestamp_continuity} ({intelligence.data_quality.gap_count} gaps)
                  </div>
                </div>
                <div className="rounded-lg bg-theme-card border border-theme-border p-2.5">
                  <div className="text-[10px] uppercase">Source Cache</div>
                  <div className="text-sm font-bold text-theme-text">
                    {intelligence.data_quality.cache_hit ? "300s Live Cache Hit" : "Fresh Upstream Fetch"}
                  </div>
                </div>
                <div className="rounded-lg bg-theme-card border border-theme-border p-2.5">
                  <div className="text-[10px] uppercase">Retrieved (UTC)</div>
                  <div className="text-xs font-bold text-theme-text mt-0.5">
                    {intelligence.retrieval_time}
                  </div>
                </div>
              </div>

              <div className="text-[11px] border-t border-theme-border/70 pt-2.5 space-y-1">
                <p>{intelligence.disclaimer}</p>
                <p>
                  {intelligence.attribution.provider_attribution} •{" "}
                  {intelligence.attribution.cams_attribution}
                </p>
              </div>
            </div>
          </details>
        </div>
      ) : null}
    </section>
  );
}
