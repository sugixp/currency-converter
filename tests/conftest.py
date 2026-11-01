import threading
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from currency_converter.cache import TTLCache
from currency_converter.oxr_client import RatesSnapshot, UsageInfo
from currency_converter.service import ConversionService

RATES_TIMESTAMP = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
USD_RATES = {
    "USD": Decimal("1"),
    "BRL": Decimal("5.0702"),
    "EUR": Decimal("0.92"),
    "JPY": Decimal("151.5"),
}
CURRENCIES = {
    "USD": "United States Dollar",
    "BRL": "Brazilian Real",
    "EUR": "Euro",
    "JPY": "Japanese Yen",
}


def historical_usd_rates(day):
    """Deterministic fake history: USD->BRL is 5.00 + day of month / 100."""
    return {**USD_RATES, "BRL": Decimal("5") + Decimal(day.day) / 100}


def historical_timestamp(day):
    return datetime(day.year, day.month, day.day, 23, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeOXRClient:
    """Stands in for OpenExchangeRatesClient: fixed data, counts calls, can fail on demand."""

    def __init__(self):
        self.rates_calls = 0
        self.currencies_calls = 0
        self.historical_calls = []
        self.error = None
        self.historical_error = None
        self.usage = UsageInfo(requests_remaining=900, requests_quota=1000)
        self.usage_calls = 0
        self._lock = threading.Lock()  # history days are fetched from several threads

    def fetch_historical_rates(self, day):
        with self._lock:
            self.historical_calls.append(day)
        if self.historical_error:
            raise self.historical_error
        return RatesSnapshot(rates=historical_usd_rates(day), timestamp=historical_timestamp(day))

    def fetch_usage(self):
        self.usage_calls += 1
        return self.usage

    def fetch_latest_rates(self):
        self.rates_calls += 1
        if self.error:
            raise self.error
        return RatesSnapshot(rates=dict(USD_RATES), timestamp=RATES_TIMESTAMP)

    def fetch_currencies(self):
        self.currencies_calls += 1
        if self.error:
            raise self.error
        return dict(CURRENCIES)


class FakeStore:
    """In-memory KeyValueStore that records every operation."""

    def __init__(self):
        self.data = {}
        self.ttls = {}
        self.operations = []

    def get(self, key):
        self.operations.append(("get", key))
        return self.data.get(key)

    def get_many(self, keys):
        self.operations.append(("get_many", tuple(keys)))
        return [self.data.get(key) for key in keys]

    def set(self, key, value, ttl_seconds=None):
        self.operations.append(("set", key))
        self.data[key] = value
        self.ttls[key] = ttl_seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def fake_client():
    return FakeOXRClient()


@pytest.fixture
def service(fake_client, clock):
    return ConversionService(fake_client, TTLCache(ttl_seconds=3600, clock=clock))
