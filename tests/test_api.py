import pytest
from fastapi.testclient import TestClient

from currency_converter.api import create_app
from currency_converter.cache import TTLCache
from currency_converter.config import Settings
from currency_converter.errors import (
    ExchangeRateProviderError,
    InvalidApiKeyError,
    ProviderUnavailableError,
    RateLimitExceededError,
)
from currency_converter.oxr_client import UsageInfo
from currency_converter.quota import QuotaGuard
from currency_converter.service import ConversionService

ALLOWED_ORIGIN = "http://localhost:5173"


@pytest.fixture
def api(fake_client, clock):
    settings = Settings(oxr_app_id="test", cors_origins=(ALLOWED_ORIGIN,))
    service = ConversionService(
        fake_client,
        TTLCache(ttl_seconds=3600, clock=clock),
        quota_guard=QuotaGuard(fake_client.fetch_usage, reserve=150, clock=clock),
    )
    return TestClient(create_app(service=service, settings=settings))


def test_health(api):
    response = api.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_does_not_depend_on_the_provider(api, fake_client):
    fake_client.error = ProviderUnavailableError("down")

    assert api.get("/health").status_code == 200


def test_lists_currencies_sorted_by_code(api):
    response = api.get("/currencies")

    assert response.status_code == 200
    assert response.json() == {
        "currencies": [
            {"code": "BRL", "name": "Brazilian Real"},
            {"code": "EUR", "name": "Euro"},
            {"code": "JPY", "name": "Japanese Yen"},
            {"code": "USD", "name": "United States Dollar"},
        ]
    }


def test_converts(api):
    response = api.get("/convert", params={"from": "usd", "to": "BRL", "amount": "100"})

    assert response.status_code == 200
    assert response.json() == {
        "from": "USD",
        "to": "BRL",
        "amount": "100",
        "converted_amount": "507.02",
        "rate": "5.070200",
        "rate_timestamp": "2026-11-01T12:00:00Z",
    }


def test_converts_with_cross_rate(api):
    response = api.get("/convert", params={"from": "EUR", "to": "BRL", "amount": "100"})

    assert response.json()["converted_amount"] == "551.11"


def test_scientific_notation_amount_is_returned_in_plain_format(api):
    response = api.get("/convert", params={"from": "USD", "to": "USD", "amount": "1e2"})

    assert response.json()["amount"] == "100"


@pytest.mark.parametrize(
    ("params", "error"),
    [
        ({"from": "USD", "to": "BRL", "amount": "abc"}, "invalid_amount"),
        ({"from": "USD", "to": "BRL", "amount": "-10"}, "invalid_amount"),
        ({"from": "USD", "to": "BRL", "amount": "0"}, "invalid_amount"),
        ({"from": "US", "to": "BRL", "amount": "10"}, "invalid_currency"),
        ({"from": "USD", "to": "BRL"}, "invalid_request"),
        ({}, "invalid_request"),
    ],
)
def test_bad_requests_return_400(api, params, error):
    response = api.get("/convert", params=params)

    assert response.status_code == 400
    assert response.json()["error"] == error
    assert response.json()["detail"]


def test_missing_params_are_named_in_the_message(api):
    response = api.get("/convert", params={"from": "USD"})

    assert response.json()["detail"] == "Missing required query parameter(s): to, amount."


def test_unknown_currency_returns_404(api):
    response = api.get("/convert", params={"from": "USD", "to": "ZZZ", "amount": "1"})

    assert response.status_code == 404
    assert response.json() == {
        "error": "unknown_currency",
        "detail": "Currency 'ZZZ' is not supported.",
    }


@pytest.mark.parametrize(
    ("provider_error", "status_code", "error"),
    [
        (InvalidApiKeyError("bad key"), 502, "provider_auth_error"),
        (RateLimitExceededError("quota"), 503, "provider_rate_limited"),
        (ProviderUnavailableError("timeout"), 503, "provider_unavailable"),
        (ExchangeRateProviderError("weird"), 502, "provider_error"),
    ],
)
@pytest.mark.parametrize(
    "path", ["/currencies", "/convert?from=USD&to=BRL&amount=1"]
)
def test_provider_failures_map_to_gateway_errors(
    api, fake_client, provider_error, status_code, error, path
):
    fake_client.error = provider_error

    response = api.get(path)

    assert response.status_code == status_code
    assert response.json()["error"] == error


def test_cors_allows_configured_origin(api):
    response = api.get("/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_cors_preflight(api):
    response = api.options(
        "/convert",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_cors_ignores_other_origins(api):
    response = api.get("/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_history_defaults_to_30_days(api):
    response = api.get("/history", params={"from": "usd", "to": "brl"})

    assert response.status_code == 200
    body = response.json()
    assert (body["from"], body["to"]) == ("USD", "BRL")
    assert len(body["points"]) == 30
    assert body["points"][0] == {"date": "2026-10-03", "rate": "5.030000"}
    assert body["points"][-1] == {"date": "2026-11-01", "rate": "5.070200"}


def test_history_with_custom_window(api):
    response = api.get("/history", params={"from": "EUR", "to": "BRL", "days": "7"})

    assert [point["date"] for point in response.json()["points"]] == [
        "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29",
        "2026-10-30", "2026-10-31", "2026-11-01",
    ]


def test_history_reuses_cached_days_across_requests(api, fake_client):
    api.get("/history", params={"from": "USD", "to": "BRL"})
    api.get("/history", params={"from": "EUR", "to": "JPY"})

    assert len(fake_client.historical_calls) == 29


@pytest.mark.parametrize(
    ("params", "status_code", "error"),
    [
        ({"from": "USD", "to": "BRL", "days": "365"}, 400, "invalid_days"),
        ({"from": "USD", "to": "BRL", "days": "1"}, 400, "invalid_days"),
        ({"from": "USD", "to": "BRL", "days": "abc"}, 400, "invalid_days"),
        ({"from": "USD"}, 400, "invalid_request"),
        ({"from": "USD", "to": "B1"}, 400, "invalid_currency"),
        ({"from": "USD", "to": "ZZZ"}, 404, "unknown_currency"),
    ],
)
def test_history_bad_requests(api, fake_client, params, status_code, error):
    response = api.get("/history", params=params)

    assert response.status_code == status_code
    assert response.json()["error"] == error
    assert fake_client.historical_calls == []


@pytest.mark.parametrize(
    ("provider_error", "status_code", "error"),
    [
        (InvalidApiKeyError("bad key"), 502, "provider_auth_error"),
        (RateLimitExceededError("quota"), 503, "provider_rate_limited"),
        (ProviderUnavailableError("timeout"), 503, "provider_unavailable"),
        (ExchangeRateProviderError("not_available"), 502, "provider_error"),
    ],
)
def test_history_provider_failures(api, fake_client, provider_error, status_code, error):
    fake_client.historical_error = provider_error

    response = api.get("/history", params={"from": "USD", "to": "BRL"})

    assert response.status_code == status_code
    assert response.json()["error"] == error


def test_paused_history_returns_503_with_a_clear_message(api, fake_client):
    fake_client.usage = UsageInfo(requests_remaining=100, requests_quota=1000)

    response = api.get("/history", params={"from": "USD", "to": "BRL"})

    assert response.status_code == 503
    assert response.json()["error"] == "history_paused"
    assert "Conversions still work" in response.json()["detail"]
    assert api.get("/convert", params={"from": "USD", "to": "BRL", "amount": "1"}).status_code == 200
