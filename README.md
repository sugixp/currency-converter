# Currency Converter 💱

- **Live app:** https://sugixp.github.io/currency-converter/
- **API docs (Swagger UI):** https://currency-converter-api-93lo.onrender.com/docs

> Hosted on free plans: the API sleeps after about 15 minutes without traffic and takes ~20 s to a minute to wake up. The page never sits empty meanwhile: it shows recently saved rates at once and swaps in the live ones when the API answers.

Real-time currency conversion backed by the [Open Exchange Rates](https://openexchangerates.org/) API, available as a **web app**, a **REST API (FastAPI)** and a **command-line tool**. All of them share the same conversion core.

## Features

- Convert between any two of 150+ currencies (USD, BRL, EUR, GBP, JPY...)
- Cross-rate conversion via USD, so it works on the Open Exchange Rates free plan (fixed USD base)
- 30-day rate history chart for any currency pair
- Instant first paint: a snapshot of recent rates published with the site is shown while the API wakes up, then replaced in place by live rates (exact `BigInt` math for the provisional conversion)
- Caches that save API quota: latest rates with configurable expiration, historical rates forever (one request per day, shared by every pair), persisted in Upstash Redis so restarts cost nothing
- Quota safety limit: reads the real monthly usage from Open Exchange Rates and pauses only the history before it eats into requests reserved for conversions
- Exact money math with `Decimal` (no floating-point rounding errors)
- Clear errors for invalid input, unknown currencies, provider outages, invalid App ID and exceeded quota
- Vanilla HTML/CSS/JS frontend (no framework, no build step): responsive, keyboard accessible, friendly error messages
- Fully tested with pytest; tests never call the real API
- Deployed with CI: tests run on GitHub Actions, the API deploys to Render only when they pass, and the frontend deploys to GitHub Pages

## Technologies

- Python 3.11+ (developed and tested on 3.14.6)
- FastAPI + Uvicorn
- Requests
- python-dotenv
- pytest, GitHub Actions
- Render (API), GitHub Pages (frontend), Upstash Redis (shared cache)
- HTML, CSS and JavaScript (ES modules) + [Chart.js](https://www.chartjs.org/)

## Project structure

```
currency_converter/
├── config.py       # settings from environment variables / .env
├── errors.py       # domain exceptions
├── oxr_client.py   # HTTP client for Open Exchange Rates
├── cache.py        # thread-safe in-memory TTL cache
├── historical_store.py  # permanent per-day cache of historical rates
├── storage.py      # key-value stores: files (local) or Upstash Redis (production)
├── quota.py        # safety limit based on the provider's real usage
├── service.py      # conversion rules (validation, cross rate, Decimal)
├── api.py          # FastAPI app (REST interface)
├── cli.py          # command-line interface
└── __main__.py     # enables `python -m currency_converter`
tests/              # pytest suite with a fake provider client
frontend/
├── index.html
├── config.js       # API URL (picked by hostname) and timing settings
├── api.js          # fetch wrapper: timeout, server wake-up, friendly errors
├── snapshot.js     # saved rates shown instantly (snapshot.json, built at deploy time)
├── decimal.js      # exact decimal math with BigInt for the provisional conversion
├── app.js          # form, result board, history loading
├── history-chart.js  # Chart.js setup
└── styles.css
scripts/
└── build_snapshot.py  # builds snapshot.json from the API's cache in Upstash
tests/js/           # Node tests for decimal.js and snapshot.js
render.yaml         # Render Blueprint for the API
.github/workflows/  # tests.yml (CI) and pages.yml (frontend deploy)
```

The layers depend only downward: `frontend/` → (HTTP) → `api.py`; `api.py` and `cli.py` → `service.py` → `oxr_client.py` / `cache.py` / `historical_store.py`. The service knows nothing about HTTP or the terminal, and only `oxr_client.py` knows about the external API.

## Setup

The commands below are for **Windows PowerShell**.

1. Clone the repository

```powershell
git clone https://github.com/sugixp/currency-converter.git
cd currency-converter
```

2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> If PowerShell blocks the activation script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

3. Install dependencies

```powershell
pip install -r requirements-dev.txt   # app + test dependencies
# or: pip install -r requirements.txt  (app only)
```

4. Configure your App ID

Create a free account at [openexchangerates.org/signup/free](https://openexchangerates.org/signup/free), then:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set `OXR_APP_ID` to your App ID. `.env` is listed in `.gitignore` and must never be committed.

| Variable | Default | Description |
|---|---|---|
| `OXR_APP_ID` | *(required)* | Open Exchange Rates App ID |
| `CACHE_TTL_SECONDS` | `3600` | How long rates stay cached |
| `HISTORY_CACHE_DIR` | `.cache/historical` | Folder for the permanent history cache; set it empty to keep history in memory only |
| `REQUEST_TIMEOUT_SECONDS` | `10` | Timeout for calls to Open Exchange Rates |
| `CORS_ORIGINS` | `*` | Comma-separated origins allowed to call the API. `.env.example` allows the local frontend (`http://localhost:5500`, `http://127.0.0.1:5500`) |
| `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` | *(empty)* | Optional. Upstash Redis REST credentials; when set, caches live there and survive restarts. Set both or neither |
| `QUOTA_RESERVE` | `150` | Requests kept for conversions each month; the history pauses before spending them |

**About the quota:** the free plan allows 1,000 requests/month and updates rates hourly.

- **Latest rates:** with the default 1-hour cache, one running process makes at most ~744 requests/month (24 × 31). Each process has its own cache, so running the API and the CLI at the same time, or frequent restarts, use extra requests.
- **History:** the free plan returns one day per request, so the first 30-day chart costs 29 requests (today comes from the latest rates). Past days never change, so each day is cached forever (on disk locally, in Upstash Redis in production) and shared by every currency pair: after that, history costs about one request per day. `days` is capped at 30 so a single call can never drain the quota.
- **Safety limit:** before fetching uncached days, the API checks the account's real usage (`usage.json`, which does not count toward the quota). If fetching would leave fewer than `QUOTA_RESERVE` requests, the history answers `503 history_paused` and conversions keep working.
- **Currencies:** the currency list (`currencies.json`) does not count toward the quota.

## Running the API

```powershell
uvicorn currency_converter.api:app --reload
```

Interactive docs (Swagger UI): http://127.0.0.1:8000/docs

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service status |
| GET | `/currencies` | Available currencies |
| GET | `/convert?from=USD&to=BRL&amount=100` | Convert an amount |
| GET | `/history?from=EUR&to=BRL&days=30` | Daily rates for the last 2-30 days (default 30), oldest first, ending today |

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/convert?from=USD&to=BRL&amount=100"
```

```json
{
  "from": "USD",
  "to": "BRL",
  "amount": "100",
  "converted_amount": "507.02",
  "rate": "5.070200",
  "rate_timestamp": "2026-11-01T12:00:00Z"
}
```

Money values are returned as strings to preserve exact decimal precision. `rate_timestamp` is when Open Exchange Rates published the rate (UTC).

`GET /currencies` returns:

```json
{ "currencies": [ { "code": "BRL", "name": "Brazilian Real" }, ... ] }
```

`GET /history?from=EUR&to=BRL&days=30` returns:

```json
{
  "from": "EUR",
  "to": "BRL",
  "points": [
    { "date": "2026-10-03", "rate": "5.498812" },
    ...
    { "date": "2026-11-01", "rate": "5.511087" }
  ]
}
```

### Errors

Every error has the same shape:

```json
{ "error": "unknown_currency", "detail": "Currency 'XYZ' is not supported." }
```

| Status | `error` | When |
|---|---|---|
| 400 | `invalid_request` | Missing query parameter |
| 400 | `invalid_amount` | Amount is not a number, is zero/negative, or is too large |
| 400 | `invalid_currency` | Currency code is not 3 letters |
| 400 | `invalid_days` | `days` is not a whole number from 2 to 30 |
| 404 | `unknown_currency` | Currency is not offered by the provider |
| 503 | `history_paused` | History paused to protect the monthly quota (conversions still work) |
| 502 | `provider_auth_error` | App ID missing or rejected (server misconfiguration) |
| 502 | `provider_error` | Unexpected response from the provider |
| 503 | `provider_rate_limited` | Provider quota exceeded |
| 503 | `provider_unavailable` | Provider down or timed out |

## Running the frontend

The frontend is plain static files, with no build step. Run the API and a static file server in **two terminals**:

```powershell
# Terminal 1: the API
uvicorn currency_converter.api:app --reload
```

```powershell
# Terminal 2: the frontend
python -m http.server 5500 -d frontend
```

Open http://localhost:5500.

- The API URL lives only in `frontend/config.js`: on `localhost`/`127.0.0.1` it uses `http://localhost:8000`, anywhere else the production API on Render. Nothing to edit when switching between them.
- The page's origin must be allowed by `CORS_ORIGINS` in `.env`. If your `.env` was created before the frontend existed, add `http://localhost:5500,http://127.0.0.1:5500` to it and restart the API.
- Open the page through the server, not by double-clicking `index.html`: browsers block ES modules on `file://`.
- Chart.js is loaded from the jsDelivr CDN with a pinned version and Subresource Integrity. If it can't load, the converter and the history summary still work without the chart.

## Running the CLI

Interactive mode:

```powershell
python -m currency_converter
```

```
=== Currency Converter ===
Type 'exit' to quit.

From currency (e.g. USD, BRL, EUR): USD
To currency (e.g. USD, BRL, EUR): BRL
Amount: 100

100 USD = 507.02 BRL
Rate: 1 USD = 5.070200 BRL (as of 2026-11-01 12:00 UTC)
```

One-shot mode (exit code `1` on error, handy for scripts):

```powershell
python -m currency_converter USD BRL 100
```

## Running the tests

```powershell
python -m pytest
```

The tests replace the Open Exchange Rates client with a fake one (and the HTTP session with a fake session in the client tests), so they run offline and never use your quota.

The frontend's exact decimal math and snapshot logic have their own tests, run with Node.js 22+ (no dependencies):

```powershell
node --test tests/js/frontend.test.mjs
```

Both suites run on GitHub Actions on every push (`.github/workflows/tests.yml`).

## Deployment

| Part | Where | How it deploys |
|---|---|---|
| API | [Render](https://render.com) web service, free plan, Oregon | `render.yaml` Blueprint; auto-deploys a commit only after the **Tests** workflow passes (`autoDeployTrigger: checksPass`) |
| Frontend | [GitHub Pages](https://pages.github.com) | `.github/workflows/pages.yml` publishes the `frontend/` folder (plus a fresh `snapshot.json`) when it changes and every 2 hours |
| Shared cache | [Upstash Redis](https://upstash.com), free plan | Used by the API through its REST API |

Secrets are never committed:

- **Render dashboard:** `OXR_APP_ID`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` (declared in `render.yaml` with `sync: false`).
- **GitHub → Settings → Secrets and variables → Actions:** `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_READONLY_TOKEN` (the **read-only** token, for the snapshot build).

`CORS_ORIGINS` is in `render.yaml` and allows only `https://sugixp.github.io` plus the local frontend.

### Rates snapshot

So the page is never empty while the API sleeps, `pages.yml` runs `scripts/build_snapshot.py` before each deploy. It reads the last known rates and up to 29 days of history **from the API's cache in Upstash** (one `GET` + one `MGET` with the read-only token) and writes `snapshot.json` into the published site; it is never committed.

- **Cost:** 0 Open Exchange Rates requests and 0 Render hours (the API is neither called nor woken); about 2 Upstash commands per run. Currency names come from `currencies.json`, which needs no App ID and does not count toward the quota.
- **Freshness:** the snapshot is as recent as the last time someone used the live API. The page always shows its date ("Rates from 14:00 UTC · updating…"), and calls it possibly outdated when it is more than 3 days old.
- **The official numbers come from the API.** The page computes a provisional conversion from the snapshot with exact `BigInt` math (same cents as the API's `Decimal`), then replaces it with the API's answer.

**If the schedule stops:** GitHub disables scheduled workflows in public repositories after 60 days without repository activity. The site keeps working; the page just reports the saved rates as outdated. To turn it back on:

1. Open the repository's **Actions** tab, select **Deploy frontend to GitHub Pages**, and click **Enable workflow** (or run `gh workflow enable pages.yml`).
2. Click **Run workflow** (or run `gh workflow run pages.yml`) to publish a fresh snapshot right away.

### Free plan limitations

- **Cold starts:** Render puts free services to sleep after about 15 minutes without external traffic (Render's own health checks do not count; we measured ~17 min). Waking up took ~20 s in our tests (Render says up to about a minute): Render holds the request open and answers it once the service is up. The frontend shows the snapshot meanwhile, keeps a single `/health` request open for up to 90 seconds, and tells apart a server that is waking up from one that cannot be reached at all (blocked, offline).
- **Ephemeral disk:** the server's files are wiped on every restart, sleep and deploy. That is why the caches live in Upstash Redis instead of on disk.
- **Exchange rate quota:** 1,000 Open Exchange Rates requests per month, with rates updated hourly. The caches and the safety limit above keep usage well within it.
- **Upstash:** 500K commands per month and 250 MB of storage (this app needs a tiny fraction). Free databases are archived after 30 days without any use; restore it from the Upstash console if that happens. Adding a credit card to the Upstash account moves free databases to a paid plan.
- **Render hours:** 750 free instance hours per month per workspace, enough for one always-on service.
