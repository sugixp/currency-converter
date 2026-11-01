from datetime import datetime, timezone
from decimal import Decimal

import pytest

from currency_converter.cache import TTLCache
from currency_converter.oxr_client import RatesSnapshot
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
        self.error = None

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


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def fake_client():
    return FakeOXRClient()


@pytest.fixture
def service(fake_client, clock):
    return ConversionService(fake_client, TTLCache(ttl_seconds=3600, clock=clock))
