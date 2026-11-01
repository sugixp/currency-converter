// Thin client for the Currency Converter API: builds URLs, applies a timeout
// and turns every failure into an ApiError with a user-friendly message.

import { API_BASE_URL, REQUEST_TIMEOUT_MS } from "./config.js";

const FRIENDLY_MESSAGES = {
  invalid_request: "Please fill in the amount and both currencies.",
  invalid_currency: "We don't have rates for that currency. Pick another one from the list.",
  unknown_currency: "We don't have rates for that currency. Pick another one from the list.",
  invalid_days: "That history range isn't available.",
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

async function request(path, params, { signal } = {}) {
  const url = new URL(path, API_BASE_URL);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }

  // One controller aborts the fetch on timeout or when the caller cancels
  // (e.g. the user changed the currency before the previous answer arrived).
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);
  const cancel = () => controller.abort();
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
