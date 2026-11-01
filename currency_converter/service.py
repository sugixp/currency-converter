"""Currency conversion rules, independent of any user interface."""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from currency_converter.cache import TTLCache
from currency_converter.errors import (
    InvalidAmountError,
    InvalidCurrencyError,
    UnknownCurrencyError,
)
from currency_converter.oxr_client import OpenExchangeRatesClient

MAX_AMOUNT = Decimal("1000000000000000")  # 1e15 keeps results well within Decimal precision
AMOUNT_PLACES = Decimal("0.01")
RATE_PLACES = Decimal("0.000001")
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class ConversionResult:
    from_currency: str
    to_currency: str
    amount: Decimal
    converted_amount: Decimal
    rate: Decimal
    rate_timestamp: datetime


class ConversionService:
    def __init__(self, client: OpenExchangeRatesClient, cache: TTLCache):
        self._client = client
        self._cache = cache

    def list_currencies(self) -> dict[str, str]:
        return self._cache.get_or_load("currencies", self._client.fetch_currencies)

    def convert(self, from_currency: str, to_currency: str, amount) -> ConversionResult:
        from_code = _parse_currency_code(from_currency)
        to_code = _parse_currency_code(to_currency)
        value = _parse_amount(amount)

        snapshot = self._cache.get_or_load("latest_rates", self._client.fetch_latest_rates)
        for code in (from_code, to_code):
            if code not in snapshot.rates:
                raise UnknownCurrencyError(f"Currency '{code}' is not supported.")

        # Free plan rates are all relative to USD, so FROM -> TO is a cross rate:
        # 1 FROM = (USD->TO / USD->FROM) TO.
        rate = snapshot.rates[to_code] / snapshot.rates[from_code]
        return ConversionResult(
            from_currency=from_code,
            to_currency=to_code,
            amount=value,
            converted_amount=(value * rate).quantize(AMOUNT_PLACES, rounding=ROUND_HALF_UP),
            rate=rate.quantize(RATE_PLACES, rounding=ROUND_HALF_UP),
            rate_timestamp=snapshot.timestamp,
        )


def _parse_currency_code(code) -> str:
    normalized = str(code).strip().upper()
    if not _CURRENCY_CODE.match(normalized):
        raise InvalidCurrencyError(
            f"'{code}' is not a valid currency code (expected 3 letters, e.g. USD)."
        )
    return normalized


def _parse_amount(amount) -> Decimal:
    try:
        value = Decimal(str(amount).strip())
    except InvalidOperation:
        raise InvalidAmountError(f"'{amount}' is not a valid amount.") from None
    if not value.is_finite():
        raise InvalidAmountError(f"'{amount}' is not a valid amount.")
    if value <= 0:
        raise InvalidAmountError("Amount must be greater than zero.")
    if value > MAX_AMOUNT:
        raise InvalidAmountError(f"Amount must not exceed {MAX_AMOUNT:,}.")
    return value
