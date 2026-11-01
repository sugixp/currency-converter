"""HTTP client for the Open Exchange Rates API.

This module is the only place that knows about URLs, query parameters and the
provider's error format; it translates all of that into domain exceptions.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

import requests

from currency_converter.errors import (
    ExchangeRateProviderError,
    InvalidApiKeyError,
    ProviderUnavailableError,
    RateLimitExceededError,
)

BASE_URL = "https://openexchangerates.org/api"


@dataclass(frozen=True)
class RatesSnapshot:
    """Rates relative to USD (the free plan's fixed base) and when they were published."""

    rates: dict[str, Decimal]
    timestamp: datetime


@dataclass(frozen=True)
class UsageInfo:
    """Account usage for the current month, as reported by usage.json."""

    requests_remaining: int
    requests_quota: int

    @property
    def unlimited(self) -> bool:
        # Open Exchange Rates reports -1 for plans without a request limit.
        return self.requests_quota < 0


class OpenExchangeRatesClient:
    def __init__(self, app_id: str, timeout_seconds: float = 10.0, session=None):
        self._app_id = app_id
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def fetch_latest_rates(self) -> RatesSnapshot:
        return self._fetch_snapshot("latest.json")

    def fetch_historical_rates(self, day: date) -> RatesSnapshot:
        """Rates published for a past UTC day. Each call counts as one quota request."""
        return self._fetch_snapshot(f"historical/{day.isoformat()}.json")

    def fetch_usage(self) -> UsageInfo:
        """Current month's usage. Calls to usage.json do not count toward the quota."""
        if not self._app_id:
            raise InvalidApiKeyError("OXR_APP_ID is not set. Add it to your .env file.")
        body = self._get("usage.json", {"app_id": self._app_id})
        try:
            usage = body["data"]["usage"]
            return UsageInfo(
                requests_remaining=int(usage["requests_remaining"]),
                requests_quota=int(usage["requests_quota"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExchangeRateProviderError(
                "Unexpected response format from Open Exchange Rates."
            ) from exc

    def _fetch_snapshot(self, path: str) -> RatesSnapshot:
        if not self._app_id:
            raise InvalidApiKeyError("OXR_APP_ID is not set. Add it to your .env file.")
        body = self._get(path, {"app_id": self._app_id})
        try:
            if body["base"] != "USD":
                raise ExchangeRateProviderError(f"Expected USD base rates, got {body['base']!r}.")
            rates = {code: Decimal(value) for code, value in body["rates"].items()}
            timestamp = datetime.fromtimestamp(int(body["timestamp"]), tz=timezone.utc)
        except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError) as exc:
            raise ExchangeRateProviderError(
                "Unexpected response format from Open Exchange Rates."
            ) from exc
        return RatesSnapshot(rates=rates, timestamp=timestamp)

    def fetch_currencies(self) -> dict[str, str]:
        # currencies.json needs no App ID and does not count toward the quota.
        body = self._get("currencies.json", {})
        if not all(isinstance(name, str) for name in body.values()):
            raise ExchangeRateProviderError("Unexpected response format from Open Exchange Rates.")
        return body

    def _get(self, path: str, params: dict) -> dict:
        try:
            response = self._session.get(
                f"{BASE_URL}/{path}", params=params, timeout=self._timeout_seconds
            )
        except requests.Timeout as exc:
            raise ProviderUnavailableError("Open Exchange Rates did not respond in time.") from exc
        except requests.RequestException as exc:
            raise ProviderUnavailableError("Could not reach Open Exchange Rates.") from exc

        # parse_float=Decimal keeps every rate exact: they never pass through float.
        try:
            body = response.json(parse_float=Decimal)
        except ValueError:
            body = None

        if response.status_code == 200 and isinstance(body, dict) and not body.get("error"):
            return body
        raise _error_from_response(response.status_code, body)


def _error_from_response(status_code: int, body) -> ExchangeRateProviderError:
    """Map an Open Exchange Rates error (https://docs.openexchangerates.org/reference/errors)."""
    message = body.get("message") if isinstance(body, dict) else None

    if message in ("missing_app_id", "invalid_app_id") or status_code == 401:
        return InvalidApiKeyError("Open Exchange Rates rejected the App ID. Check OXR_APP_ID.")
    if message == "access_restricted" or (status_code == 429 and message != "not_allowed"):
        return RateLimitExceededError("Open Exchange Rates request quota exceeded.")
    if status_code >= 500:
        return ProviderUnavailableError(f"Open Exchange Rates is unavailable (HTTP {status_code}).")
    return ExchangeRateProviderError(
        f"Open Exchange Rates returned an error (HTTP {status_code}, {message or 'no details'})."
    )
