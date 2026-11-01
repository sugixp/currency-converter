// Exact decimal arithmetic for the provisional conversion shown from the
// snapshot while the API wakes up.
//
// Why not plain numbers: JavaScript numbers are binary floats, so 1.005 is
// really 1.00499999999999989..., and rounding it to cents gives 1.00 instead
// of 1.01. Here every decimal string becomes a BigInt scaled by a power of
// ten, the whole conversion is one exact fraction, and rounding happens once
// at the end, half up, like the API's Decimal ROUND_HALF_UP. Same inputs,
// same cents as the API.
//
// It is still only provisional: the snapshot can be hours old. The official
// value always comes from the API, the single source of truth with the latest
// rates, and replaces this one as soon as it arrives.

const DECIMAL = /^(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i;

/** "12.50" -> { digits: 1250n, scale: 2 }, meaning 1250 / 10^2; null if not a plain positive decimal. */
export function parseDecimal(text) {
  const match = DECIMAL.exec(String(text).trim());
  if (!match) return null;
  const [, whole, fraction = "", exponent = "0"] = match;
  let digits = BigInt(whole + fraction);
  let scale = fraction.length - Number(exponent);
  if (scale < 0) {
    digits *= 10n ** BigInt(-scale);
    scale = 0;
  }
  return { digits, scale };
}

/** numerator / denominator (positive BigInts) rounded half up to `places` decimals, as a string. */
function divideRounded(numerator, denominator, places) {
  const scaled = numerator * 10n ** BigInt(places);
  // floor(scaled / denominator + 1/2), in integers only.
  const rounded = (2n * scaled + denominator) / (2n * denominator);
  const text = rounded.toString().padStart(places + 1, "0");
  return places ? `${text.slice(0, -places)}.${text.slice(-places)}` : text;
}

/**
 * amount × (USD→to) / (USD→from), rounded to cents, e.g. ("100", "0.92", "5.0702") -> "551.11".
 * Returns null unless every input is a positive decimal string.
 */
export function convertExact(amount, usdToFrom, usdToTo) {
  const a = parseDecimal(amount);
  const from = parseDecimal(usdToFrom);
  const to = parseDecimal(usdToTo);
  if (!a || !from || !to || a.digits === 0n || from.digits === 0n) return null;
  // (a / 10^sa) × (to / 10^st) / (from / 10^sf) = a·to·10^sf / (from·10^(sa+st))
  const numerator = a.digits * to.digits * 10n ** BigInt(from.scale);
  const denominator = from.digits * 10n ** BigInt(a.scale + to.scale);
  return divideRounded(numerator, denominator, 2);
}

/** 1 FROM in TO, from rates relative to USD, rounded to `places` decimals (the API uses 6). */
export function crossRateExact(usdToFrom, usdToTo, places = 6) {
  const from = parseDecimal(usdToFrom);
  const to = parseDecimal(usdToTo);
  if (!from || !to || from.digits === 0n) return null;
  const numerator = to.digits * 10n ** BigInt(from.scale);
  const denominator = from.digits * 10n ** BigInt(to.scale);
  return divideRounded(numerator, denominator, places);
}
