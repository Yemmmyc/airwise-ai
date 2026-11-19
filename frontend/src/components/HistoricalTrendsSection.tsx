"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchHistoricalAirQuality,
  fetchHistoricalCityComparison,
  isRequestCanceledError,
} from "@/lib/api";
import {
  DailyHistoricalSummary,
  HistoricalAirQualityResponse,
  HistoricalCityComparisonResponse,
  HistoricalHourlyRecord,
  HistoricalMetricKey,
  HistoricalRangeDays,
  HistoricalStorageOrigin,
  LocationOption,
} from "@/types/dashboard";

interface HistoricalTrendsSectionProps {
  selectedLocation: LocationOption;
  isDashboardDemoMode: boolean;
}

type HistoryTabMode = "location" | "compare";
type GranularityMode = "daily" | "hourly";

interface MetricConfig {
  key: HistoricalMetricKey;
  label: string;
  shortLabel: string;
  unit: string;
  dailyAvgField: keyof DailyHistoricalSummary;
  dailyPeakField?: keyof DailyHistoricalSummary;
  hourlyField: keyof HistoricalHourlyRecord;
}

const METRICS: MetricConfig[] = [
  {
    key: "us_aqi",
    label: "US AQI",
    shortLabel: "US AQI",
    unit: "US AQI",
    dailyAvgField: "avg_us_aqi",
    dailyPeakField: "max_us_aqi",
    hourlyField: "us_aqi",
  },
  {
    key: "pm2_5",
    label: "PM2.5",
    shortLabel: "PM2.5",
    unit: "µg/m³",
    dailyAvgField: "avg_pm2_5",
    dailyPeakField: "max_pm2_5",
    hourlyField: "pm2_5",
  },
  {
    key: "pm10",
    label: "PM10",
    shortLabel: "PM10",
    unit: "µg/m³",
    dailyAvgField: "avg_pm10",
    hourlyField: "pm10",
  },
  {
    key: "no2",
    label: "NO2",
    shortLabel: "NO2",
    unit: "µg/m³",
    dailyAvgField: "avg_no2",
    hourlyField: "no2",
  },
  {
    key: "o3",
    label: "O3",
    shortLabel: "O3",
    unit: "µg/m³",
    dailyAvgField: "avg_o3",
    hourlyField: "o3",
  },
  {
    key: "so2",
    label: "SO2",
    shortLabel: "SO2",
    unit: "µg/m³",
    dailyAvgField: "avg_so2",
    hourlyField: "so2",
  },
];

const RANGE_OPTIONS: HistoricalRangeDays[] = [7, 14, 30];

// Distinct visual styles (color + dash pattern + marker shape) for accessible 4-city comparison
const CITY_SERIES_STYLES: Record<
  string,
  { stroke: string; dashArray: string; shape: "circle" | "square" | "triangle" | "diamond"; badgeClass: string }
> = {
  "lagos-ng": {
    stroke: "#5EEAD4", // mint
    dashArray: "",
    shape: "circle",
    badgeClass: "bg-teal-950/90 text-teal-200 border-teal-400/50",
  },
  "abuja-ng": {
    stroke: "#FBBF24", // amber
    dashArray: "6 3",
    shape: "square",
    badgeClass: "bg-amber-950/90 text-amber-200 border-amber-400/50",
  },
  "nairobi-ke": {
    stroke: "#34D399", // emerald
    dashArray: "2 3",
    shape: "triangle",
    badgeClass: "bg-emerald-950/90 text-emerald-200 border-emerald-400/50",
  },
  "accra-gh": {
    stroke: "#C084FC", // violet
    dashArray: "8 3 2 3",
    shape: "diamond",
    badgeClass: "bg-purple-950/90 text-purple-200 border-purple-400/50",
  },
};

function getOriginBadge(origin: HistoricalStorageOrigin): {
  label: string;
  style: string;
} {
  switch (origin) {
    case "fresh_provider_retrieval":
      return {
        label: "Fresh Upstream Retrieval",
        style: "bg-emerald-500/15 text-emerald-300 border-emerald-400/45",
      };
    case "historical_cache":
      return {
        label: "Historical In-Memory Cache",
        style: "bg-teal-500/15 text-theme-mint border-theme-accent/45",
      };
    case "persisted_database_records":
      return {
        label: "Persisted SQLite Records",
        style: "bg-sky-500/15 text-sky-300 border-sky-400/45",
      };
    case "persisted_database_fallback":
      return {
        label: "Persisted SQLite Fallback (Upstream Unreachable)",
        style: "bg-amber-500/15 text-amber-300 border-amber-400/50",
      };
  }
}

function formatShortDate(isoDate: string): string {
  const parts = isoDate.split("-");
  if (parts.length === 3) {
    return `${parts[1]}/${parts[2]}`;
  }
  return isoDate;
}

/**
 * Build contiguous SVG polyline path segments, breaking the line cleanly across any null/missing points.
 * Never connects lines through missing data gaps.
 */
function buildSegmentedPath(
  points: Array<{ x: number; y: number | null }>
): string {
  const segments: string[] = [];
  let inSegment = false;

  for (const pt of points) {
    if (pt.y === null || Number.isNaN(pt.y)) {
      inSegment = false;
      continue;
    }
    if (!inSegment) {
      segments.push(`M ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`);
      inSegment = true;
    } else {
      segments.push(`L ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`);
    }
  }
  return segments.join(" ");
}

function renderCityShapeMarker(
  shape: "circle" | "square" | "triangle" | "diamond",
  x: number,
  y: number,
  color: string
) {
  switch (shape) {
    case "circle":
      return <circle cx={x} cy={y} r={3.5} fill={color} stroke="#0B1415" strokeWidth={1} />;
    case "square":
      return (
        <rect
          x={x - 3}
          y={y - 3}
          width={6}
          height={6}
          fill={color}
          stroke="#0B1415"
          strokeWidth={1}
        />
      );
    case "triangle":
      return (
        <polygon
          points={`${x},${y - 4} ${x + 3.8},${y + 3} ${x - 3.8},${y + 3}`}
          fill={color}
          stroke="#0B1415"
          strokeWidth={1}
        />
      );
    case "diamond":
      return (
        <polygon
          points={`${x},${y - 4.2} ${x + 3.8},${y} ${x},${y + 4.2} ${x - 3.8},${y}`}
          fill={color}
          stroke="#0B1415"
          strokeWidth={1}
        />
      );
  }
}

export default function HistoricalTrendsSection({
  selectedLocation,
  isDashboardDemoMode,
}: HistoricalTrendsSectionProps) {
  const [tabMode, setTabMode] = useState<HistoryTabMode>("location");
  const [rangeDays, setRangeDays] = useState<HistoricalRangeDays>(7);
  const [metricKey, setMetricKey] = useState<HistoricalMetricKey>("us_aqi");
  const [granularity, setGranularity] = useState<GranularityMode>("daily");

  // Single-location history state
  const [historyData, setHistoryData] =
    useState<HistoricalAirQualityResponse | null>(null);
  const [historyLoading, setHistoryLoading] = useState<boolean>(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [focusedDayIndex, setFocusedDayIndex] = useState<number | null>(null);
  const [focusedHourIndex, setFocusedHourIndex] = useState<number | null>(null);

  // Four-city comparison state
  const [compareData, setCompareData] =
    useState<HistoricalCityComparisonResponse | null>(null);
  const [compareLoading, setCompareLoading] = useState<boolean>(false);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [focusedCompareDayIndex, setFocusedCompareDayIndex] = useState<number | null>(null);

  const locationAbortRef = useRef<AbortController | null>(null);
  const locationSeqRef = useRef<number>(0);

  const compareAbortRef = useRef<AbortController | null>(null);
  const compareSeqRef = useRef<number>(0);

  // Enforce daily default when switching to 14 or 30 days (hourly view is 7-day only)
  useEffect(() => {
    if (rangeDays !== 7 && granularity === "hourly") {
      setGranularity("daily");
    }
  }, [rangeDays, granularity]);

  const loadLocationHistory = useCallback(
    async (
      locId: string,
      days: HistoricalRangeDays,
      forceRefresh: boolean = false
    ) => {
      if (locationAbortRef.current) {
        locationAbortRef.current.abort();
      }
      const controller = new AbortController();
      locationAbortRef.current = controller;
      locationSeqRef.current += 1;
      const seq = locationSeqRef.current;

      setHistoryLoading(true);
      setHistoryError(null);
      setFocusedDayIndex(null);
      setFocusedHourIndex(null);

      try {
        const res = await fetchHistoricalAirQuality(locId, days, {
          forceRefresh,
          signal: controller.signal,
        });
        if (seq !== locationSeqRef.current || controller.signal.aborted) return;
        setHistoryData(res);
      } catch (err) {
        if (isRequestCanceledError(err)) return;
        if (seq !== locationSeqRef.current) return;
        setHistoryData(null);
        setHistoryError(
          err instanceof Error
            ? err.message
            : "Unable to retrieve historical model data from FastAPI."
        );
      } finally {
        if (seq === locationSeqRef.current) {
          setHistoryLoading(false);
        }
      }
    },
    []
  );

  const loadCityComparison = useCallback(
    async (days: HistoricalRangeDays, forceRefresh: boolean = false) => {
      if (compareAbortRef.current) {
        compareAbortRef.current.abort();
      }
      const controller = new AbortController();
      compareAbortRef.current = controller;
      compareSeqRef.current += 1;
      const seq = compareSeqRef.current;

      setCompareLoading(true);
      setCompareError(null);
      setFocusedCompareDayIndex(null);

      try {
        const res = await fetchHistoricalCityComparison(days, {
          forceRefresh,
          signal: controller.signal,
        });
        if (seq !== compareSeqRef.current || controller.signal.aborted) return;
        setCompareData(res);
      } catch (err) {
        if (isRequestCanceledError(err)) return;
        if (seq !== compareSeqRef.current) return;
        setCompareData(null);
        setCompareError(
          err instanceof Error
            ? err.message
            : "Unable to retrieve four-city historical comparison from FastAPI."
        );
      } finally {
        if (seq === compareSeqRef.current) {
          setCompareLoading(false);
        }
      }
    },
    []
  );

  useEffect(() => {
    if (isDashboardDemoMode) return;
    if (tabMode === "location") {
      void loadLocationHistory(selectedLocation.id, rangeDays);
    } else {
      void loadCityComparison(rangeDays);
    }
  }, [
    isDashboardDemoMode,
    tabMode,
    selectedLocation.id,
    rangeDays,
    loadLocationHistory,
    loadCityComparison,
  ]);

  useEffect(() => {
    return () => {
      if (locationAbortRef.current) locationAbortRef.current.abort();
      if (compareAbortRef.current) compareAbortRef.current.abort();
    };
  }, []);

  const activeMetric =
    METRICS.find((m) => m.key === metricKey) ?? METRICS[0];

  // Extract single-location daily chart series
  const dailySeries = useMemo(() => {
    if (!historyData) return [];
    return historyData.daily_summaries.map((d) => {
      const avgVal = d[activeMetric.dailyAvgField] as number | null;
      const peakVal = activeMetric.dailyPeakField
        ? (d[activeMetric.dailyPeakField] as number | null)
        : null;
      return {
        date: d.date,
        avg: avgVal,
        peak: peakVal,
        minAqi: d.min_us_aqi,
        band: d.dominant_aqi_band,
        validHours: d.valid_hours,
        expectedHours: d.expected_hours,
        missingHours: d.missing_hours,
        completeness: d.completeness_percent,
      };
    });
  }, [historyData, activeMetric]);

  // Extract 7-day hourly chart series
  const hourlySeries = useMemo(() => {
    if (!historyData || rangeDays !== 7) return [];
    return historyData.hourly_records.map((r) => ({
      localTime: r.local_time,
      timestampUtc: r.timestamp_utc,
      value: r[activeMetric.hourlyField] as number | null,
    }));
  }, [historyData, rangeDays, activeMetric]);

  // Compute restrained, strictly data-driven non-causal insights
  const trendInsights = useMemo(() => {
    if (!historyData || historyData.daily_summaries.length === 0) return [];
    const insights: string[] = [];
    const ps = historyData.period_summary;

    const validAqiDays = historyData.daily_summaries.filter(
      (d) => d.avg_us_aqi !== null
    );

    if (ps.avg_us_aqi !== null && ps.max_us_aqi !== null) {
      insights.push(
        `Across the ${historyData.range_days}-day window (${historyData.start_date} to ${historyData.end_date}), the model-estimated average US AQI was ${ps.avg_us_aqi} with a peak hourly value of ${ps.max_us_aqi}${
          ps.peak_aqi_timestamp ? ` observed at ${ps.peak_aqi_timestamp} (${historyData.timezone})` : ""
        }.`
      );
    }

    if (validAqiDays.length >= 2) {
      const highestDay = validAqiDays.reduce((best, cur) =>
        (cur.avg_us_aqi ?? -1) > (best.avg_us_aqi ?? -1) ? cur : best
      );
      const lowestDay = validAqiDays.reduce((best, cur) =>
        (cur.avg_us_aqi ?? Infinity) < (best.avg_us_aqi ?? Infinity) ? cur : best
      );
      insights.push(
        `Highest daily mean US AQI occurred on ${highestDay.date} (${highestDay.avg_us_aqi}), while the lowest daily mean occurred on ${lowestDay.date} (${lowestDay.avg_us_aqi}).`
      );

      // Compare first half vs second half of the available window (strictly observational, non-causal)
      const midpoint = Math.floor(validAqiDays.length / 2);
      const firstHalf = validAqiDays.slice(0, midpoint);
      const secondHalf = validAqiDays.slice(midpoint);
      const firstMean =
        firstHalf.reduce((acc, d) => acc + (d.avg_us_aqi ?? 0), 0) /
        firstHalf.length;
      const secondMean =
        secondHalf.reduce((acc, d) => acc + (d.avg_us_aqi ?? 0), 0) /
        secondHalf.length;
      const delta = Number((secondMean - firstMean).toFixed(1));
      if (Math.abs(delta) >= 5) {
        insights.push(
          `Observed half-period change: mean US AQI was ${Math.abs(delta)} points ${
            delta > 0 ? "higher" : "lower"
          } in the second half of the window (${secondMean.toFixed(1)}) compared with the first half (${firstMean.toFixed(1)}). No causal source is inferred from model series alone.`
        );
      } else {
        insights.push(
          `Observed half-period stability: mean US AQI remained within 5 points between the first half (${firstMean.toFixed(1)}) and second half (${secondMean.toFixed(1)}) of the period.`
        );
      }
    }

    const bandEntries = Object.entries(ps.days_by_aqi_band);
    if (bandEntries.length > 0) {
      const formattedBands = bandEntries
        .map(([band, count]) => `${count} ${band}`)
        .join(", ");
      insights.push(`Daily category distribution: ${formattedBands} day(s).`);
    }

    insights.push(
      `Data completeness: ${ps.completeness_percent}% (${ps.total_valid_hours} of ${ps.total_expected_hours} expected hourly slots populated; ${ps.total_missing_hours} missing).`
    );

    return insights;
  }, [historyData]);

  // SVG Chart Geometry Helper (Daily Single-City)
  const dailyChart = useMemo(() => {
    const width = 760;
    const height = 250;
    const padL = 46;
    const padR = 20;
    const padT = 20;
    const padB = 34;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;

    const numericVals: number[] = [];
    for (const d of dailySeries) {
      if (d.avg !== null) numericVals.push(d.avg);
      if (d.peak !== null) numericVals.push(d.peak);
    }

    const rawMax = numericVals.length > 0 ? Math.max(...numericVals) : 100;
    const yMax = Math.max(10, Math.ceil((rawMax * 1.15) / 10) * 10);
    const n = dailySeries.length;

    const xFor = (idx: number) =>
      n <= 1 ? padL + plotW / 2 : padL + (idx / (n - 1)) * plotW;
    const yFor = (val: number | null) =>
      val === null ? null : padT + plotH - (val / yMax) * plotH;

    const avgPoints = dailySeries.map((d, i) => ({
      x: xFor(i),
      y: yFor(d.avg),
      item: d,
      idx: i,
    }));
    const peakPoints = dailySeries.map((d, i) => ({
      x: xFor(i),
      y: yFor(d.peak),
      item: d,
      idx: i,
    }));

    return {
      width,
      height,
      padL,
      padR,
      padT,
      padB,
      plotW,
      plotH,
      yMax,
      yTicks: [0, Math.round(yMax * 0.25), Math.round(yMax * 0.5), Math.round(yMax * 0.75), yMax],
      avgPath: buildSegmentedPath(avgPoints),
      peakPath: buildSegmentedPath(peakPoints),
      avgPoints,
      peakPoints,
      hasPeakSeries: Boolean(activeMetric.dailyPeakField),
    };
  }, [dailySeries, activeMetric]);

  // SVG Chart Geometry Helper (7-Day Hourly Single-City)
  const hourlyChart = useMemo(() => {
    const width = 760;
    const height = 240;
    const padL = 46;
    const padR = 20;
    const padT = 20;
    const padB = 34;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;

    const numericVals = hourlySeries
      .map((h) => h.value)
      .filter((v): v is number => v !== null);
    const rawMax = numericVals.length > 0 ? Math.max(...numericVals) : 100;
    const yMax = Math.max(10, Math.ceil((rawMax * 1.15) / 10) * 10);
    const n = hourlySeries.length;

    const xFor = (idx: number) =>
      n <= 1 ? padL + plotW / 2 : padL + (idx / (n - 1)) * plotW;
    const yFor = (val: number | null) =>
      val === null ? null : padT + plotH - (val / yMax) * plotH;

    const pts = hourlySeries.map((h, i) => ({
      x: xFor(i),
      y: yFor(h.value),
      item: h,
      idx: i,
    }));

    return {
      width,
      height,
      padL,
      padT,
      plotW,
      plotH,
      yMax,
      yTicks: [0, Math.round(yMax * 0.25), Math.round(yMax * 0.5), Math.round(yMax * 0.75), yMax],
      path: buildSegmentedPath(pts),
      pts,
    };
  }, [hourlySeries]);

  // SVG Chart Geometry Helper (Four-City Daily AQI Comparison)
  const compareChart = useMemo(() => {
    const width = 760;
    const height = 260;
    const padL = 46;
    const padR = 20;
    const padT = 20;
    const padB = 34;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;

    if (!compareData) {
      return {
        width,
        height,
        padL,
        padT,
        plotW,
        plotH,
        yMax: 100,
        yTicks: [0, 25, 50, 75, 100],
        dates: [] as string[],
        series: [] as Array<{
          cityId: string;
          cityName: string;
          available: boolean;
          stroke: string;
          dashArray: string;
          shape: "circle" | "square" | "triangle" | "diamond";
          path: string;
          points: Array<{ x: number; y: number | null; val: number | null; date: string }>;
        }>,
      };
    }

    // Collect union of all sorted local dates across available cities
    const dateSet = new Set<string>();
    const allVals: number[] = [];
    for (const city of compareData.cities) {
      for (const d of city.daily_summaries) {
        dateSet.add(d.date);
        if (d.avg_us_aqi !== null) allVals.push(d.avg_us_aqi);
      }
    }
    const dates = Array.from(dateSet).sort();
    const rawMax = allVals.length > 0 ? Math.max(...allVals) : 100;
    const yMax = Math.max(50, Math.ceil((rawMax * 1.15) / 10) * 10);
    const n = dates.length;

    const xFor = (idx: number) =>
      n <= 1 ? padL + plotW / 2 : padL + (idx / (n - 1)) * plotW;
    const yFor = (val: number | null) =>
      val === null ? null : padT + plotH - (val / yMax) * plotH;

    const series = compareData.cities.map((city) => {
      const style = CITY_SERIES_STYLES[city.location.id] ?? {
        stroke: "#5EEAD4",
        dashArray: "",
        shape: "circle" as const,
      };
      const byDate = new Map(city.daily_summaries.map((d) => [d.date, d.avg_us_aqi]));
      const pts = dates.map((dt, idx) => {
        const val = city.status === "available" ? (byDate.get(dt) ?? null) : null;
        return { x: xFor(idx), y: yFor(val), val, date: dt };
      });
      return {
        cityId: city.location.id,
        cityName: city.location.display_name,
        available: city.status === "available",
        stroke: style.stroke,
        dashArray: style.dashArray,
        shape: style.shape,
        path: buildSegmentedPath(pts),
        points: pts,
      };
    });

    return {
      width,
      height,
      padL,
      padT,
      plotW,
      plotH,
      yMax,
      yTicks: [0, Math.round(yMax * 0.25), Math.round(yMax * 0.5), Math.round(yMax * 0.75), yMax],
      dates,
      series,
    };
  }, [compareData]);

  const focusedDay =
    focusedDayIndex !== null && dailySeries[focusedDayIndex]
      ? dailySeries[focusedDayIndex]
      : dailySeries.length > 0
      ? dailySeries[dailySeries.length - 1]
      : null;

  const focusedHour =
    focusedHourIndex !== null && hourlySeries[focusedHourIndex]
      ? hourlySeries[focusedHourIndex]
      : hourlySeries.length > 0
      ? hourlySeries[hourlySeries.length - 1]
      : null;

  const originMeta = historyData ? getOriginBadge(historyData.origin.storage_origin) : null;

  return (
    <section
      id="section-history"
      aria-labelledby="heading-historical-trends"
      className="rounded-2xl bg-theme-card border border-theme-border p-6 space-y-6"
    >
      {/* Top Section Header & Mode Switcher */}
      <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4 border-b border-theme-border pb-5">
        <div>
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <span className="rounded bg-teal-500/15 border border-theme-accent/45 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider text-theme-mint">
              HISTORICAL PROVIDER DATA — MODEL-BASED ESTIMATE
            </span>
            {originMeta && !isDashboardDemoMode && tabMode === "location" && (
              <span
                className={`rounded border px-2.5 py-0.5 text-[11px] font-semibold ${originMeta.style}`}
              >
                Origin: {originMeta.label}
              </span>
            )}
          </div>
          <h2
            id="heading-historical-trends"
            className="text-xl sm:text-2xl font-bold text-theme-text"
          >
            Historical Air Quality Trends &amp; Insights —{" "}
            {tabMode === "location"
              ? selectedLocation.display_name
              : "Four-City Comparison"}
          </h2>
          <p className="mt-1 text-xs sm:text-sm text-theme-muted max-w-3xl">
            Genuine historical Open-Meteo CAMS Global model series (~0.4° / ~45 km grid, 3-hourly native output) aggregated in each location&apos;s local timezone. Missing hours remain gaps and are never zero-filled or substituted with demo data.
          </p>
        </div>

        {/* View Mode & Range Controls */}
        <div className="flex flex-col sm:flex-row flex-wrap items-stretch sm:items-center gap-2.5 shrink-0">
          {/* Location vs 4-City Comparison Tabs */}
          <div
            role="tablist"
            aria-label="Historical view mode"
            className="inline-flex rounded-xl bg-[#0B1415] border border-theme-border p-1"
          >
            <button
              type="button"
              role="tab"
              aria-selected={tabMode === "location"}
              onClick={() => setTabMode("location")}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint ${
                tabMode === "location"
                  ? "bg-[#14B8A6]/20 text-theme-mint border border-theme-accent/50"
                  : "text-theme-muted hover:text-theme-text border border-transparent"
              }`}
            >
              {selectedLocation.city} Trends
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tabMode === "compare"}
              onClick={() => setTabMode("compare")}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint ${
                tabMode === "compare"
                  ? "bg-[#14B8A6]/20 text-theme-mint border border-theme-accent/50"
                  : "text-theme-muted hover:text-theme-text border border-transparent"
              }`}
            >
              4-City Comparison
            </button>
          </div>

          {/* 7 / 14 / 30 Days Selector */}
          <div
            role="group"
            aria-label="Historical date range selector"
            className="inline-flex rounded-xl bg-[#0B1415] border border-theme-border p-1"
          >
            {RANGE_OPTIONS.map((days) => (
              <button
                key={days}
                type="button"
                aria-pressed={rangeDays === days}
                onClick={() => setRangeDays(days)}
                className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint ${
                  rangeDays === days
                    ? "bg-theme-accent text-[#0B1415]"
                    : "text-theme-muted hover:text-theme-text"
                }`}
              >
                {days} Days
              </button>
            ))}
          </div>

          {/* Refresh Upstream Button */}
          {!isDashboardDemoMode && (
            <button
              type="button"
              disabled={historyLoading || compareLoading}
              onClick={() => {
                if (tabMode === "location") {
                  void loadLocationHistory(selectedLocation.id, rangeDays, true);
                } else {
                  void loadCityComparison(rangeDays, true);
                }
              }}
              className="rounded-xl border border-theme-border bg-theme-secondary px-3 py-2 text-xs font-semibold text-theme-mint hover:border-theme-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint disabled:opacity-50 transition-colors"
            >
              {historyLoading || compareLoading ? "Syncing..." : "Refresh"}
            </button>
          )}
        </div>
      </div>

      {/* Explicit Demo Mode Isolation */}
      {isDashboardDemoMode ? (
        <div
          role="status"
          aria-live="polite"
          className="rounded-xl border border-amber-400/45 bg-theme-secondary/80 p-5 text-xs sm:text-sm text-theme-muted space-y-2"
        >
          <p className="font-bold text-amber-300">
            EXPLICIT DEMO MODE ACTIVE — Historical Model Charts Paused
          </p>
          <p>
            To preserve strict data integrity, AIRWISE AI does not render live historical CAMS Global model records while the dashboard is in explicit Demo Data mode, nor does it fabricate simulated historical trends. Switch back to{" "}
            <strong className="text-theme-text">Live Model Data</strong> in the top disclosure banner to inspect genuine 7, 14, and 30-day historical trends.
          </p>
        </div>
      ) : tabMode === "location" ? (
        /* ================================================================
           SINGLE-LOCATION HISTORICAL TRENDS VIEW
           ================================================================ */
        <div className="space-y-6">
          {/* Metric Selector & Daily/Hourly Granularity Controls */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div
              role="group"
              aria-label="Select historical air quality metric"
              className="flex flex-wrap items-center gap-1.5"
            >
              <span className="text-xs font-semibold text-theme-muted mr-1">
                Metric:
              </span>
              {METRICS.map((m) => (
                <button
                  key={m.key}
                  type="button"
                  aria-pressed={metricKey === m.key}
                  onClick={() => setMetricKey(m.key)}
                  className={`rounded-lg px-2.5 py-1.5 text-xs font-bold border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint ${
                    metricKey === m.key
                      ? "bg-[#14B8A6]/20 text-theme-mint border-theme-mint"
                      : "bg-theme-secondary text-theme-muted border-theme-border hover:text-theme-text hover:border-theme-accent/60"
                  }`}
                >
                  {m.shortLabel}
                </button>
              ))}
            </div>

            <div
              role="group"
              aria-label="Historical chart granularity"
              className="inline-flex items-center gap-1.5 self-start md:self-auto"
            >
              <span className="text-xs font-semibold text-theme-muted">View:</span>
              <button
                type="button"
                aria-pressed={granularity === "daily"}
                onClick={() => setGranularity("daily")}
                className={`rounded-lg px-3 py-1.5 text-xs font-bold border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint ${
                  granularity === "daily"
                    ? "bg-theme-secondary text-theme-mint border-theme-accent"
                    : "bg-[#0B1415] text-theme-muted border-theme-border hover:text-theme-text"
                }`}
              >
                Daily Summary
              </button>
              <button
                type="button"
                aria-pressed={granularity === "hourly"}
                disabled={rangeDays !== 7}
                title={
                  rangeDays !== 7
                    ? "Hourly view is limited to the 7-day range for readability"
                    : "Inspect 7-day hourly model series"
                }
                onClick={() => setGranularity("hourly")}
                className={`rounded-lg px-3 py-1.5 text-xs font-bold border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint disabled:opacity-45 disabled:cursor-not-allowed ${
                  granularity === "hourly"
                    ? "bg-theme-secondary text-theme-mint border-theme-accent"
                    : "bg-[#0B1415] text-theme-muted border-theme-border hover:text-theme-text"
                }`}
              >
                Hourly (7d only)
              </button>
            </div>
          </div>

          {/* Loading State */}
          {historyLoading && (
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
                Loading {rangeDays}-day historical CAMS Global model records for{" "}
                <strong>{selectedLocation.display_name}</strong>...
              </span>
            </div>
          )}

          {/* Error / Unavailable State */}
          {!historyLoading && historyError && (
            <div
              role="alert"
              aria-live="assertive"
              className="rounded-xl border border-red-500/45 bg-[#0B1415]/90 p-5 space-y-3"
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <span className="inline-block rounded bg-red-500/20 border border-red-400/40 px-2 py-0.5 text-xs font-bold uppercase text-red-300 mb-1">
                    DATA UNAVAILABLE
                  </span>
                  <h3 className="text-sm font-bold text-theme-text">
                    Historical Model Data Could Not Be Retrieved for {selectedLocation.display_name}
                  </h3>
                  <p className="text-xs text-theme-muted mt-1">
                    {historyError}. No sample or fabricated historical values are displayed.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void loadLocationHistory(selectedLocation.id, rangeDays, true)}
                  className="self-start sm:self-auto rounded-lg bg-theme-accent px-3.5 py-2 text-xs font-bold text-[#0B1415] hover:bg-theme-mint focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint shrink-0"
                >
                  Retry Historical API
                </button>
              </div>
            </div>
          )}

          {/* Persisted Fallback Notice */}
          {!historyLoading &&
            historyData &&
            historyData.origin.storage_origin === "persisted_database_fallback" && (
              <div
                role="alert"
                className="rounded-xl border border-amber-400/50 bg-theme-secondary/90 p-4 text-xs text-theme-muted"
              >
                <strong className="text-amber-300">
                  PERSISTED SQLITE FALLBACK ACTIVE:
                </strong>{" "}
                Upstream Open-Meteo refresh failed ({historyData.origin.fallback_reason}). Displaying previously persisted historical records retrieved at{" "}
                <strong className="text-theme-text">{historyData.retrieval_time}</strong>.
              </div>
            )}

          {/* Historical Content when Available */}
          {!historyLoading && historyData && (
            <>
              {/* 4.4 Period Summary Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="rounded-xl bg-theme-secondary border border-theme-border p-4">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-theme-muted">
                    Period Average US AQI ({rangeDays}d)
                  </span>
                  <div className="mt-2 text-3xl font-black text-theme-text">
                    {historyData.period_summary.avg_us_aqi ?? "N/A"}
                  </div>
                  <p className="mt-1 text-xs text-theme-muted">
                    Range: {historyData.start_date} → {historyData.end_date}
                  </p>
                </div>

                <div className="rounded-xl bg-theme-secondary border border-theme-border p-4">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-theme-muted">
                    Peak Hourly US AQI
                  </span>
                  <div className="mt-2 text-3xl font-black text-theme-mint">
                    {historyData.period_summary.max_us_aqi ?? "N/A"}
                  </div>
                  <p className="mt-1 text-xs text-theme-muted">
                    {historyData.period_summary.peak_aqi_timestamp
                      ? `${historyData.period_summary.peak_aqi_timestamp} (${historyData.timezone})`
                      : "Peak timestamp unavailable"}
                  </p>
                </div>

                <div className="rounded-xl bg-theme-secondary border border-theme-border p-4">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-theme-muted">
                    Data Completeness
                  </span>
                  <div className="mt-2 text-3xl font-black text-theme-text">
                    {historyData.data_completeness_percent}%
                  </div>
                  <p className="mt-1 text-xs text-theme-muted">
                    {historyData.period_summary.total_valid_hours} /{" "}
                    {historyData.period_summary.total_expected_hours} hrs (
                    {historyData.period_summary.total_missing_hours} missing)
                  </p>
                </div>

                <div className="rounded-xl bg-theme-secondary border border-theme-border p-4">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-theme-muted">
                    Days by US EPA AQI Band
                  </span>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {Object.keys(historyData.period_summary.days_by_aqi_band).length > 0 ? (
                      Object.entries(historyData.period_summary.days_by_aqi_band).map(
                        ([band, count]) => (
                          <span
                            key={band}
                            className="rounded-md bg-theme-card border border-theme-border px-2 py-0.5 text-[11px] font-semibold text-theme-text"
                          >
                            {band}: <strong className="text-theme-mint">{count}d</strong>
                          </span>
                        )
                      )
                    ) : (
                      <span className="text-xs text-theme-muted">No valid AQI days</span>
                    )}
                  </div>
                </div>
              </div>

              {/* 4.3 & 4.5 Interactive Responsive SVG Trend Chart */}
              <div className="rounded-xl bg-[#0B1415]/90 border border-theme-border p-4 sm:p-5 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <h3 className="text-sm sm:text-base font-bold text-theme-text">
                      {granularity === "daily"
                        ? `Daily ${activeMetric.label} Trend (${rangeDays} Days — ${selectedLocation.display_name})`
                        : `7-Day Hourly ${activeMetric.label} Trend (${selectedLocation.display_name})`}
                    </h3>
                    <p className="text-xs text-theme-muted">
                      {granularity === "daily"
                        ? `Local calendar days (${historyData.timezone}). Units: ${activeMetric.unit}. Missing days appear as line breaks.`
                        : `Local timestamps (${historyData.timezone}). Interpolated to 1-hourly API intervals from 3-hourly CAMS Global model fields (not physical roadside sensor telemetry).`}
                    </p>
                  </div>

                  {/* Legend */}
                  <div className="flex flex-wrap items-center gap-3 text-xs text-theme-muted">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-0.5 w-4 bg-theme-mint inline-block" aria-hidden="true" />
                      {granularity === "daily" ? "Daily Average" : "Hourly Model Estimate"}
                    </span>
                    {granularity === "daily" && dailyChart.hasPeakSeries && (
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className="h-0.5 w-4 border-t-2 border-dashed border-amber-400 inline-block"
                          aria-hidden="true"
                        />
                        Daily Peak
                      </span>
                    )}
                  </div>
                </div>

                {/* Focused Point Inspector (Accessible Tooltip Alternative + Mouse/Keyboard Selection) */}
                {granularity === "daily" && focusedDay && (
                  <div
                    role="status"
                    aria-live="polite"
                    className="rounded-lg bg-theme-secondary border border-theme-border px-3.5 py-2.5 flex flex-wrap items-center justify-between gap-2 text-xs"
                  >
                    <div>
                      <span className="text-theme-muted">Selected Day: </span>
                      <strong className="text-theme-text">{focusedDay.date}</strong>
                      <span className="text-theme-muted"> ({historyData.timezone})</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-4">
                      <span>
                        Avg {activeMetric.shortLabel}:{" "}
                        <strong className="text-theme-mint">
                          {focusedDay.avg !== null
                            ? `${focusedDay.avg} ${activeMetric.unit}`
                            : "DATA UNAVAILABLE"}
                        </strong>
                      </span>
                      {dailyChart.hasPeakSeries && (
                        <span>
                          Peak:{" "}
                          <strong className="text-amber-300">
                            {focusedDay.peak !== null
                              ? `${focusedDay.peak} ${activeMetric.unit}`
                              : "N/A"}
                          </strong>
                        </span>
                      )}
                      <span className="text-theme-muted">
                        Valid hours: {focusedDay.validHours}/{focusedDay.expectedHours}
                      </span>
                    </div>
                  </div>
                )}

                {granularity === "hourly" && focusedHour && (
                  <div
                    role="status"
                    aria-live="polite"
                    className="rounded-lg bg-theme-secondary border border-theme-border px-3.5 py-2.5 flex flex-wrap items-center justify-between gap-2 text-xs"
                  >
                    <div>
                      <span className="text-theme-muted">Selected Hour: </span>
                      <strong className="text-theme-text">{focusedHour.localTime}</strong>
                      <span className="text-theme-muted"> ({historyData.timezone})</span>
                    </div>
                    <div>
                      {activeMetric.shortLabel}:{" "}
                      <strong className="text-theme-mint">
                        {focusedHour.value !== null
                          ? `${focusedHour.value} ${activeMetric.unit}`
                          : "DATA UNAVAILABLE"}
                      </strong>
                    </div>
                  </div>
                )}

                {/* Responsive SVG Canvas */}
                {granularity === "daily" ? (
                  <div className="w-full overflow-x-auto">
                    <svg
                      viewBox={`0 0 ${dailyChart.width} ${dailyChart.height}`}
                      role="img"
                      aria-label={`Daily ${activeMetric.label} historical line chart for ${selectedLocation.display_name} over ${rangeDays} days`}
                      className="w-full h-auto min-w-[540px]"
                    >
                      {/* Horizontal grid lines & Y axis labels */}
                      {dailyChart.yTicks.map((tick) => {
                        const y =
                          dailyChart.padT +
                          dailyChart.plotH -
                          (tick / dailyChart.yMax) * dailyChart.plotH;
                        return (
                          <g key={tick}>
                            <line
                              x1={dailyChart.padL}
                              x2={dailyChart.width - dailyChart.padR}
                              y1={y}
                              y2={y}
                              stroke="#29423D"
                              strokeDasharray="3 3"
                              strokeWidth={1}
                            />
                            <text
                              x={dailyChart.padL - 8}
                              y={y + 3.5}
                              textAnchor="end"
                              fill="#A3B8B2"
                              fontSize="10"
                            >
                              {tick}
                            </text>
                          </g>
                        );
                      })}

                      {/* Daily Peak Dashed Path (US AQI / PM2.5) */}
                      {dailyChart.hasPeakSeries && dailyChart.peakPath && (
                        <path
                          d={dailyChart.peakPath}
                          fill="none"
                          stroke="#FBBF24"
                          strokeWidth={1.75}
                          strokeDasharray="5 4"
                        />
                      )}

                      {/* Daily Average Primary Path */}
                      {dailyChart.avgPath && (
                        <path
                          d={dailyChart.avgPath}
                          fill="none"
                          stroke="#5EEAD4"
                          strokeWidth={2.5}
                        />
                      )}

                      {/* Interactive Keyboard-Accessible Data Points & X-axis Labels */}
                      {dailyChart.avgPoints.map((pt, idx) => {
                        const showLabel =
                          dailySeries.length <= 10 ||
                          idx === 0 ||
                          idx === dailySeries.length - 1 ||
                          idx % Math.ceil(dailySeries.length / 7) === 0;
                        const isFocused = focusedDay?.date === pt.item.date;

                        return (
                          <g key={pt.item.date}>
                            {showLabel && (
                              <text
                                x={pt.x}
                                y={dailyChart.height - 10}
                                textAnchor="middle"
                                fill="#A3B8B2"
                                fontSize="10"
                              >
                                {formatShortDate(pt.item.date)}
                              </text>
                            )}
                            {pt.y !== null && (
                              <circle
                                cx={pt.x}
                                cy={pt.y}
                                r={isFocused ? 5.5 : 3.8}
                                fill={isFocused ? "#14B8A6" : "#5EEAD4"}
                                stroke="#0B1415"
                                strokeWidth={1.5}
                                tabIndex={0}
                                role="button"
                                aria-label={`${pt.item.date}: average ${activeMetric.label} ${pt.item.avg} ${activeMetric.unit}`}
                                onMouseEnter={() => setFocusedDayIndex(idx)}
                                onFocus={() => setFocusedDayIndex(idx)}
                                onClick={() => setFocusedDayIndex(idx)}
                                className="cursor-pointer focus:outline-none"
                              />
                            )}
                          </g>
                        );
                      })}
                    </svg>
                  </div>
                ) : (
                  <div className="w-full overflow-x-auto">
                    <svg
                      viewBox={`0 0 ${hourlyChart.width} ${hourlyChart.height}`}
                      role="img"
                      aria-label={`7-day hourly ${activeMetric.label} historical model chart for ${selectedLocation.display_name}`}
                      className="w-full h-auto min-w-[540px]"
                    >
                      {hourlyChart.yTicks.map((tick) => {
                        const y =
                          hourlyChart.padT +
                          hourlyChart.plotH -
                          (tick / hourlyChart.yMax) * hourlyChart.plotH;
                        return (
                          <g key={tick}>
                            <line
                              x1={hourlyChart.padL}
                              x2={hourlyChart.width - 20}
                              y1={y}
                              y2={y}
                              stroke="#29423D"
                              strokeDasharray="3 3"
                              strokeWidth={1}
                            />
                            <text
                              x={hourlyChart.padL - 8}
                              y={y + 3.5}
                              textAnchor="end"
                              fill="#A3B8B2"
                              fontSize="10"
                            >
                              {tick}
                            </text>
                          </g>
                        );
                      })}

                      {hourlyChart.path && (
                        <path
                          d={hourlyChart.path}
                          fill="none"
                          stroke="#5EEAD4"
                          strokeWidth={1.8}
                        />
                      )}

                      {/* Render day-boundary x-axis ticks and sampled interactive hover targets */}
                      {hourlyChart.pts.map((pt, idx) => {
                        const isMidnight = pt.item.localTime.endsWith("T00:00");
                        return (
                          <g key={pt.item.timestampUtc}>
                            {isMidnight && (
                              <text
                                x={pt.x}
                                y={hourlyChart.height - 10}
                                textAnchor="middle"
                                fill="#A3B8B2"
                                fontSize="10"
                              >
                                {formatShortDate(pt.item.localTime.split("T")[0] ?? "")}
                              </text>
                            )}
                            {pt.y !== null && idx % 3 === 0 && (
                              <circle
                                cx={pt.x}
                                cy={pt.y}
                                r={focusedHourIndex === idx ? 4.5 : 2.2}
                                fill={focusedHourIndex === idx ? "#FBBF24" : "#14B8A6"}
                                tabIndex={0}
                                role="button"
                                aria-label={`${pt.item.localTime}: ${activeMetric.label} ${pt.item.value} ${activeMetric.unit}`}
                                onMouseEnter={() => setFocusedHourIndex(idx)}
                                onFocus={() => setFocusedHourIndex(idx)}
                                onClick={() => setFocusedHourIndex(idx)}
                                className="cursor-pointer focus:outline-none"
                              />
                            )}
                          </g>
                        );
                      })}
                    </svg>
                  </div>
                )}

                {/* Accessible Tabular Alternative */}
                <details className="rounded-xl bg-theme-secondary/70 border border-theme-border p-3.5">
                  <summary className="cursor-pointer text-xs font-semibold text-theme-mint focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint rounded px-1">
                    View Accessible Daily Historical Data Table ({historyData.daily_summaries.length} local days)
                  </summary>
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full text-left border-collapse text-xs">
                      <caption className="sr-only">
                        Daily historical CAMS Global model summaries for {selectedLocation.display_name} ({historyData.timezone})
                      </caption>
                      <thead>
                        <tr className="border-b border-theme-border text-theme-muted uppercase">
                          <th scope="col" className="py-2 pr-3">Local Date</th>
                          <th scope="col" className="py-2 px-2">Avg AQI</th>
                          <th scope="col" className="py-2 px-2">Peak AQI</th>
                          <th scope="col" className="py-2 px-2">Avg PM2.5</th>
                          <th scope="col" className="py-2 px-2">Avg PM10</th>
                          <th scope="col" className="py-2 px-2">Avg NO2</th>
                          <th scope="col" className="py-2 px-2">Avg O3</th>
                          <th scope="col" className="py-2 px-2">Avg SO2</th>
                          <th scope="col" className="py-2 pl-2">Valid Hrs</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-theme-border/60">
                        {historyData.daily_summaries.map((d) => (
                          <tr key={d.date} className="hover:bg-theme-card/50">
                            <th scope="row" className="py-2 pr-3 font-semibold text-theme-text whitespace-nowrap">
                              {d.date}
                            </th>
                            <td className="py-2 px-2 font-bold text-theme-mint">
                              {d.avg_us_aqi ?? "N/A"}
                            </td>
                            <td className="py-2 px-2 text-amber-300 font-semibold">
                              {d.max_us_aqi ?? "N/A"}
                            </td>
                            <td className="py-2 px-2 text-theme-text">{d.avg_pm2_5 ?? "N/A"}</td>
                            <td className="py-2 px-2 text-theme-text">{d.avg_pm10 ?? "N/A"}</td>
                            <td className="py-2 px-2 text-theme-text">{d.avg_no2 ?? "N/A"}</td>
                            <td className="py-2 px-2 text-theme-text">{d.avg_o3 ?? "N/A"}</td>
                            <td className="py-2 px-2 text-theme-text">{d.avg_so2 ?? "N/A"}</td>
                            <td className="py-2 pl-2 text-theme-muted">
                              {d.valid_hours}/{d.expected_hours} ({d.completeness_percent}%)
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </div>

              {/* 6. Restrained Data-Driven Trend Insights Panel */}
              <div className="rounded-xl bg-theme-secondary border border-theme-border p-5 space-y-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-bold uppercase tracking-wider text-theme-mint">
                    Data-Driven Historical Insights (Observational Only)
                  </h3>
                  <span className="text-[11px] text-theme-muted">
                    Derived strictly from verified backend statistics • Non-causal
                  </span>
                </div>
                {trendInsights.length > 0 ? (
                  <ul className="space-y-1.5 text-xs sm:text-sm text-theme-text list-disc pl-5">
                    {trendInsights.map((insight, idx) => (
                      <li key={idx} className="leading-relaxed">
                        {insight}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-theme-muted">
                    Insufficient valid historical data to compute reliable trend summaries for this window.
                  </p>
                )}
              </div>
            </>
          )}
        </div>
      ) : (
        /* ================================================================
           FOUR-CITY HISTORICAL COMPARISON VIEW
           ================================================================ */
        <div className="space-y-6">
          {compareLoading && (
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
                Loading {rangeDays}-day historical CAMS Global comparison for Lagos, Abuja, Nairobi, and Accra...
              </span>
            </div>
          )}

          {!compareLoading && compareError && (
            <div
              role="alert"
              aria-live="assertive"
              className="rounded-xl border border-red-500/45 bg-[#0B1415]/90 p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
            >
              <div>
                <p className="text-sm font-bold text-red-300">
                  Four-City Historical Comparison Unavailable
                </p>
                <p className="text-xs text-theme-muted mt-1">{compareError}</p>
              </div>
              <button
                type="button"
                onClick={() => void loadCityComparison(rangeDays, true)}
                className="self-start sm:self-auto rounded-lg bg-theme-accent px-3.5 py-2 text-xs font-bold text-[#0B1415] hover:bg-theme-mint"
              >
                Retry Comparison
              </button>
            </div>
          )}

          {!compareLoading && compareData && (
            <>
              {/* City Availability & Summary Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {compareData.cities.map((city) => {
                  const style = CITY_SERIES_STYLES[city.location.id];
                  return (
                    <div
                      key={city.location.id}
                      className="rounded-xl bg-theme-secondary border border-theme-border p-4 flex flex-col justify-between space-y-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-bold text-theme-text">
                          {city.location.display_name}
                        </span>
                        <span
                          className={`rounded border px-2 py-0.5 text-[10px] font-bold uppercase ${
                            city.status === "available"
                              ? style?.badgeClass ?? "bg-teal-950 text-theme-mint border-theme-accent/50"
                              : "bg-red-950/80 text-red-300 border-red-500/40"
                          }`}
                        >
                          {city.status === "available" ? style?.shape ?? "series" : "UNAVAILABLE"}
                        </span>
                      </div>

                      {city.status === "available" && city.period_summary ? (
                        <div className="space-y-1 text-xs">
                          <div className="flex justify-between">
                            <span className="text-theme-muted">Avg US AQI ({rangeDays}d):</span>
                            <strong className="text-theme-text">
                              {city.period_summary.avg_us_aqi ?? "N/A"}
                            </strong>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-theme-muted">Peak US AQI:</span>
                            <strong className="text-theme-mint">
                              {city.period_summary.max_us_aqi ?? "N/A"}
                            </strong>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-theme-muted">Completeness:</span>
                            <span className="text-theme-text">
                              {city.period_summary.completeness_percent}%
                            </span>
                          </div>
                          {city.origin && (
                            <div className="pt-1 text-[10px] text-theme-muted">
                              Origin: {getOriginBadge(city.origin.storage_origin).label}
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="text-xs text-red-300">
                          DATA UNAVAILABLE — {city.error_message ?? "Provider unavailable."}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Multi-City Daily US AQI SVG Chart (Distinct Color + Dash Pattern + Marker Shape) */}
              <div className="rounded-xl bg-[#0B1415]/90 border border-theme-border p-4 sm:p-5 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <h3 className="text-sm sm:text-base font-bold text-theme-text">
                      Four-City Daily Average US AQI Comparison ({rangeDays} Days)
                    </h3>
                    <p className="text-xs text-theme-muted">
                      Each city uses a distinct color, dash pattern, and marker shape for accessibility. Unavailable cities are excluded without demo substitution.
                    </p>
                  </div>

                  {/* Accessible Pattern + Shape Legend */}
                  <div className="flex flex-wrap items-center gap-3 text-xs">
                    {compareChart.series.map((s) => (
                      <span
                        key={s.cityId}
                        className={`inline-flex items-center gap-1.5 ${
                          s.available ? "text-theme-text" : "text-theme-muted line-through"
                        }`}
                      >
                        <svg width="24" height="12" aria-hidden="true">
                          <line
                            x1="0"
                            x2="24"
                            y1="6"
                            y2="6"
                            stroke={s.stroke}
                            strokeWidth="2"
                            strokeDasharray={s.dashArray}
                          />
                          {renderCityShapeMarker(s.shape, 12, 6, s.stroke)}
                        </svg>
                        <span>{s.cityName.split(",")[0]}</span>
                      </span>
                    ))}
                  </div>
                </div>

                {/* Focused Comparison Date Inspector */}
                {focusedCompareDayIndex !== null && compareChart.dates[focusedCompareDayIndex] && (
                  <div
                    role="status"
                    aria-live="polite"
                    className="rounded-lg bg-theme-secondary border border-theme-border px-3.5 py-2 flex flex-wrap items-center gap-4 text-xs"
                  >
                    <strong className="text-theme-mint">
                      Date: {compareChart.dates[focusedCompareDayIndex]}
                    </strong>
                    {compareChart.series.map((s) => {
                      const pt = s.points[focusedCompareDayIndex];
                      return (
                        <span key={s.cityId} className="text-theme-text">
                          {s.cityName.split(",")[0]}:{" "}
                          <strong>
                            {pt?.val !== null && pt?.val !== undefined ? pt.val : "N/A"}
                          </strong>
                        </span>
                      );
                    })}
                  </div>
                )}

                <div className="w-full overflow-x-auto">
                  <svg
                    viewBox={`0 0 ${compareChart.width} ${compareChart.height}`}
                    role="img"
                    aria-label={`Four-city daily average US AQI historical comparison chart over ${rangeDays} days`}
                    className="w-full h-auto min-w-[540px]"
                  >
                    {compareChart.yTicks.map((tick) => {
                      const y =
                        compareChart.padT +
                        compareChart.plotH -
                        (tick / compareChart.yMax) * compareChart.plotH;
                      return (
                        <g key={tick}>
                          <line
                            x1={compareChart.padL}
                            x2={compareChart.width - 20}
                            y1={y}
                            y2={y}
                            stroke="#29423D"
                            strokeDasharray="3 3"
                            strokeWidth={1}
                          />
                          <text
                            x={compareChart.padL - 8}
                            y={y + 3.5}
                            textAnchor="end"
                            fill="#A3B8B2"
                            fontSize="10"
                          >
                            {tick}
                          </text>
                        </g>
                      );
                    })}

                    {/* City lines & markers */}
                    {compareChart.series.map((s) => (
                      <g key={s.cityId}>
                        {s.path && (
                          <path
                            d={s.path}
                            fill="none"
                            stroke={s.stroke}
                            strokeWidth={2.2}
                            strokeDasharray={s.dashArray}
                          />
                        )}
                        {s.points.map((pt, idx) =>
                          pt.y !== null ? (
                            <g
                              key={`${s.cityId}-${pt.date}`}
                              tabIndex={0}
                              role="button"
                              aria-label={`${s.cityName} on ${pt.date}: average US AQI ${pt.val}`}
                              onMouseEnter={() => setFocusedCompareDayIndex(idx)}
                              onFocus={() => setFocusedCompareDayIndex(idx)}
                              onClick={() => setFocusedCompareDayIndex(idx)}
                              className="cursor-pointer focus:outline-none"
                            >
                              {renderCityShapeMarker(s.shape, pt.x, pt.y, s.stroke)}
                            </g>
                          ) : null
                        )}
                      </g>
                    ))}

                    {/* X-axis dates */}
                    {compareChart.dates.map((dt, idx) => {
                      const showLabel =
                        compareChart.dates.length <= 10 ||
                        idx === 0 ||
                        idx === compareChart.dates.length - 1 ||
                        idx % Math.ceil(compareChart.dates.length / 7) === 0;
                      if (!showLabel) return null;
                      const x =
                        compareChart.dates.length <= 1
                          ? compareChart.padL + compareChart.plotW / 2
                          : compareChart.padL +
                            (idx / (compareChart.dates.length - 1)) * compareChart.plotW;
                      return (
                        <text
                          key={dt}
                          x={x}
                          y={compareChart.height - 10}
                          textAnchor="middle"
                          fill="#A3B8B2"
                          fontSize="10"
                        >
                          {formatShortDate(dt)}
                        </text>
                      );
                    })}
                  </svg>
                </div>

                {/* Accessible Comparison Data Table */}
                <details className="rounded-xl bg-theme-secondary/70 border border-theme-border p-3.5">
                  <summary className="cursor-pointer text-xs font-semibold text-theme-mint focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint rounded px-1">
                    View Accessible Four-City Daily Comparison Table ({compareChart.dates.length} days)
                  </summary>
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full text-left border-collapse text-xs">
                      <caption className="sr-only">
                        Four-city daily average US AQI historical comparison across Lagos, Abuja, Nairobi, and Accra
                      </caption>
                      <thead>
                        <tr className="border-b border-theme-border text-theme-muted uppercase">
                          <th scope="col" className="py-2 pr-3">Date</th>
                          {compareData.cities.map((c) => (
                            <th key={c.location.id} scope="col" className="py-2 px-3">
                              {c.location.city} Avg AQI
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-theme-border/60">
                        {compareChart.dates.map((dt, idx) => (
                          <tr key={dt} className="hover:bg-theme-card/50">
                            <th scope="row" className="py-2 pr-3 font-semibold text-theme-text">
                              {dt}
                            </th>
                            {compareChart.series.map((s) => (
                              <td key={`${dt}-${s.cityId}`} className="py-2 px-3 text-theme-text">
                                {s.points[idx]?.val !== null && s.points[idx]?.val !== undefined
                                  ? s.points[idx].val
                                  : "DATA UNAVAILABLE"}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </div>
            </>
          )}
        </div>
      )}

      {/* 7. Historical Data Provenance & Scientific Disclosure Footer */}
      <div className="rounded-xl bg-theme-secondary/75 border border-theme-border p-4 text-xs text-theme-muted space-y-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-bold uppercase tracking-wider text-theme-mint">
            Historical Data Provenance &amp; Scientific Limitations
          </span>
          {historyData && !isDashboardDemoMode && (
            <span className="text-[11px]">
              Retrieved: <strong className="text-theme-text">{historyData.retrieval_time}</strong>
            </span>
          )}
        </div>
        <p className="leading-relaxed">
          <strong className="text-theme-text">Source &amp; Model Scope:</strong> Open-Meteo Air Quality API using Copernicus Atmosphere Monitoring Service (CAMS Global) data — approximate spatial resolution{" "}
          <strong className="text-theme-text">0.4° (~45 km)</strong>, underlying model temporal resolution{" "}
          <strong className="text-theme-text">3-hourly</strong> (interpolated to 1-hourly API timestamps). Values are regional atmospheric model estimates,{" "}
          <strong className="text-theme-text">not roadside physical sensor measurements</strong>, and are{" "}
          <strong className="text-theme-text">non-causal</strong>.
        </p>
        <p className="text-[11px]">
          {historyData?.attribution.provider_attribution ??
            compareData?.attribution.provider_attribution ??
            "Weather and air quality data by Open-Meteo.com (https://open-meteo.com/en/docs/air-quality-api)"}{" "}
          •{" "}
          {historyData?.attribution.cams_attribution ??
            compareData?.attribution.cams_attribution ??
            "Contains modified Copernicus Atmosphere Monitoring Service (CAMS) information."}
        </p>
      </div>
    </section>
  );
}
