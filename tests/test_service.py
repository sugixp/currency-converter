from decimal import Decimal

import pytest

from currency_converter.errors import (
    InvalidAmountError,
    InvalidCurrencyError,
    ProviderUnavailableError,
    UnknownCurrencyError,
)
from tests.conftest import CURRENCIES, RATES_TIMESTAMP


def test_converts_from_usd(service):
    result = service.convert("USD", "BRL", "100")

    assert result.from_currency == "USD"
    assert result.to_currency == "BRL"
    assert result.amount == Decimal("100")
    assert result.converted_amount == Decimal("507.02")
    assert result.rate == Decimal("5.070200")
    assert result.rate_timestamp == RATES_TIMESTAMP


def test_converts_between_non_usd_currencies_via_cross_rate(service):
    # EUR -> BRL = (USD->BRL) / (USD->EUR) = 5.0702 / 0.92 = 5.51108695...
    result = service.convert("EUR", "BRL", "100")

    assert result.rate == Decimal("5.511087")
    assert result.converted_amount == Decimal("551.11")


def test_converts_to_usd(service):
    result = service.convert("BRL", "USD", "507.02")

    assert result.converted_amount == Decimal("100.00")


def test_same_currency_has_rate_one(service):
    result = service.convert("BRL", "BRL", "42.5")

    assert result.rate == Decimal("1")
    assert result.converted_amount == Decimal("42.50")


def test_rounds_half_up_without_float_errors(service):
    # As a float, 1.005 is 1.00499999..., which would round down to 1.00.
    assert service.convert("USD", "USD", "1.005").converted_amount == Decimal("1.01")


def test_normalizes_currency_codes(service):
    result = service.convert(" usd ", "brl", 1)

    assert (result.from_currency, result.to_currency) == ("USD", "BRL")


@pytest.mark.parametrize("code", ["ZZZ", "XYZ"])
def test_rejects_unknown_currency(service, code):
    with pytest.raises(UnknownCurrencyError, match=code):
        service.convert("USD", code, "1")


@pytest.mark.parametrize("code", ["", "US", "USDD", "12A", "U$D"])
def test_rejects_malformed_currency_code(service, fake_client, code):
    with pytest.raises(InvalidCurrencyError):
        service.convert(code, "BRL", "1")
    assert fake_client.rates_calls == 0


@pytest.mark.parametrize("amount", ["abc", "", "-5", "0", "-0.01", "NaN", "Infinity", "1e16"])
def test_rejects_invalid_amount_without_calling_the_api(service, fake_client, amount):
    with pytest.raises(InvalidAmountError):
        service.convert("USD", "BRL", amount)
    assert fake_client.rates_calls == 0


def test_reuses_cached_rates_until_ttl_expires(service, fake_client, clock):
    service.convert("USD", "BRL", "1")
    service.convert("EUR", "JPY", "1")
    assert fake_client.rates_calls == 1

    clock.now = 3600
    service.convert("USD", "BRL", "1")
    assert fake_client.rates_calls == 2


def test_lists_currencies_with_cache(service, fake_client):
    assert service.list_currencies() == CURRENCIES
    service.list_currencies()
    assert fake_client.currencies_calls == 1


def test_provider_errors_propagate(service, fake_client):
    fake_client.error = ProviderUnavailableError("down")

    with pytest.raises(ProviderUnavailableError):
        service.convert("USD", "BRL", "1")
