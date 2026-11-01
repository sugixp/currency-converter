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
const HEALTH_ATTEMPT_TIMEOUT_MS = 30000;

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
// The free hosting plan sleeps after 15 idle minutes. Before the first request
// (and after a request fails as if the server were gone) we poll /health until
// it answers, telling the page so it can show a "waking up" notice instead of
// an error. Concurrent callers share the same wake-up attempt.

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
  // Only mention waking up if it is actually slow; a healthy server answers at once.
  const notice = setTimeout(() => emitStatus("waking"), WAKING_NOTICE_DELAY_MS);
  try {
    while (Date.now() < deadline) {
      if (await isHealthy(Math.min(HEALTH_ATTEMPT_TIMEOUT_MS, deadline - Date.now()))) {
        serverAwake = true;
        emitStatus("awake");
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, WAKE_UP_RETRY_MS));
    }
    emitStatus("unreachable");
    throw buildError("wake_timeout");
  } finally {
    clearTimeout(notice);
  }
}

async function isHealthy(timeoutMs) {
  try {
    // While the server boots, the host may hold the request or answer with a
    // loading page (no CORS headers): both just mean "not yet".
    const body = await fetchJson(new URL("/health", API_BASE_URL), timeoutMs);
    return body?.status === "ok";
  } catch {
    return false;
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
