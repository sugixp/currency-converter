// Instant rates from snapshot.json: a copy of the API's cached rates that a
// scheduled workflow publishes with the site (scripts/build_snapshot.py).
// The page shows it immediately, while the API wakes up, and keeps it on
// screen if the API never answers. Results are shaped like the API's so the
// same rendering code handles both.

import { convertExact, crossRateExact } from "./decimal.js";

const DAY_MS = 24 * 60 * 60 * 1000;

export async function loadSnapshot(url = "snapshot.json") {
  try {
    // "no-cache" revalidates with the server, so a newer snapshot is used as
    // soon as it is published (an unchanged one costs only a 304).
    const response = await fetch(url, { cache: "no-cache" });
    if (!response.ok) return null;
    const data = await response.json();
    return data?.latest?.rates && data.latest.timestamp ? data : null;
  } catch {
    return null; // no snapshot is fine: the page just waits for the API
  }
}

/** [{ code, name }] sorted by code, like GET /currencies. */
export function snapshotCurrencies(snapshot) {
  const names = snapshot.currencies ?? {};
  return Object.keys(snapshot.latest.rates)
    .sort()
    .map((code) => ({ code, name: names[code] ?? code }));
}

/** Provisional conversion shaped like GET /convert, or null if it can't be computed. */
export function snapshotConversion(snapshot, from, to, amount) {
  const rates = snapshot.latest.rates;
  if (!(from in rates) || !(to in rates)) return null;
  const converted = convertExact(amount, rates[from], rates[to]);
  if (converted === null) return null;
  return {
    from,
    to,
    amount,
    converted_amount: converted,
    rate: crossRateExact(rates[from], rates[to]),
    rate_timestamp: snapshot.latest.timestamp,
  };
}

/** History shaped like GET /history (past days + the snapshot's latest rates), or null. */
export function snapshotHistory(snapshot, from, to) {
  const days = [
    ...(snapshot.history ?? []),
    { date: snapshot.latest.timestamp.slice(0, 10), rates: snapshot.latest.rates },
  ];
  // A chart only needs display precision, so plain numbers are fine here.
  const points = days
    .filter((day) => from in day.rates && to in day.rates)
    .map((day) => ({ date: day.date, rate: String(Number(day.rates[to]) / Number(day.rates[from])) }));
  return points.length >= 2 ? { from, to, points } : null;
}

/** Whole days between the snapshot's rates and `now`. */
export function snapshotAgeDays(snapshot, now = Date.now()) {
  return Math.floor((now - Date.parse(snapshot.latest.timestamp)) / DAY_MS);
}
