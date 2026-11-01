import { convert, getCurrencies, getHistory } from "./api.js";
import { createHistoryChart, formatRate, isChartAvailable } from "./history-chart.js";

// Shown first in both selects, in this order (only if the API offers them).
const POPULAR_CODES = ["USD", "EUR", "BRL", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "ARS", "MXN"];
const DEFAULTS = { from: "USD", to: "BRL", amount: "100" };
const STORAGE_KEY = "currency-converter:last-conversion";
const PLACEHOLDER = "— — —";
const HISTORY_DAYS = 30;

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
  historyPair: document.getElementById("history-pair"),
  historyChange: document.getElementById("history-change"),
  historyLow: document.getElementById("history-low"),
  historyHigh: document.getElementById("history-high"),
  historyChartWrap: document.getElementById("history-chart-wrap"),
  historyCanvas: document.getElementById("history-chart"),
  historyAlert: document.getElementById("history-alert"),
  historyAlertMessage: document.getElementById("history-alert-message"),
  historyRetry: document.getElementById("history-retry"),
};

// Only the latest conversion request matters: starting a new one aborts the
// previous, so a slow old answer can never overwrite a newer result.
let conversionController = null;
let historyController = null;
let historyChart = null;
let retryAction = null;

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
  elements.historyRetry.addEventListener("click", loadHistory);

  loadCurrencies(saved);
}

// ---- Currencies ------------------------------------------------------------

async function loadCurrencies(selection) {
  hideAlert();
  setFormEnabled(false);
  setLoadingOption("Loading currencies…");

  try {
    const { currencies } = await getCurrencies();
    fillSelect(elements.from, currencies, selection.from);
    fillSelect(elements.to, currencies, selection.to);
    setFormEnabled(true);
    onPairChange();
  } catch (error) {
    setLoadingOption("Currencies unavailable");
    showAlert(error.message, () => loadCurrencies(selection));
  }
}

function fillSelect(select, currencies, selectedCode) {
  const byCode = new Map(currencies.map((currency) => [currency.code, currency]));
  const popular = POPULAR_CODES.filter((code) => byCode.has(code)).map((code) => byCode.get(code));

  select.replaceChildren(
    buildGroup("Popular", popular),
    buildGroup("All currencies", currencies), // already sorted by code by the API
  );
  select.value = byCode.has(selectedCode) ? selectedCode : popular[0]?.code ?? currencies[0]?.code;
}

function buildGroup(label, currencies) {
  const group = document.createElement("optgroup");
  group.label = label;
  for (const { code, name } of currencies) {
    group.append(new Option(`${code} — ${name}`, code));
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
  setBusy(true);

  try {
    const result = await convert(request, { signal: controller.signal });
    renderResult(result);
    saveConversion({ from: request.from, to: request.to, amount: elements.amount.value.trim() });
  } catch (error) {
    if (controller.signal.aborted) return; // superseded by a newer request
    clearResult();
    if (error.code === "invalid_amount") {
      setAmountError(error.message);
    } else {
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
  elements.historyChartWrap.setAttribute("aria-busy", "true");

  try {
    const history = await getHistory({ from, to, days: HISTORY_DAYS }, { signal: controller.signal });
    renderHistory(history);
  } catch (error) {
    if (controller.signal.aborted) return;
    clearHistory();
    showHistoryAlert(error.message, { retry: true });
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

function renderResult(result) {
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
  renderCapsule(converted, result.to);
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
function renderCapsule(value, code = null) {
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
  // Restart the entrance animation for every new value.
  capsule.style.animation = "none";
  void capsule.offsetWidth;
  capsule.style.animation = "";
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
