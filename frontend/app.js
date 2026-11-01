import { convert, getCurrencies } from "./api.js";

// Shown first in both selects, in this order (only if the API offers them).
const POPULAR_CODES = ["USD", "EUR", "BRL", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "ARS", "MXN"];
const DEFAULTS = { from: "USD", to: "BRL", amount: "100" };
const STORAGE_KEY = "currency-converter:last-conversion";
const PLACEHOLDER_TILES = "------";

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
  resultTiles: document.getElementById("result-tiles"),
  resultCode: document.getElementById("result-code"),
  resultText: document.getElementById("result-text"),
  resultRate: document.getElementById("result-rate"),
  resultTime: document.getElementById("result-time"),
};

// Only the latest conversion request matters: starting a new one aborts the
// previous, so a slow old answer can never overwrite a newer result.
let conversionController = null;
let retryAction = null;

init();

function init() {
  const saved = loadSavedConversion();
  elements.amount.value = saved.amount;
  renderTiles(PLACEHOLDER_TILES, { placeholder: true });

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    runConversion();
  });
  elements.from.addEventListener("change", runConversion);
  elements.to.addEventListener("change", runConversion);
  elements.swap.addEventListener("click", swapCurrencies);
  elements.amount.addEventListener("input", () => setAmountError(null));
  elements.alertRetry.addEventListener("click", () => retryAction?.());

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
    runConversion();
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
  runConversion();
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
  renderTiles(converted);
  elements.resultCode.textContent = result.to;
  elements.resultRate.textContent = `1 ${result.from} = ${rate} ${result.to}`;
  elements.resultTime.textContent = publishedAt;
  // The tiles are hidden from screen readers; this sentence is what they announce.
  elements.resultText.textContent = `${amount} ${result.from} equals ${converted} ${result.to}.`;
}

function clearResult() {
  elements.resultFrom.innerHTML = "&nbsp;";
  renderTiles(PLACEHOLDER_TILES, { placeholder: true });
  elements.resultCode.textContent = "";
  elements.resultRate.textContent = "—";
  elements.resultTime.textContent = "—";
  elements.resultText.textContent = "";
}

function renderTiles(text, { placeholder = false } = {}) {
  const tiles = [...text].map((character, index) => {
    const tile = document.createElement("span");
    tile.className = "tile";
    if (placeholder) tile.classList.add("tile--placeholder");
    if (/[^\d\p{L}]/u.test(character)) tile.classList.add("tile--narrow");
    tile.style.setProperty("--i", index);
    tile.textContent = character;
    return tile;
  });
  elements.resultTiles.style.setProperty("--chars", Math.max(tiles.length, 6));
  elements.resultTiles.replaceChildren(...tiles);
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
