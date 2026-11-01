// Thin client for the Currency Converter API: builds URLs, applies a timeout,
// waits for a sleeping server to wake up and turns every failure into an
// ApiError with a user-friendly message.

import {
  API_BASE_URL,
  REQUEST_TIMEOUT_MS,
  WAKE_UP_TIMEOUT_MS,
  WAKING_NOTICE_DELAY_MS,
} from "./config.js";

const WAKE_UP_RETRY_MS = 3000;
// A network error this fast cannot be a server booting (Render holds the
// request open while it boots): it is a blocked request, DNS or no internet.
const FAST_FAILURE_MS = 2000;
const FAST_FAILURES_BEFORE_GIVING_UP = 2;

const FRIENDLY_MESSAGES = {
  invalid_request: "Please fill in the amount and both currencies.",
  invalid_currency: "We don't have rates for that currency. Pick another one from the list.",
  unknown_currency: "We don't have rates for that currency. Pick another one from the list.",
  invalid_days: "That history range isn't available.",
  history_paused:
    "The history chart is paused to save this month's exchange rate quota. Conversions still work.",
  provider_rate_limited:
    "We've used up our exchange rate quota for now. Please try again later.",
  provider_unavailable:
    "The exchange rate service is temporarily unavailable. Please try again in a few minutes.",
  provider_auth_error:
    "Our exchange rate provider isn't responding correctly right now. Please try again later.",
  provider_error:
    "Our exchange rate provider isn't responding correctly right now. Please try again later.",
  network: "Can't reach the converter. Check your connection or try again shortly.",
  unreachable:
    "Can't reach the server. Check your connection, or whether a browser extension or network filter is blocking onrender.com.",
  offline: "You seem to be offline. Check your internet connection and try again.",
  timeout: "The server is taking too long to respond. Please try again.",
  wake_timeout: "The server is taking too long to wake up. Please try again in a minute.",
};

// For these codes the API's own message is already specific and friendly
// (e.g. "Amount must be greater than zero.").
const USE_SERVER_DETAIL = new Set(["invalid_amount"]);

export class ApiError extends Error {
  constructor(code, message, status = null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export function getCurrencies(options) {
  return request("/currencies", {}, options);
}

export function convert({ from, to, amount }, options) {
  return request("/convert", { from, to, amount }, options);
}

export function getHistory({ from, to, days }, options) {
  return request("/history", { from, to, days }, options);
}

// ---- Waking up the server ------------------------------------------------------
// The free hosting plan sleeps after 15 idle minutes. Measured on Render: a
// request to a sleeping service is *held open* until it boots (~20 s in our
// tests, "about a minute" per the docs) and then answered normally. So we send
// a single /health request and keep it open for the whole wake-up window
// instead of cancelling and retrying, and we tell apart three cases:
// - slow answer: the server is booting, show "waking up";
// - fast network errors: not a boot at all (blocked, DNS, no internet);
// - browser offline.
// Concurrent callers share the same wake-up attempt.

let serverAwake = false;
let wakeUpPromise = null;
const statusListeners = new Set();

/** Subscribe to "waking" | "awake" | "unreachable" server status changes. */
export function onServerStatus(listener) {
  statusListeners.add(listener);
}

function emitStatus(status) {
  for (const listener of statusListeners) listener(status);
}

function ensureAwake() {
  if (serverAwake) return Promise.resolve();
  wakeUpPromise ??= wakeUp().finally(() => {
    wakeUpPromise = null;
  });
  return wakeUpPromise;
}

async function wakeUp() {
  const deadline = Date.now() + WAKE_UP_TIMEOUT_MS;
  let fastFailures = 0;

  while (Date.now() < deadline) {
    if (!navigator.onLine) {
      emitStatus("unreachable");
      throw buildError("offline");
    }

    // Only mention waking up while a request is actually pending for a while.
    const notice = setTimeout(() => emitStatus("waking"), WAKING_NOTICE_DELAY_MS);
    const startedAt = Date.now();
    const outcome = await checkHealth(deadline - Date.now());
    clearTimeout(notice);

    if (outcome === "ok") {
      serverAwake = true;
      emitStatus("awake");
      return;
    }
    if (outcome === "timeout") break; // the whole window was used by one request

    const failedFast = outcome === "network" && Date.now() - startedAt < FAST_FAILURE_MS;
    fastFailures = failedFast ? fastFailures + 1 : 0;
    if (fastFailures >= FAST_FAILURES_BEFORE_GIVING_UP) {
      emitStatus("unreachable");
      throw buildError(navigator.onLine ? "unreachable" : "offline");
    }
    // A slow network error or an unexpected answer (e.g. a proxy error page
    // while booting): wait a moment and ask again within the same window.
    await new Promise((resolve) => setTimeout(resolve, WAKE_UP_RETRY_MS));
  }
  emitStatus("unreachable");
  throw buildError("wake_timeout");
}

/** "ok" | "timeout" | "network" | "unexpected" */
async function checkHealth(timeoutMs) {
  try {
    const body = await fetchJson(new URL("/health", API_BASE_URL), timeoutMs);
    return body?.status === "ok" ? "ok" : "unexpected";
  } catch (error) {
    if (error.code === "timeout" || error.code === "network") return error.code;
    return "unexpected";
  }
}

// ---- Requests ------------------------------------------------------------------

async function request(path, params, { signal } = {}) {
  const url = new URL(path, API_BASE_URL);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }

  await ensureAwake();
  try {
    return await fetchJson(url, REQUEST_TIMEOUT_MS, signal);
  } catch (error) {
    const serverMayBeAsleep = error.code === "network" || error.code === "timeout";
    if (!serverMayBeAsleep || signal?.aborted) throw error;
    // The server may have gone back to sleep since the last request:
    // wake it up and try once more.
    serverAwake = false;
    await ensureAwake();
    return fetchJson(url, REQUEST_TIMEOUT_MS, signal);
  }
}

async function fetchJson(url, timeoutMs, signal) {
  // One controller aborts the fetch on timeout or when the caller cancels
  // (e.g. the user changed the currency before the previous answer arrived).
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const cancel = () => controller.abort();
  if (signal?.aborted) cancel();
  signal?.addEventListener("abort", cancel);

  try {
    let response;
    try {
      response = await fetch(url, { signal: controller.signal });
    } catch (error) {
      if (signal?.aborted) throw error; // cancelled on purpose: let the caller ignore it
      throw buildError(timedOut ? "timeout" : "network");
    }

    const body = await response.json().catch(() => null);
    if (!response.ok) {
      throw buildError(body?.error ?? `http_${response.status}`, body?.detail, response.status);
    }
    return body;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

function buildError(code, detail = null, status = null) {
  let message = FRIENDLY_MESSAGES[code];
  if (USE_SERVER_DETAIL.has(code) && detail) message = detail;
  if (!message) {
    message =
      status >= 500
        ? "Something went wrong on our side. Please try again later."
        : "Something went wrong. Please try again.";
  }
  return new ApiError(code, message, status);
}
