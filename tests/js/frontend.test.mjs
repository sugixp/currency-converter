// Tests for the frontend's pure modules. Run with: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import { convertExact, crossRateExact, parseDecimal } from "../../frontend/decimal.js";
import {
  snapshotAgeDays,
  snapshotConversion,
  snapshotCurrencies,
  snapshotHistory,
} from "../../frontend/snapshot.js";

const SNAPSHOT = {
  generated_at: "2026-11-01T15:17:00Z",
  base: "USD",
  currencies: { BRL: "Brazilian Real", EUR: "Euro", USD: "United States Dollar" },
  latest: {
    timestamp: "2026-11-01T14:00:00Z",
    rates: { USD: "1", BRL: "5.0702", EUR: "0.92", JPY: "151.5" },
  },
  history: [
    { date: "2026-10-30", rates: { USD: "1", BRL: "5.30", EUR: "0.92" } },
    { date: "2026-10-31", rates: { USD: "1", BRL: "5.31", EUR: "0.92" } },
  ],
};

// ---- decimal.js -------------------------------------------------------------

test("parseDecimal reads plain and exponent notation", () => {
  assert.deepEqual(parseDecimal("12.50"), { digits: 1250n, scale: 2 });
  assert.deepEqual(parseDecimal("1e2"), { digits: 100n, scale: 0 });
  assert.deepEqual(parseDecimal("1.41e-5"), { digits: 141n, scale: 7 });
  for (const bad of ["", "abc", "-5", "1,5", "1.2.3", "NaN"]) assert.equal(parseDecimal(bad), null, bad);
});

test("convertExact matches the API's Decimal results (same fixtures as the pytest suite)", () => {
  assert.equal(convertExact("100", "1", "5.0702"), "507.02"); // USD -> BRL
  assert.equal(convertExact("100", "0.92", "5.0702"), "551.11"); // EUR -> BRL cross rate
  assert.equal(convertExact("507.02", "5.0702", "1"), "100.00"); // BRL -> USD
  assert.equal(convertExact("42.5", "5.0702", "5.0702"), "42.50");
});

test("convertExact rounds half up without float errors", () => {
  // As a float, 1.005 is 1.00499999..., which Number rounding turns into 1.00.
  assert.equal(convertExact("1.005", "1", "1"), "1.01");
  assert.equal(convertExact("0.004", "1", "1"), "0.00");
  assert.equal(convertExact("0.005", "1", "1"), "0.01");
});

test("convertExact handles large and tiny values exactly", () => {
  assert.equal(convertExact("1234567.89", "151.5", "151.5"), "1234567.89");
  assert.equal(convertExact("1000000000000000", "1", "5.0702"), "5070200000000000.00");
  assert.equal(convertExact("1", "0.0000141234567", "1"), "70804.20"); // checked against Python Decimal
});

test("convertExact rejects invalid input instead of guessing", () => {
  assert.equal(convertExact("abc", "1", "5"), null);
  assert.equal(convertExact("0", "1", "5"), null);
  assert.equal(convertExact("-1", "1", "5"), null);
  assert.equal(convertExact("1", "0", "5"), null);
});

test("crossRateExact rounds to 6 places like the API", () => {
  assert.equal(crossRateExact("0.92", "5.0702"), "5.511087");
  assert.equal(crossRateExact("5.0702", "5.0702"), "1.000000");
});

// ---- snapshot.js ------------------------------------------------------------

test("snapshotCurrencies lists every currency with rates, sorted, with names when known", () => {
  assert.deepEqual(snapshotCurrencies(SNAPSHOT), [
    { code: "BRL", name: "Brazilian Real" },
    { code: "EUR", name: "Euro" },
    { code: "JPY", name: "JPY" },
    { code: "USD", name: "United States Dollar" },
  ]);
});

test("snapshotConversion is shaped like the API response", () => {
  assert.deepEqual(snapshotConversion(SNAPSHOT, "EUR", "BRL", "100"), {
    from: "EUR",
    to: "BRL",
    amount: "100",
    converted_amount: "551.11",
    rate: "5.511087",
    rate_timestamp: "2026-11-01T14:00:00Z",
  });
  assert.equal(snapshotConversion(SNAPSHOT, "EUR", "ZZZ", "100"), null);
  assert.equal(snapshotConversion(SNAPSHOT, "EUR", "BRL", "abc"), null);
});

test("snapshotHistory ends with the latest rates and skips days missing a currency", () => {
  const history = snapshotHistory(SNAPSHOT, "USD", "BRL");
  assert.deepEqual(
    history.points.map((point) => point.date),
    ["2026-10-30", "2026-10-31", "2026-11-01"],
  );
  assert.equal(Number(history.points.at(-1).rate), 5.0702);
  assert.equal(snapshotHistory(SNAPSHOT, "USD", "JPY"), null); // only one day has JPY
});

test("snapshotAgeDays counts whole days since the rates", () => {
  const timestamp = Date.parse("2026-11-01T14:00:00Z");
  assert.equal(snapshotAgeDays(SNAPSHOT, timestamp + 5 * 60 * 60 * 1000), 0);
  assert.equal(snapshotAgeDays(SNAPSHOT, timestamp + 3.5 * 24 * 60 * 60 * 1000), 3);
});
