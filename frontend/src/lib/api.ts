/**
 * Typed API client for the AIRWISE AI FastAPI backend.
 *
 * The frontend communicates strictly with the FastAPI backend and never
 * sends requests directly to Open-Meteo from the browser.
 */

import {
  AirQualityResponse,
  AssistantRequest,
  AssistantResponse,
  AssistantStatusResponse,
  DashboardResponse,
  HealthResponse,
  HistoricalAirQualityResponse,
  HistoricalCityComparisonResponse,
  HistoricalRangeDays,
  PredictiveIntelligenceResponse,
} from "@/types/dashboard";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_REQUEST_TIMEOUT_MS = 35000;
const ASSISTANT_POST_TIMEOUT_MS = 35000;
const COLD_START_RETRY_DELAY_MS = 1500;
const COLD_START_MAX_GET_RETRIES = 1;
const COLD_START_GATEWAY_STATUSES = new Set([502, 503, 504]);

export function getApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!configured) {
    return DEFAULT_API_BASE_URL;
  }
  return configured.replace(/\/+$/, "");
}

export class ApiClientError extends Error {
  public readonly statusCode?: number;
  public readonly errorCode?: string;
  public readonly isTimeout: boolean;

  constructor(
    message: string,
    statusCode?: number,
    errorCode?: string,
    isTimeout: boolean = false
  ) {
    super(message);
    this.name = "ApiClientError";
    this.statusCode = statusCode;
    this.errorCode = errorCode;
    this.isTimeout = isTimeout;
  }
}

export function isRequestCanceledError(err: unknown): boolean {
  return (
    err instanceof DOMException &&
    err.name === "AbortError"
  );
}

function waitWithAbort(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Request aborted by caller", "AbortError"));
      return;
    }

    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Request aborted by caller", "AbortError"));
    };

    const timer = setTimeout(() => {
      if (signal) {
        signal.removeEventListener("abort", onAbort);
      }
      resolve();
    }, delayMs);

    if (signal) {
      signal.addEventListener("abort", onAbort, { once: true });
    }
  });
}

function isNonJsonGatewayWakeupResponse(response: Response): boolean {
  if (!COLD_START_GATEWAY_STATUSES.has(response.status)) {
    return false;
  }
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  // FastAPI structured error payloads return application/json; Render/proxy cold-start
  // 502/503/504 responses are typically text/html or text/plain before Uvicorn binds.
  return !contentType.includes("application/json");
}

async function fetchSingleAttemptWithTimeout(
  url: string,
  options: RequestInit & { timeoutMs?: number } = {}
): Promise<Response> {
  const { timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, signal: callerSignal, ...rest } = options;

  const timeoutController = new AbortController();
  let timedOut = false;

  const timer = setTimeout(() => {
    timedOut = true;
    timeoutController.abort();
  }, timeoutMs);

  const onCallerAbort = () => {
    timeoutController.abort();
  };

  if (callerSignal) {
    if (callerSignal.aborted) {
      clearTimeout(timer);
      throw new DOMException("Request aborted by caller", "AbortError");
    }
    callerSignal.addEventListener("abort", onCallerAbort, { once: true });
  }

  try {
    return await fetch(url, {
      ...rest,
      signal: timeoutController.signal,
    });
  } catch (err) {
    if (timedOut) {
      throw new ApiClientError(
        `Request timed out after ${(timeoutMs / 1000).toFixed(0)}s waiting for FastAPI backend (the server may be waking up from idle—please retry).`,
        504,
        "client_timeout",
        true
      );
    }
    if (callerSignal?.aborted) {
      throw new DOMException("Request superseded by a newer location selection", "AbortError");
    }
    throw new ApiClientError(
      err instanceof Error
        ? `Network error contacting FastAPI backend (${err.message}).`
        : "Network error contacting FastAPI backend.",
      undefined,
      "network_error"
    );
  } finally {
    clearTimeout(timer);
    if (callerSignal) {
      callerSignal.removeEventListener("abort", onCallerAbort);
    }
  }
}

async function fetchWithTimeout(
  url: string,
  options: RequestInit & { timeoutMs?: number; retryOnColdStart?: boolean } = {}
): Promise<Response> {
  const {
    retryOnColdStart,
    method = "GET",
    signal: callerSignal,
    ...attemptOptions
  } = options;

  // Allow at most one bounded retry for idempotent GET requests during free-tier cold starts.
  // Non-idempotent requests (e.g., POST /assistant/ask) are never auto-retried.
  const canRetry =
    (retryOnColdStart ?? method.toUpperCase() === "GET") &&
    method.toUpperCase() === "GET";
  const maxAttempts = canRetry ? COLD_START_MAX_GET_RETRIES + 1 : 1;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetchSingleAttemptWithTimeout(url, {
        ...attemptOptions,
        method,
        signal: callerSignal,
      });

      if (attempt < maxAttempts && isNonJsonGatewayWakeupResponse(response)) {
        await waitWithAbort(COLD_START_RETRY_DELAY_MS, callerSignal ?? undefined);
        continue;
      }

      return response;
    } catch (err) {
      if (isRequestCanceledError(err)) {
        throw err;
      }

      const isColdStartRetryable =
        err instanceof ApiClientError &&
        (err.errorCode === "client_timeout" || err.errorCode === "network_error");

      if (attempt < maxAttempts && isColdStartRetryable) {
        await waitWithAbort(COLD_START_RETRY_DELAY_MS, callerSignal ?? undefined);
        continue;
      }

      throw err;
    }
  }

  throw new ApiClientError(
    "Unable to reach FastAPI backend after cold-start retry.",
    undefined,
    "network_error"
  );
}

export async function fetchBackendHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const url = `${getApiBaseUrl()}/api/v1/health`;
  const response = await fetchWithTimeout(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new ApiClientError(
      `Health endpoint returned HTTP ${response.status}`,
      response.status
    );
  }

  return (await response.json()) as HealthResponse;
}

export async function fetchDashboardData(
  locationId: string = "lagos-ng",
  signal?: AbortSignal
): Promise<DashboardResponse> {
  const params = new URLSearchParams({ location: locationId });
  const url = `${getApiBaseUrl()}/api/v1/dashboard?${params.toString()}`;

  const response = await fetchWithTimeout(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new ApiClientError(
      `Dashboard endpoint returned HTTP ${response.status}`,
      response.status
    );
  }

  return (await response.json()) as DashboardResponse;
}

export async function fetchLiveAirQuality(
  locationId: string = "lagos-ng",
  signal?: AbortSignal
): Promise<AirQualityResponse> {
  const params = new URLSearchParams({ location_id: locationId });
  const url = `${getApiBaseUrl()}/api/v1/air-quality?${params.toString()}`;

  const response = await fetchWithTimeout(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
    cache: "no-store",
  });

  if (!response.ok) {
    let errorMessage = `Air quality endpoint returned HTTP ${response.status}`;
    let errorCode: string | undefined;

    try {
      const errorPayload = (await response.json()) as {
        detail?: { message?: string; error_code?: string } | string;
      };
      if (typeof errorPayload?.detail === "string") {
        errorMessage = errorPayload.detail;
      } else if (errorPayload?.detail && typeof errorPayload.detail.message === "string") {
        errorMessage = errorPayload.detail.message;
        errorCode = errorPayload.detail.error_code;
      }
    } catch {
      // Ignore JSON parsing failure on non-200 error response
    }

    throw new ApiClientError(
      errorMessage,
      response.status,
      errorCode,
      response.status === 504
    );
  }

  return (await response.json()) as AirQualityResponse;
}

export async function fetchAssistantStatus(
  signal?: AbortSignal
): Promise<AssistantStatusResponse> {
  const url = `${getApiBaseUrl()}/api/v1/assistant/status`;
  const response = await fetchWithTimeout(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new ApiClientError(
      `Assistant status endpoint returned HTTP ${response.status}`,
      response.status
    );
  }

  return (await response.json()) as AssistantStatusResponse;
}

export async function askAirwiseAssistant(
  payload: AssistantRequest,
  signal?: AbortSignal
): Promise<AssistantResponse> {
  const url = `${getApiBaseUrl()}/api/v1/assistant/ask`;
  const response = await fetchWithTimeout(url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal,
    cache: "no-store",
    timeoutMs: ASSISTANT_POST_TIMEOUT_MS,
    retryOnColdStart: false,
  });

  if (!response.ok) {
    let errorMessage = `Assistant endpoint returned HTTP ${response.status}`;
    let errorCode: string | undefined;

    try {
      const errorPayload = (await response.json()) as {
        detail?: { message?: string; error_code?: string } | string;
      };
      if (typeof errorPayload?.detail === "string") {
        errorMessage = errorPayload.detail;
      } else if (errorPayload?.detail && typeof errorPayload.detail.message === "string") {
        errorMessage = errorPayload.detail.message;
        errorCode = errorPayload.detail.error_code;
      }
    } catch {
      // Ignore JSON parsing failure on non-200 error response
    }

    throw new ApiClientError(
      errorMessage,
      response.status,
      errorCode,
      response.status === 504
    );
  }

  return (await response.json()) as AssistantResponse;
}

export async function fetchHistoricalAirQuality(
  locationId: string = "lagos-ng",
  days: HistoricalRangeDays = 7,
  options?: { forceRefresh?: boolean; signal?: AbortSignal }
): Promise<HistoricalAirQualityResponse> {
  const params = new URLSearchParams({
    location_id: locationId,
    days: String(days),
  });
  if (options?.forceRefresh) {
    params.set("force_refresh", "true");
  }
  const url = `${getApiBaseUrl()}/api/v1/air-quality/history?${params.toString()}`;

  const response = await fetchWithTimeout(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: options?.signal,
    cache: "no-store",
    timeoutMs: DEFAULT_REQUEST_TIMEOUT_MS,
  });

  if (!response.ok) {
    let errorMessage = `Historical air quality endpoint returned HTTP ${response.status}`;
    let errorCode: string | undefined;

    try {
      const errorPayload = (await response.json()) as {
        detail?: { message?: string; error_code?: string } | string;
      };
      if (typeof errorPayload?.detail === "string") {
        errorMessage = errorPayload.detail;
      } else if (errorPayload?.detail && typeof errorPayload.detail.message === "string") {
        errorMessage = errorPayload.detail.message;
        errorCode = errorPayload.detail.error_code;
      }
    } catch {
      // Ignore JSON parsing failure on non-200 error response
    }

    throw new ApiClientError(
      errorMessage,
      response.status,
      errorCode,
      response.status === 504
    );
  }

  return (await response.json()) as HistoricalAirQualityResponse;
}

export async function fetchHistoricalCityComparison(
  days: HistoricalRangeDays = 7,
  options?: { forceRefresh?: boolean; signal?: AbortSignal }
): Promise<HistoricalCityComparisonResponse> {
  const params = new URLSearchParams({ days: String(days) });
  if (options?.forceRefresh) {
    params.set("force_refresh", "true");
  }
  const url = `${getApiBaseUrl()}/api/v1/air-quality/history/compare?${params.toString()}`;

  const response = await fetchWithTimeout(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: options?.signal,
    cache: "no-store",
    timeoutMs: DEFAULT_REQUEST_TIMEOUT_MS,
  });

  if (!response.ok) {
    let errorMessage = `Historical city comparison endpoint returned HTTP ${response.status}`;
    let errorCode: string | undefined;

    try {
      const errorPayload = (await response.json()) as {
        detail?: { message?: string; error_code?: string } | string;
      };
      if (typeof errorPayload?.detail === "string") {
        errorMessage = errorPayload.detail;
      } else if (errorPayload?.detail && typeof errorPayload.detail.message === "string") {
        errorMessage = errorPayload.detail.message;
        errorCode = errorPayload.detail.error_code;
      }
    } catch {
      // Ignore JSON parsing failure on non-200 error response
    }

    throw new ApiClientError(
      errorMessage,
      response.status,
      errorCode,
      response.status === 504
    );
  }

  return (await response.json()) as HistoricalCityComparisonResponse;
}

export async function fetchPredictiveIntelligence(
  locationId: string = "lagos-ng",
  signal?: AbortSignal
): Promise<PredictiveIntelligenceResponse> {
  const params = new URLSearchParams({ location_id: locationId });
  const url = `${getApiBaseUrl()}/api/v1/air-quality/intelligence?${params.toString()}`;

  const response = await fetchWithTimeout(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
    cache: "no-store",
    timeoutMs: DEFAULT_REQUEST_TIMEOUT_MS,
  });

  if (!response.ok) {
    let errorMessage = `Predictive intelligence endpoint returned HTTP ${response.status}`;
    let errorCode: string | undefined;

    try {
      const errorPayload = (await response.json()) as {
        detail?: { message?: string; error_code?: string } | string;
      };
      if (typeof errorPayload?.detail === "string") {
        errorMessage = errorPayload.detail;
      } else if (errorPayload?.detail && typeof errorPayload.detail.message === "string") {
        errorMessage = errorPayload.detail.message;
        errorCode = errorPayload.detail.error_code;
      }
    } catch {
      // Ignore JSON parsing failure on non-200 error response
    }

    throw new ApiClientError(
      errorMessage,
      response.status,
      errorCode,
      response.status === 504
    );
  }

  return (await response.json()) as PredictiveIntelligenceResponse;
}



