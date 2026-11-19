"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiClientError,
  askAirwiseAssistant,
  fetchAssistantStatus,
  isRequestCanceledError,
} from "@/lib/api";
import {
  AssistantMode,
  AssistantResponse,
  AssistantStatusResponse,
  ConversationTurn,
  LocationOption,
  PollutantCode,
} from "@/types/dashboard";

interface AssistantPanelProps {
  selectedLocation: LocationOption;
  observationTime?: string | null;
  usAqi?: number | null;
  aqiBand?: string | null;
}

interface ChatEntry {
  id: string;
  question: string;
  mode: AssistantMode;
  locationDisplayName: string;
  response: AssistantResponse;
}

const MODE_TABS: Array<{
  id: AssistantMode;
  label: string;
  shortDesc: string;
}> = [
  {
    id: "ask",
    label: "Ask AIRWISE",
    shortDesc: "Ask natural questions grounded in verified model data",
  },
  {
    id: "activity_planner",
    label: "Daily Activity Planner",
    shortDesc: "Exercise, walking, cycling, events & sensitive groups",
  },
  {
    id: "pollutant_education",
    label: "Pollutant Education",
    shortDesc: "Plain-language guide to PM2.5, PM10, NO2, O3 & SO2",
  },
  {
    id: "city_comparison",
    label: "City Comparison",
    shortDesc: "Compare Lagos, Abuja, Nairobi & Accra live estimates",
  },
];

const POLLUTANT_CODES: PollutantCode[] = ["PM2.5", "PM10", "NO2", "O3", "SO2"];

export default function AssistantPanel({
  selectedLocation,
  observationTime,
  usAqi,
  aqiBand,
}: AssistantPanelProps) {
  const [assistantStatus, setAssistantStatus] =
    useState<AssistantStatusResponse | null>(null);
  const [statusLoading, setStatusLoading] = useState<boolean>(true);
  const [mode, setMode] = useState<AssistantMode>("ask");
  const [selectedPollutant, setSelectedPollutant] =
    useState<PollutantCode>("PM2.5");
  const [questionInput, setQuestionInput] = useState<string>("");
  const [chatEntries, setChatEntries] = useState<ChatEntry[]>([]);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorBanner, setErrorBanner] = useState<{
    title: string;
    message: string;
    isUnavailable: boolean;
  } | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const checkStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const status = await fetchAssistantStatus();
      setAssistantStatus(status);
    } catch {
      setAssistantStatus(null);
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    void checkStatus();
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, [checkStatus]);

  const suggestedPrompts: Array<{ label: string; mode: AssistantMode; prompt: string }> =
    React.useMemo(() => {
      const city = selectedLocation.city;
      return [
        {
          label: `Exercise safety in ${city}`,
          mode: "ask",
          prompt: `Is the air quality safe for outdoor exercise in ${city}?`,
        },
        {
          label: "Today's PM2.5 meaning",
          mode: "ask",
          prompt: `What does today's PM2.5 reading mean in ${selectedLocation.display_name}?`,
        },
        {
          label: "Elevated pollutants",
          mode: "ask",
          prompt: `Which pollutants are elevated in ${city} right now?`,
        },
        {
          label: "Children outdoors",
          mode: "ask",
          prompt: `What should I consider before taking my children outdoors in ${city}?`,
        },
        {
          label: "Daily activity plan",
          mode: "activity_planner",
          prompt: `Create a general daily activity plan for outdoor exercise, walking, cycling, outdoor events, and sensitive-group precautions in ${city} using available future forecast hours.`,
        },
        {
          label: `Explain ${selectedPollutant}`,
          mode: "pollutant_education",
          prompt: `Explain what ${selectedPollutant} is in accessible language and what the current model reading in ${city} indicates.`,
        },
        {
          label: "Compare all 4 cities",
          mode: "city_comparison",
          prompt:
            "Compare the verified model air quality estimates across Lagos, Abuja, Nairobi, and Accra, including timestamps and any missing data.",
        },
      ];
    }, [selectedLocation, selectedPollutant]);

  const submitQuestion = useCallback(
    async (
      rawQuestion: string,
      overrideMode?: AssistantMode,
      overridePollutant?: PollutantCode
    ) => {
      const trimmed = rawQuestion.trim();
      if (!trimmed) return;

      const targetMode = overrideMode ?? mode;
      const targetPollutant = overridePollutant ?? selectedPollutant;

      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      setIsSubmitting(true);
      setErrorBanner(null);

      // Build concise history from recent entries for this location
      const recentHistory: ConversationTurn[] = chatEntries
        .slice(-3)
        .flatMap((entry) => [
          { role: "user" as const, content: entry.question },
          {
            role: "assistant" as const,
            content: entry.response.sections.ai_interpretation.slice(0, 800),
          },
        ]);

      try {
        const res = await askAirwiseAssistant(
          {
            location_id: selectedLocation.id,
            mode: targetMode,
            question: trimmed,
            pollutant_code:
              targetMode === "pollutant_education" ? targetPollutant : null,
            history: recentHistory,
          },
          controller.signal
        );

        setChatEntries((prev) => [
          ...prev,
          {
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            question: trimmed,
            mode: targetMode,
            locationDisplayName: selectedLocation.display_name,
            response: res,
          },
        ]);
        setQuestionInput("");
      } catch (err) {
        if (isRequestCanceledError(err)) {
          return;
        }
        if (err instanceof ApiClientError) {
          const isUnavailable =
            err.errorCode === "assistant_unavailable" || err.statusCode === 503;
          setErrorBanner({
            title: isUnavailable
              ? "AIRWISE AI Assistant Unavailable (Backend Credentials Required)"
              : err.statusCode === 429
              ? "Gemini Rate Limit Reached"
              : err.isTimeout
              ? "Gemini Request Timed Out"
              : "Assistant Request Failed",
            message: err.message,
            isUnavailable,
          });
        } else {
          setErrorBanner({
            title: "Assistant Request Failed",
            message:
              err instanceof Error
                ? err.message
                : "Unable to contact the AIRWISE AI backend assistant endpoint.",
            isUnavailable: false,
          });
        }
      } finally {
        setIsSubmitting(false);
      }
    },
    [chatEntries, mode, selectedLocation, selectedPollutant]
  );

  const handleFormSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submitQuestion(questionInput);
  };

  return (
    <section
      id="section-assistant"
      aria-labelledby="heading-ai-assistant"
      className="rounded-2xl bg-gradient-to-br from-[#0F2926] via-[#142321] to-[#092C29] text-theme-text p-6 sm:p-8 border border-theme-accent/45 shadow-sm"
    >
      {/* Header & Selected Location Context */}
      <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4 border-b border-theme-border pb-5">
        <div>
          <div className="flex flex-wrap items-center gap-2 mb-2.5">
            {statusLoading ? (
              <span className="inline-flex items-center gap-2 rounded-full bg-theme-secondary border border-theme-border px-3 py-1 text-xs font-semibold text-theme-muted">
                Checking Gemini Assistant Status...
              </span>
            ) : assistantStatus?.configured ? (
              <span className="inline-flex items-center gap-2 rounded-full bg-emerald-500/15 border border-emerald-400/45 px-3 py-1 text-xs font-semibold text-emerald-300">
                <span className="h-2 w-2 rounded-full bg-emerald-400" aria-hidden="true" />
                Gemini Ready ({assistantStatus.model})
              </span>
            ) : (
              <span className="inline-flex items-center gap-2 rounded-full bg-amber-500/15 border border-amber-400/45 px-3 py-1 text-xs font-semibold text-amber-300">
                <span className="h-2 w-2 rounded-full bg-amber-400" aria-hidden="true" />
                Assistant Unavailable (GEMINI_API_KEY Not Set on Backend)
              </span>
            )}

            <span className="inline-flex items-center rounded-full bg-theme-secondary border border-theme-border px-3 py-1 text-xs font-semibold text-theme-mint">
              Context: {selectedLocation.display_name} ({selectedLocation.id})
            </span>
          </div>

          <h2 id="heading-ai-assistant" className="text-xl sm:text-2xl font-bold text-theme-text">
            AIRWISE AI Urban Air-Quality Assistant
          </h2>
          <p className="mt-1.5 text-sm text-theme-muted max-w-3xl">
            Ask questions, plan daily outdoor activities, explore pollutant science, or compare all four African cities.
            Every response is grounded strictly in verified Open-Meteo CAMS Global model data fetched by the FastAPI backend.
          </p>
        </div>

        {/* Live Context Pill */}
        <div className="rounded-xl bg-[#0B1415]/80 border border-theme-border p-3.5 text-xs space-y-1 shrink-0 min-w-[230px]">
          <div className="font-bold uppercase tracking-wider text-theme-mint">
            Active Grounding Context
          </div>
          <div className="text-theme-text font-semibold">
            {selectedLocation.display_name}
          </div>
          <div className="text-theme-muted">
            Model AQI:{" "}
            <strong className="text-theme-text">
              {usAqi !== null && usAqi !== undefined
                ? `${usAqi}${aqiBand ? ` (${aqiBand})` : ""}`
                : "Unavailable / Pending"}
            </strong>
          </div>
          <div className="text-theme-muted">
            Observation:{" "}
            <strong className="text-theme-text">
              {observationTime ?? "Synced on request"}
            </strong>
          </div>
        </div>
      </div>

      {/* Assistant Unavailable Explicit Banner */}
      {!statusLoading && assistantStatus && !assistantStatus.configured && (
        <div
          role="status"
          aria-live="polite"
          className="mt-5 rounded-xl border border-amber-400/45 bg-[#0B1415]/85 p-4 text-xs sm:text-sm text-theme-muted"
        >
          <p className="font-bold text-amber-300 mb-1">
            ASSISTANT UNAVAILABLE — Backend Gemini Credentials Required
          </p>
          <p>
            {assistantStatus.message} AIRWISE AI will not fabricate AI replies without a live backend Gemini API key.
            All live Open-Meteo AQI cards, pollutant readings, and hourly forecasts above remain fully operational.
          </p>
        </div>
      )}

      {/* Capability Mode Selector */}
      <div className="mt-6 space-y-4">
        <div
          role="tablist"
          aria-label="AIRWISE AI Assistant Capability Modes"
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5"
        >
          {MODE_TABS.map((tab) => {
            const isSelected = mode === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={isSelected}
                onClick={() => setMode(tab.id)}
                className={`text-left rounded-xl p-3 border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint ${
                  isSelected
                    ? "bg-[#14B8A6]/20 border-theme-mint text-theme-text shadow-sm"
                    : "bg-theme-card/85 border-theme-border text-theme-muted hover:bg-theme-secondary hover:text-theme-text"
                }`}
              >
                <div className="text-xs sm:text-sm font-bold">{tab.label}</div>
                <div className="text-[11px] opacity-85 mt-0.5 leading-snug">
                  {tab.shortDesc}
                </div>
              </button>
            );
          })}
        </div>

        {/* Pollutant focus pills when Pollutant Education mode is active */}
        {mode === "pollutant_education" && (
          <div className="flex flex-wrap items-center gap-2 rounded-xl bg-theme-card/70 border border-theme-border p-3">
            <span className="text-xs font-semibold text-theme-muted mr-1">
              Pollutant focus:
            </span>
            {POLLUTANT_CODES.map((code) => (
              <button
                key={code}
                type="button"
                onClick={() => setSelectedPollutant(code)}
                aria-pressed={selectedPollutant === code}
                className={`rounded-lg px-2.5 py-1 text-xs font-bold border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint ${
                  selectedPollutant === code
                    ? "bg-theme-accent text-[#0B1415] border-theme-mint"
                    : "bg-theme-secondary text-theme-mint border-theme-border hover:border-theme-accent"
                }`}
              >
                {code}
              </button>
            ))}
          </div>
        )}

        {/* Suggested Prompts */}
        <div className="space-y-2">
          <p className="text-xs font-bold uppercase tracking-wider text-theme-mint">
            Suggested Prompts ({selectedLocation.city})
          </p>
          <div className="flex flex-wrap gap-2">
            {suggestedPrompts.map((item) => (
              <button
                key={item.label}
                type="button"
                disabled={isSubmitting}
                onClick={() => {
                  setMode(item.mode);
                  setQuestionInput(item.prompt);
                  void submitQuestion(item.prompt, item.mode);
                }}
                className="rounded-lg bg-theme-secondary border border-theme-border px-3 py-1.5 text-xs font-medium text-theme-text hover:border-theme-accent hover:text-theme-mint focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint disabled:opacity-50 transition-colors"
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {/* Question Input Form */}
        <form onSubmit={handleFormSubmit} className="flex flex-col sm:flex-row gap-3">
          <label htmlFor="airwise-assistant-input" className="sr-only">
            Ask AIRWISE AI about air quality in {selectedLocation.display_name}
          </label>
          <input
            id="airwise-assistant-input"
            type="text"
            value={questionInput}
            onChange={(e) => setQuestionInput(e.target.value)}
            placeholder={`Ask about ${selectedLocation.city}'s air quality, PM2.5, exercise timing, or compare cities...`}
            maxLength={800}
            disabled={isSubmitting}
            className="flex-1 rounded-xl border border-theme-border bg-[#0B1415]/90 px-4 py-3 text-sm text-theme-text placeholder:text-theme-muted/70 focus:border-theme-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={isSubmitting || questionInput.trim().length < 2}
            className="rounded-xl bg-theme-accent px-5 py-3 text-sm font-bold text-[#0B1415] hover:bg-theme-mint focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint disabled:opacity-50 transition-colors shrink-0"
          >
            {isSubmitting ? "Analyzing Verified Data..." : "Ask AIRWISE AI"}
          </button>
        </form>

        {/* Loading State */}
        {isSubmitting && (
          <div
            role="status"
            aria-live="polite"
            className="rounded-xl border border-theme-accent/45 bg-[#0B1415]/85 p-4 flex items-center gap-3 text-sm text-theme-text"
          >
            <span
              aria-hidden="true"
              className="h-4 w-4 rounded-full border-2 border-theme-mint border-t-transparent animate-spin shrink-0"
            />
            <span>
              Grounding Gemini response in verified Open-Meteo CAMS Global data for{" "}
              <strong>{selectedLocation.display_name}</strong>...
            </span>
          </div>
        )}

        {/* Error / Unavailable Alert */}
        {errorBanner && (
          <div
            role="alert"
            aria-live="assertive"
            className={`rounded-xl border p-4 text-xs sm:text-sm ${
              errorBanner.isUnavailable
                ? "border-amber-400/50 bg-[#0B1415]/90 text-amber-100"
                : "border-red-500/50 bg-[#0B1415]/90 text-red-100"
            }`}
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <p className="font-bold">{errorBanner.title}</p>
                <p className="text-theme-muted mt-1">{errorBanner.message}</p>
              </div>
              <button
                type="button"
                onClick={() => void checkStatus()}
                className="self-start sm:self-auto rounded-lg border border-theme-border bg-theme-secondary px-3 py-1.5 text-xs font-semibold text-theme-mint hover:border-theme-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-theme-mint shrink-0"
              >
                Re-check Assistant Status
              </button>
            </div>
          </div>
        )}

        {/* Conversation Output Feed */}
        <div
          aria-label="AIRWISE AI conversation history"
          className="space-y-4 pt-2"
        >
          {chatEntries.length === 0 ? (
            <div className="rounded-xl bg-[#0B1415]/75 border border-theme-border p-5 text-xs sm:text-sm text-theme-muted space-y-2">
              <p className="font-semibold text-theme-text">
                Ready for grounded air-quality questions in {selectedLocation.display_name}.
              </p>
              <p>
                Every Gemini response separates{" "}
                <strong className="text-emerald-300">Verified Provider Data</strong>,{" "}
                <strong className="text-theme-mint">Future Forecast Context</strong>,{" "}
                <strong className="text-theme-text">AI Interpretation</strong>, and{" "}
                <strong className="text-amber-300">General Health Guidance</strong> so you can always see what comes directly from Open-Meteo CAMS Global vs. AI synthesis.
              </p>
            </div>
          ) : (
            [...chatEntries].reverse().map((entry) => {
              const { response } = entry;
              return (
                <article
                  key={entry.id}
                  className="rounded-xl bg-[#0B1415]/90 border border-theme-border p-5 space-y-4"
                >
                  {/* Turn Header */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-theme-border pb-3">
                    <div>
                      <span className="text-[11px] font-bold uppercase tracking-wider text-theme-mint">
                        {entry.locationDisplayName} • Mode: {entry.mode.replace("_", " ")}
                      </span>
                      <h3 className="text-sm sm:text-base font-bold text-theme-text mt-0.5">
                        “{entry.question}”
                      </h3>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-[11px]">
                      <span className="rounded bg-emerald-500/15 border border-emerald-400/40 px-2 py-0.5 font-semibold text-emerald-300">
                        Gemini ({response.model})
                      </span>
                      <span className="text-theme-muted">
                        Generated: {response.generated_at}
                      </span>
                    </div>
                  </div>

                  {/* 4 Distinct Integrity Sections */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3.5">
                    <div className="rounded-xl bg-theme-secondary/90 border border-emerald-500/30 p-4 space-y-1.5">
                      <span className="inline-block rounded bg-emerald-500/15 border border-emerald-400/40 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-300">
                        1. Verified Provider Data
                      </span>
                      <p className="text-xs sm:text-sm text-theme-text leading-relaxed">
                        {response.sections.verified_data_summary}
                      </p>
                      <p className="text-[11px] text-theme-muted pt-1">
                        Observation: {response.verified_context.observation_time ?? "Unavailable"} •
                        Retrieved: {response.verified_context.retrieval_time ?? "Unavailable"}
                      </p>
                    </div>

                    <div className="rounded-xl bg-theme-secondary/90 border border-theme-accent/35 p-4 space-y-1.5">
                      <span className="inline-block rounded bg-teal-500/15 border border-theme-accent/45 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-theme-mint">
                        2. Forecast Data (Future Hours Only)
                      </span>
                      <p className="text-xs sm:text-sm text-theme-text leading-relaxed">
                        {response.sections.forecast_context}
                      </p>
                    </div>
                  </div>

                  <div className="rounded-xl bg-theme-card border border-theme-mint/35 p-4 space-y-1.5">
                    <span className="inline-block rounded bg-[#14B8A6]/20 border border-theme-mint/50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-theme-mint">
                      3. AI Interpretation (Gemini)
                    </span>
                    <p className="text-sm text-theme-text leading-relaxed whitespace-pre-line">
                      {response.sections.ai_interpretation}
                    </p>
                  </div>

                  <div className="rounded-xl bg-theme-secondary/75 border border-amber-400/35 p-4 space-y-2">
                    <span className="inline-block rounded bg-amber-500/15 border border-amber-400/45 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-300">
                      4. General Health Guidance (Non-Medical) & Model Limitations
                    </span>
                    <p className="text-xs sm:text-sm text-theme-text leading-relaxed">
                      {response.sections.general_health_guidance}
                    </p>
                    <p className="text-xs text-theme-muted leading-relaxed border-t border-theme-border/70 pt-2">
                      {response.sections.model_limitations_notice}
                    </p>
                  </div>

                  {/* Verified 4-City Comparison Table when mode is city_comparison */}
                  {response.city_comparisons.length > 0 && (
                    <div className="rounded-xl bg-theme-card border border-theme-border p-4 overflow-x-auto">
                      <div className="text-xs font-bold uppercase tracking-wider text-theme-mint mb-2.5">
                        Verified 4-City Model Comparison Snapshot
                      </div>
                      <table className="w-full text-left border-collapse text-xs">
                        <thead>
                          <tr className="border-b border-theme-border text-theme-muted uppercase">
                            <th scope="col" className="py-2 pr-3">City</th>
                            <th scope="col" className="py-2 px-3">US AQI</th>
                            <th scope="col" className="py-2 px-3">Observation Time</th>
                            <th scope="col" className="py-2 pl-3">Missing Data Disclosure</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-theme-border/60">
                          {response.city_comparisons.map((citySnap) => (
                            <tr key={citySnap.location.id}>
                              <th scope="row" className="py-2 pr-3 font-semibold text-theme-text">
                                {citySnap.location.display_name}
                              </th>
                              <td className="py-2 px-3 font-bold text-theme-text">
                                {citySnap.us_aqi !== null
                                  ? `${citySnap.us_aqi} (${citySnap.aqi_band ?? ""})`
                                  : "DATA UNAVAILABLE"}
                              </td>
                              <td className="py-2 px-3 text-theme-muted">
                                {citySnap.observation_time
                                  ? `${citySnap.observation_time} (${citySnap.timezone})`
                                  : "Unavailable"}
                              </td>
                              <td className="py-2 pl-3 text-theme-muted">
                                {citySnap.missing_fields.length > 0
                                  ? `Missing: ${citySnap.missing_fields.join(", ")}`
                                  : "All 5 pollutants & AQI available"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Footer Attribution */}
                  <div className="pt-2 border-t border-theme-border flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-[11px] text-theme-muted">
                    <span>{response.attribution.provider_attribution}</span>
                    <span className="font-semibold text-theme-mint">
                      Backend-only Gemini key • Zero client exposure
                    </span>
                  </div>
                </article>
              );
            })
          )}
        </div>
      </div>
    </section>
  );
}
