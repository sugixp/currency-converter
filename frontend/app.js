import { convert, getCurrencies, getHistory, onServerStatus } from "./api.js";
import { SNAPSHOT_STALE_DAYS } from "./config.js";
import { createHistoryChart, formatRate, isChartAvailable } from "./history-chart.js";
import {
  loadSnapshot,
  snapshotAgeDays,
  snapshotConversion,
  snapshotCurrencies,
  snapshotHistory,
} from "./snapshot.js";

// Shown first in both selects, in this order (only if the API offers them).
const POPULAR_CODES = ["USD", "EUR", "BRL", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "ARS", "MXN"];
const DEFAULTS = { from: "USD", to: "BRL", amount: "100" };
const STORAGE_KEY = "currency-converter:last-conversion";
const PLACEHOLDER = "— — —";
const HISTORY_DAYS = 30;

// Errors about the user's input; everything else means "live rates unavailable".
const INPUT_ERRORS = new Set(["invalid_amount", "invalid_currency", "unknown_currency", "invalid_request"]);

const elements = {
  form: document.getElementById("converter-form"),
  amount: document.getElementById("amount"),
  amountError: document.getElementById("amount-error"),
  from: document.getElementById("from"),
  to: document.getElementById("to"),
  swap: document.getElementById("swap"),
  convert: document.getElementById("convert"),
  alert: document.getElementById("alert"),
  alertMessage: document.getElementById("alert-message"),
  alertRetry: document.getElementById("alert-retry"),
  result: document.getElementById("result"),
  resultFrom: document.getElementById("result-from"),
  resultValue: document.getElementById("result-value"),
  resultText: document.getElementById("result-text"),
  resultRate: document.getElementById("result-rate"),
  resultTime: document.getElementById("result-time"),
  ratesSourceText: document.getElementById("rates-source-text"),
  ratesRetry: document.getElementById("rates-retry"),
  historyPair: document.getElementById("history-pair"),
  historyChange: document.getElementById("history-change"),
  historyLow: document.getElementById("history-low"),
  historyHigh: document.getElementById("history-high"),
  historySource: document.getElementById("history-source"),
  historyChartWrap: document.getElementById("history-chart-wrap"),
  historyCanvas: document.getElementById("history-chart"),
  historyAlert: document.getElementById("history-alert"),
  historyAlertMessage: document.getElementById("history-alert-message"),
  historyRetry: document.getElementById("history-retry"),
  serverStatus: document.getElementById("server-status"),
};

// Only the latest conversion request matters: starting a new one aborts the
// previous, so a slow old answer can never overwrite a newer result.
let conversionController = null;
let historyController = null;
let historyChart = null;
let retryAction = null;

// The snapshot (saved rates published with the site) lets the page show values
// at once; live API answers replace them. Once the API has answered, there is
// no point showing older saved values first, so the snapshot steps aside.
let snapshot = null;
let liveRatesWorking = false;
let liveHistoryWorking = false;
let currenciesFilled = false;

init();

function init() {
  const saved = loadSavedConversion();
  elements.amount.value = saved.amount;
  renderCapsule(PLACEHOLDER);

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    runConversion();
  });
  elements.from.addEventListener("change", onPairChange);
  elements.to.addEventListener("change", onPairChange);
  elements.swap.addEventListener("click", swapCurrencies);
  elements.amount.addEventListener("input", () => setAmountError(null));
  elements.alertRetry.addEventListener("click", () => retryAction?.());
  elements.ratesRetry.addEventListener("click", onPairChange);
  elements.historyRetry.addEventListener("click", loadHistory);
  // A sleeping server is expected on free hosting. With saved rates on screen
  // the small source line already says "updating…"; the banner is only for
  // when there is nothing to show yet.
  onServerStatus((status) => {
    elements.serverStatus.hidden = status !== "waking" || snapshot !== null;
  });

  setFormEnabled(false);
  setLoadingOption("Loading currencies…");
  loadSnapshot().then((loaded) => {
    snapshot = loaded;
    if (!snapshot) return;
    elements.serverStatus.hidden = true; // saved values are on screen now
    if (!currenciesFilled) fillCurrencies(snapshotCurrencies(snapshot), saved);
  });
  loadCurrencies(saved);
}

// ---- Currencies ------------------------------------------------------------

async function loadCurrencies(selection) {
  hideAlert();
  try {
    const { currencies } = await getCurrencies();
    // If the snapshot already filled the selects, keep them: rebuilding would
    // reset the user's choice and make the page jump.
    if (!currenciesFilled) fillCurrencies(currencies, selection);
  } catch (error) {
    if (currenciesFilled) return; // the snapshot's list is on screen
    setLoadingOption("Currencies unavailable");
    showAlert(error.message, () => loadCurrencies(selection));
  }
}

function fillCurrencies(currencies, selection) {
  fillSelect(elements.from, currencies, selection.from);
  fillSelect(elements.to, currencies, selection.to);
  currenciesFilled = true;
  setFormEnabled(true);
  onPairChange();
}

function fillSelect(select, currencies, selectedCode) {
  const byCode = new Map(currencies.map((currency) => [currency.code, currency]));
  const popular = POPULAR_CODES.filter((code) => byCode.has(code)).map((code) => byCode.get(code));

  select.replaceChildren(
    buildGroup("Popular", popular),
    buildGroup("All currencies", currencies), // already sorted by code
  );
  select.value = byCode.has(selectedCode) ? selectedCode : popular[0]?.code ?? currencies[0]?.code;
}

function buildGroup(label, currencies) {
  const group = document.createElement("optgroup");
  group.label = label;
  for (const { code, name } of currencies) {
    group.append(new Option(code === name ? code : `${code} — ${name}`, code));
  }
  return group;
}

function setLoadingOption(text) {
  for (const select of [elements.from, elements.to]) {
    select.replaceChildren(new Option(text, ""));
  }
}

function setFormEnabled(enabled) {
  for (const control of [elements.from, elements.to, elements.swap, elements.convert]) {
    control.disabled = !enabled;
  }
}

// ---- Conversion --------------------------------------------------------------

async function runConversion() {
  const amount = normalizeAmount(elements.amount.value);
  if (!amount) {
    setAmountError("Enter an amount to convert.");
    return;
  }
  setAmountError(null);
  hideAlert();

  const request = { from: elements.from.value, to: elements.to.value, amount };
  conversionController?.abort();
  const controller = new AbortController();
  conversionController = controller;

  // Show the saved rates right away while the live answer is on its way.
  const provisional =
    snapshot && !liveRatesWorking ? snapshotConversion(snapshot, request.from, request.to, amount) : null;
  if (provisional) {
    renderResult(provisional);
    setRatesSource("snapshot", { updating: true });
  }
  setBusy(true);

  try {
    const result = await convert(request, { signal: controller.signal });
    liveRatesWorking = true;
    // Replace the provisional numbers in place, without replaying the entrance animation.
    renderResult(result, { animate: !provisional });
    setRatesSource("live");
    saveConversion({ from: request.from, to: request.to, amount: elements.amount.value.trim() });
  } catch (error) {
    if (controller.signal.aborted) return; // superseded by a newer request
    if (INPUT_ERRORS.has(error.code)) {
      clearResult();
      setRatesSource(null);
      if (error.code === "invalid_amount") setAmountError(error.message);
      else showAlert(error.message);
      return;
    }
    liveRatesWorking = false;
    // The server may also fall asleep mid-session: fall back to the saved rates then too.
    const fallback = provisional ?? (snapshot && snapshotConversion(snapshot, request.from, request.to, amount));
    if (fallback) {
      if (!provisional) renderResult(fallback);
      setRatesSource("snapshot", { updating: false }); // keep the saved values, no error screen
    } else {
      clearResult();
      setRatesSource(null);
      showAlert(error.message, runConversion);
    }
  } finally {
    if (conversionController === controller) setBusy(false);
  }
}

function swapCurrencies() {
  [elements.from.value, elements.to.value] = [elements.to.value, elements.from.value];
  elements.swap.classList.remove("is-swapping");
  void elements.swap.offsetWidth; // restart the icon animation
  elements.swap.classList.add("is-swapping");
  onPairChange();
}

// The amount only affects the conversion; the history depends on the pair alone.
function onPairChange() {
  runConversion();
  loadHistory();
}

/**
 * Accepts both "1.234,56" and "1,234.56" styles: when both separators appear,
 * the last one is the decimal separator. A lone comma is a decimal comma.
 * Anything else is sent as typed and validated by the API.
 */
function normalizeAmount(raw) {
  let value = raw.replace(/\s/g, "");
  const lastComma = value.lastIndexOf(",");
  const lastDot = value.lastIndexOf(".");

  if (lastComma !== -1 && lastDot !== -1) {
    const decimalSeparator = lastComma > lastDot ? "," : ".";
    const groupSeparator = decimalSeparator === "," ? "." : ",";
    value = value.split(groupSeparator).join("").replace(decimalSeparator, ".");
  } else if (lastComma !== -1 && value.indexOf(",") === lastComma) {
    value = value.replace(",", ".");
  }
  return value;
}

// ---- Where the numbers come from ---------------------------------------------

/** source: "live" | "snapshot" | null (nothing shown). */
function setRatesSource(source, { updating = false } = {}) {
  const line = elements.ratesSourceText.parentElement;
  elements.ratesRetry.hidden = true;
  line.classList.remove("is-warning");

  if (source === "live") {
    elements.ratesSourceText.textContent = "Live rates";
  } else if (source === "snapshot") {
    const stale = snapshotAgeDays(snapshot) > SNAPSHOT_STALE_DAYS;
    const status = updating ? "updating…" : "live rates unavailable right now";
    elements.ratesSourceText.textContent = `${describeSnapshot(stale)} · ${status}`;
    line.classList.toggle("is-warning", stale || !updating);
    elements.ratesRetry.hidden = updating;
  } else {
    elements.ratesSourceText.textContent = "";
  }
}

function describeSnapshot(stale) {
  const timestamp = new Date(snapshot.latest.timestamp);
  if (stale) {
    const day = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(timestamp);
    return `Saved rates from ${day}, ${snapshotAgeDays(snapshot)} days ago, may be outdated`;
  }
  const sameDay = timestamp.toISOString().slice(0, 10) === new Date().toISOString().slice(0, 10);
  const time = new Intl.DateTimeFormat(undefined, {
    ...(sameDay ? {} : { month: "short", day: "numeric" }),
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "UTC",
  }).format(timestamp);
  return `Rates from ${time} UTC`;
}

// ---- History -------------------------------------------------------------------

async function loadHistory() {
  const from = elements.from.value;
  const to = elements.to.value;
  if (!from || !to) return;

  historyController?.abort();
  const controller = new AbortController();
  historyController = controller;
  elements.historyAlert.hidden = true;
  elements.historyPair.textContent = `${from} → ${to}`;

  const provisional = snapshot && !liveHistoryWorking ? snapshotHistory(snapshot, from, to) : null;
  if (provisional) {
    renderHistory(provisional);
    elements.historySource.textContent = "Saved data · updating…";
  } else {
    elements.historySource.textContent = "";
  }
  elements.historyChartWrap.setAttribute("aria-busy", "true");

  try {
    const history = await getHistory({ from, to, days: HISTORY_DAYS }, { signal: controller.signal });
    liveHistoryWorking = true;
    renderHistory(history);
    elements.historySource.textContent = "";
  } catch (error) {
    if (controller.signal.aborted) return;
    liveHistoryWorking = false;
    const fallback = provisional ?? (snapshot && snapshotHistory(snapshot, from, to));
    if (fallback) {
      if (!provisional) renderHistory(fallback);
      elements.historySource.textContent =
        error.code === "history_paused"
          ? "Saved data · live history paused to save this month's quota"
          : "Saved data · live history unavailable right now";
    } else {
      clearHistory();
      showHistoryAlert(error.message, { retry: true });
    }
  } finally {
    if (historyController === controller) {
      elements.historyChartWrap.setAttribute("aria-busy", "false");
    }
  }
}

function renderHistory(history) {
  const points = history.points.map((point) => ({ date: point.date, rate: Number(point.rate) }));
  if (points.length < 2) {
    clearHistory();
    showHistoryAlert("Not enough history for this pair yet.");
    return;
  }

  const first = points[0];
  const last = points.at(-1);
  const low = points.reduce((min, point) => (point.rate < min.rate ? point : min));
  const high = points.reduce((max, point) => (point.rate > max.rate ? point : max));
  const change = ((last.rate - first.rate) / first.rate) * 100;

  const changeText = `${change >= 0 ? "▲ +" : "▼ −"}${formatPercent(Math.abs(change))}`;
  elements.historyChange.textContent = changeText;
  elements.historyChange.className = change >= 0 ? "trend-up" : "trend-down";
  renderStat(elements.historyLow, low);
  renderStat(elements.historyHigh, high);

  const summary =
    `${history.from} to ${history.to} over the last ${points.length} days: ` +
    `${formatRate(first.rate)} on ${formatDay(first.date)}, ${formatRate(last.rate)} on ${formatDay(last.date)} ` +
    `(${change >= 0 ? "up" : "down"} ${formatPercent(Math.abs(change))}). ` +
    `Low ${formatRate(low.rate)}, high ${formatRate(high.rate)}.`;
  elements.historyCanvas.setAttribute("aria-label", summary);

  if (!isChartAvailable()) {
    elements.historyChartWrap.hidden = true;
    showHistoryAlert("The chart couldn't load, but the summary above is up to date.");
    return;
  }
  elements.historyChartWrap.hidden = false;
  historyChart ??= createHistoryChart(elements.historyCanvas);
  historyChart.update(history);
}

function renderStat(element, point) {
  const day = document.createElement("small");
  day.textContent = formatDay(point.date);
  element.replaceChildren(formatRate(point.rate), day);
}

function clearHistory() {
  // Never leave the previous pair's chart on screen under the new pair's title.
  elements.historyChartWrap.hidden = true;
  elements.historySource.textContent = "";
  for (const element of [elements.historyChange, elements.historyLow, elements.historyHigh]) {
    element.textContent = "—";
    element.className = "";
  }
}

function showHistoryAlert(message, { retry = false } = {}) {
  elements.historyAlertMessage.textContent = message;
  elements.historyRetry.hidden = !retry;
  elements.historyAlert.hidden = false;
}

function formatDay(isoDate) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone: "UTC" }).format(
    new Date(isoDate),
  );
}

function formatPercent(value) {
  return `${new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}%`;
}

// ---- Rendering -----------------------------------------------------------------

function renderResult(result, { animate = true } = {}) {
  const amount = formatNumber(result.amount, { maximumFractionDigits: 20 });
  const converted = formatNumber(result.converted_amount, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const rate = formatNumber(result.rate, { maximumFractionDigits: 6 });
  const publishedAt = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(result.rate_timestamp));

  elements.resultFrom.textContent = `${amount} ${result.from} =`;
  renderCapsule(converted, result.to, { animate });
  elements.resultRate.textContent = `1 ${result.from} = ${rate} ${result.to}`;
  elements.resultTime.textContent = publishedAt;
  // The capsule is hidden from screen readers; this sentence is what they announce.
  elements.resultText.textContent = `${amount} ${result.from} equals ${converted} ${result.to}.`;
}

function clearResult() {
  elements.resultFrom.innerHTML = "&nbsp;";
  renderCapsule(PLACEHOLDER);
  elements.resultRate.textContent = "—";
  elements.resultTime.textContent = "—";
  elements.resultText.textContent = "";
}

/** Shows the converted value and its currency code together in one capsule. */
function renderCapsule(value, code = null, { animate = true } = {}) {
  const capsule = elements.resultValue;
  const valueSpan = document.createElement("span");
  valueSpan.textContent = value;
  const parts = [valueSpan];
  if (code) {
    const codeSpan = document.createElement("span");
    codeSpan.className = "capsule-code";
    codeSpan.textContent = code;
    parts.push(codeSpan);
  }
  capsule.replaceChildren(...parts);
  capsule.classList.toggle("capsule--empty", !code);
  // The font size shrinks with the text length so large values never overflow.
  capsule.style.setProperty("--chars", value.length + (code ? code.length + 1 : 0));
  if (animate) {
    // Restart the entrance animation for every new value.
    capsule.style.animation = "none";
    void capsule.offsetWidth;
    capsule.style.animation = "";
  }
}

function formatNumber(value, options) {
  // Modern browsers format numeric strings exactly, without a float round-trip.
  return new Intl.NumberFormat(undefined, options).format(value);
}

function setBusy(busy) {
  elements.result.setAttribute("aria-busy", String(busy));
  elements.convert.textContent = busy ? "Converting…" : "Convert";
}

function setAmountError(message) {
  elements.amountError.textContent = message ?? "";
  elements.amountError.hidden = !message;
  if (message) {
    elements.amount.setAttribute("aria-invalid", "true");
  } else {
    elements.amount.removeAttribute("aria-invalid");
  }
}

function showAlert(message, retry = null) {
  elements.alertMessage.textContent = message;
  retryAction = retry;
  elements.alertRetry.hidden = !retry;
  elements.alert.hidden = false;
}

function hideAlert() {
  elements.alert.hidden = true;
  retryAction = null;
}

// ---- Persistence ---------------------------------------------------------------

function loadSavedConversion() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORAGE_KEY)) };
  } catch {
    return { ...DEFAULTS };
  }
}

function saveConversion(conversion) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversion));
  } catch {
    // Storage can be unavailable (private mode, quota); remembering is optional.
  }
}
