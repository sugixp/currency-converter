"""Tests for the HTTP client using a fake requests session (no network access)."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import requests

from currency_converter.errors import (
    ExchangeRateProviderError,
    InvalidApiKeyError,
    ProviderUnavailableError,
    RateLimitExceededError,
)
from currency_converter.oxr_client import BASE_URL, OpenExchangeRatesClient

LATEST_BODY = '{"timestamp": 1793534400, "base": "USD", "rates": {"USD": 1, "BRL": 5.0702}}'


def make_response(status_code, content):
    response = requests.Response()
    response.status_code = status_code
    response._content = content.encode()
    return response


class FakeSession:
    def __init__(self, response=None, exception=None):
        self.response = response
        self.exception = exception
        self.requests = []

    def get(self, url, params=None, timeout=None):
        self.requests.append({"url": url, "params": params, "timeout": timeout})
        if self.exception:
            raise self.exception
        return self.response


def make_client(response=None, exception=None, app_id="test-app-id"):
    session = FakeSession(response, exception)
    return OpenExchangeRatesClient(app_id, timeout_seconds=5, session=session), session


def test_fetch_latest_rates_parses_rates_as_exact_decimals():
    client, session = make_client(make_response(200, LATEST_BODY))

    snapshot = client.fetch_latest_rates()

    assert snapshot.rates == {"USD": Decimal("1"), "BRL": Decimal("5.0702")}
    assert all(isinstance(rate, Decimal) for rate in snapshot.rates.values())
    assert snapshot.timestamp == datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    assert session.requests == [
        {"url": f"{BASE_URL}/latest.json", "params": {"app_id": "test-app-id"}, "timeout": 5}
    ]


def test_fetch_historical_rates_requests_the_given_day():
    client, session = make_client(make_response(200, LATEST_BODY))

    snapshot = client.fetch_historical_rates(date(2026, 10, 15))

    assert snapshot.rates["BRL"] == Decimal("5.0702")
    assert session.requests[0]["url"] == f"{BASE_URL}/historical/2026-10-15.json"
    assert session.requests[0]["params"] == {"app_id": "test-app-id"}


def test_missing_app_id_fails_without_calling_the_api():
    client, session = make_client(app_id="")

    with pytest.raises(InvalidApiKeyError, match="OXR_APP_ID"):
        client.fetch_latest_rates()
    assert session.requests == []


def test_fetch_currencies_does_not_send_app_id():
    client, session = make_client(make_response(200, '{"USD": "United States Dollar"}'))

    assert client.fetch_currencies() == {"USD": "United States Dollar"}
    assert session.requests[0]["params"] == {}


@pytest.mark.parametrize(
    ("status_code", "message", "expected_error"),
    [
        (401, "invalid_app_id", InvalidApiKeyError),
        (401, "missing_app_id", InvalidApiKeyError),
        (403, "access_restricted", RateLimitExceededError),
        (429, "access_restricted", RateLimitExceededError),
        (429, "not_allowed", ExchangeRateProviderError),
        (400, "invalid_base", ExchangeRateProviderError),
        (503, "service_unavailable", ProviderUnavailableError),
    ],
)
def test_maps_provider_errors(status_code, message, expected_error):
    body = f'{{"error": true, "status": {status_code}, "message": "{message}", "description": "..."}}'
    client, _ = make_client(make_response(status_code, body))

    with pytest.raises(expected_error) as excinfo:
        client.fetch_latest_rates()
    assert type(excinfo.value) is expected_error


def test_server_error_with_non_json_body_means_unavailable():
    client, _ = make_client(make_response(502, "<html>Bad Gateway</html>"))

    with pytest.raises(ProviderUnavailableError):
        client.fetch_latest_rates()


@pytest.mark.parametrize(
    "exception", [requests.Timeout("slow"), requests.ConnectionError("no route")]
)
def test_network_failures_mean_unavailable(exception):
    client, _ = make_client(exception=exception)

    with pytest.raises(ProviderUnavailableError):
        client.fetch_latest_rates()


@pytest.mark.parametrize(
    "content",
    [
        '{"base": "USD", "rates": {"BRL": 5}}',
        '{"timestamp": 1, "base": "EUR", "rates": {"BRL": 5}}',
        '{"timestamp": 1, "base": "USD", "rates": ["BRL"]}',
        '{"timestamp": 1, "base": "USD", "rates": {"BRL": "abc"}}',
        "[]",
    ],
)
def test_unexpected_success_body_is_a_provider_error(content):
    client, _ = make_client(make_response(200, content))

    with pytest.raises(ExchangeRateProviderError):
        client.fetch_latest_rates()
