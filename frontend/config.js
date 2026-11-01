// The only place that knows where the API lives. The right URL is picked
// from the page's hostname, so the same file works locally and on GitHub Pages.
const PRODUCTION_API_URL = "https://currency-converter-api-93lo.onrender.com";
const DEVELOPMENT_API_URL = "http://localhost:8000";
const LOCAL_HOSTNAMES = ["localhost", "127.0.0.1", "[::1]"];

export const API_BASE_URL = LOCAL_HOSTNAMES.includes(window.location.hostname)
  ? DEVELOPMENT_API_URL
  : PRODUCTION_API_URL;

// Requests slower than this show a "taking too long" message.
export const REQUEST_TIMEOUT_MS = 10000;

// Render's free plan puts the API to sleep after 15 idle minutes and takes
// about a minute to wake it up. Show a notice if waking takes longer than
// WAKING_NOTICE_DELAY_MS, and give up only after WAKE_UP_TIMEOUT_MS.
export const WAKING_NOTICE_DELAY_MS = 2500;
export const WAKE_UP_TIMEOUT_MS = 90000;
