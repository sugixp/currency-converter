# Currency Converter 💱

Real-time currency conversion backed by the [Open Exchange Rates](https://openexchangerates.org/) API, available as a **REST API (FastAPI)** and as a **command-line tool**. Both share the same conversion core.

## Features

- Convert between any two of 150+ currencies (USD, BRL, EUR, GBP, JPY...)
- Cross-rate conversion via USD, so it works on the Open Exchange Rates free plan (fixed USD base)
- In-memory cache with configurable expiration to save API quota
- Exact money math with `Decimal` (no floating-point rounding errors)
- Clear errors for invalid input, unknown currencies, provider outages, invalid App ID and exceeded quota
- CORS enabled, ready to be consumed by a separate frontend
- Fully tested with pytest; tests never call the real API

## Technologies

- Python 3.11+ (developed and tested on 3.14)
- FastAPI + Uvicorn
- Requests
- python-dotenv
- pytest

## Project structure

```
currency_converter/
├── config.py       # settings from environment variables / .env
├── errors.py       # domain exceptions
├── oxr_client.py   # HTTP client for Open Exchange Rates
├── cache.py        # thread-safe in-memory TTL cache
├── service.py      # conversion rules (validation, cross rate, Decimal)
├── api.py          # FastAPI app (REST interface)
├── cli.py          # command-line interface
└── __main__.py     # enables `python -m currency_converter`
tests/              # pytest suite with a fake provider client
```

The layers depend only downward: `api.py` and `cli.py` → `service.py` → `oxr_client.py` / `cache.py`. The service knows nothing about HTTP or the terminal, and only `oxr_client.py` knows about the external API.

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
| `REQUEST_TIMEOUT_SECONDS` | `10` | Timeout for calls to Open Exchange Rates |
| `CORS_ORIGINS` | `*` | Comma-separated origins allowed to call the API |

**About the quota:** the free plan allows 1,000 requests/month and updates rates hourly. With the default 1-hour cache, one running process makes at most ~744 requests/month (24 × 31). Each process has its own cache, so running the API and the CLI at the same time, or frequent restarts with `--reload`, use extra requests. The currency list (`currencies.json`) does not count toward the quota.

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
| 404 | `unknown_currency` | Currency is not offered by the provider |
| 502 | `provider_auth_error` | App ID missing or rejected (server misconfiguration) |
| 502 | `provider_error` | Unexpected response from the provider |
| 503 | `provider_rate_limited` | Provider quota exceeded |
| 503 | `provider_unavailable` | Provider down or timed out |

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
