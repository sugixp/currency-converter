import pytest
from fastapi.testclient import TestClient

from currency_converter.api import create_app
from currency_converter.config import Settings
from currency_converter.errors import (
    ExchangeRateProviderError,
    InvalidApiKeyError,
    ProviderUnavailableError,
    RateLimitExceededError,
)

ALLOWED_ORIGIN = "http://localhost:5173"


@pytest.fixture
def api(service):
    settings = Settings(oxr_app_id="test", cors_origins=(ALLOWED_ORIGIN,))
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
