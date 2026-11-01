"""Currency conversion rules, independent of any user interface."""

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from currency_converter.cache import TTLCache
from currency_converter.config import Settings
from currency_converter.errors import (
    InvalidAmountError,
    InvalidCurrencyError,
    InvalidDaysError,
    UnknownCurrencyError,
)
from currency_converter.historical_store import HistoricalRatesStore
from currency_converter.oxr_client import OpenExchangeRatesClient, RatesSnapshot
from currency_converter.quota import QuotaGuard
from currency_converter.storage import (
    DiskStore,
    KeyValueStore,
    UpstashStore,
    snapshot_from_json,
    snapshot_to_json,
)

MAX_AMOUNT = Decimal("1000000000000000")  # 1e15 keeps results well within Decimal precision
AMOUNT_PLACES = Decimal("0.01")
RATE_PLACES = Decimal("0.000001")
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")

# Each history day not yet cached costs one request of the 1,000/month free
# quota, so the window is capped. Days are always relative to today, so callers
# cannot make us fetch arbitrary dates.
MIN_HISTORY_DAYS = 2
MAX_HISTORY_DAYS = 30
HISTORY_FETCH_WORKERS = 4

LATEST_RATES_KEY = "latest"
# With a shared store, each process keeps latest rates in memory only briefly
# and re-reads the shared copy, so rates are never older than the TTL + this.
SHARED_MEMORY_TTL_SECONDS = 300
UPSTASH_KEY_PREFIX = "currency-converter:"


@dataclass(frozen=True)
class ConversionResult:
    from_currency: str
    to_currency: str
    amount: Decimal
    converted_amount: Decimal
    rate: Decimal
    rate_timestamp: datetime


@dataclass(frozen=True)
class HistoryPoint:
    day: date
    rate: Decimal


@dataclass(frozen=True)
class HistoryResult:
    from_currency: str
    to_currency: str
    points: list[HistoryPoint]


class ConversionService:
    def __init__(
        self,
        client: OpenExchangeRatesClient,
        cache: TTLCache,
        history_store: HistoricalRatesStore | None = None,
        shared_store: KeyValueStore | None = None,
        latest_ttl_seconds: int = 3600,
        quota_guard: QuotaGuard | None = None,
    ):
        self._client = client
        self._cache = cache
        self._history_store = history_store or HistoricalRatesStore()
        self._shared_store = shared_store
        self._latest_ttl_seconds = latest_ttl_seconds
        self._quota_guard = quota_guard

    def list_currencies(self) -> dict[str, str]:
        return self._cache.get_or_load("currencies", self._client.fetch_currencies)

    def convert(self, from_currency: str, to_currency: str, amount) -> ConversionResult:
        from_code = _parse_currency_code(from_currency)
        to_code = _parse_currency_code(to_currency)
        value = _parse_amount(amount)

        snapshot = self._latest_snapshot(from_code, to_code)
        rate = _cross_rate(snapshot, from_code, to_code)
        return ConversionResult(
            from_currency=from_code,
            to_currency=to_code,
            amount=value,
            converted_amount=(value * rate).quantize(AMOUNT_PLACES, rounding=ROUND_HALF_UP),
            rate=rate.quantize(RATE_PLACES, rounding=ROUND_HALF_UP),
            rate_timestamp=snapshot.timestamp,
        )

    def get_history(self, from_currency: str, to_currency: str, days=MAX_HISTORY_DAYS) -> HistoryResult:
        """Daily FROM -> TO rates for the last `days` days, oldest first, ending today."""
        from_code = _parse_currency_code(from_currency)
        to_code = _parse_currency_code(to_currency)
        day_count = _parse_days(days)

        # Today's point comes from the latest rates (already cached for the TTL);
        # past days come from the permanent historical store. Anchoring on the
        # latest rates' date guarantees every past day is a closed UTC day.
        latest = self._latest_snapshot(from_code, to_code)
        today = latest.timestamp.date()
        past_days = [today - timedelta(days=offset) for offset in range(day_count - 1, 0, -1)]

        # Only days found in no cache cost quota; check the safety limit first.
        missing = self._history_store.missing_days(past_days)
        if missing and self._quota_guard is not None:
            self._quota_guard.spend(len(missing))

        with ThreadPoolExecutor(max_workers=HISTORY_FETCH_WORKERS) as executor:
            past_snapshots = list(executor.map(self._historical_snapshot, past_days))

        points = []
        for day, snapshot in zip(past_days + [today], past_snapshots + [latest]):
            # A currency may not exist yet on older days; skip those points.
            if from_code in snapshot.rates and to_code in snapshot.rates:
                rate = _cross_rate(snapshot, from_code, to_code)
                points.append(HistoryPoint(day, rate.quantize(RATE_PLACES, rounding=ROUND_HALF_UP)))
        return HistoryResult(from_currency=from_code, to_currency=to_code, points=points)

    def _latest_snapshot(self, *codes: str) -> RatesSnapshot:
        snapshot = self._cache.get_or_load("latest_rates", self._load_latest_rates)
        for code in codes:
            if code not in snapshot.rates:
                raise UnknownCurrencyError(f"Currency '{code}' is not supported.")
        return snapshot

    def _load_latest_rates(self) -> RatesSnapshot:
        """Latest rates from the shared store if still fresh there, else from the provider."""
        if self._shared_store is not None:
            snapshot = snapshot_from_json(self._shared_store.get(LATEST_RATES_KEY))
            if snapshot is not None:
                return snapshot
        snapshot = self._client.fetch_latest_rates()
        if self._shared_store is not None:
            self._shared_store.set(
                LATEST_RATES_KEY, snapshot_to_json(snapshot), ttl_seconds=self._latest_ttl_seconds
            )
        return snapshot

    def _historical_snapshot(self, day: date) -> RatesSnapshot:
        return self._history_store.get_or_load(day, self._client.fetch_historical_rates)


def create_service(settings: Settings) -> ConversionService:
    """Wire the real Open Exchange Rates client, caches and quota guard from settings."""
    client = OpenExchangeRatesClient(settings.oxr_app_id, settings.request_timeout_seconds)
    guard = QuotaGuard(client.fetch_usage, reserve=settings.quota_reserve)

    if settings.upstash_redis_rest_url:
        # Production: caches survive restarts and are shared by every instance.
        def upstash(prefix):
            return UpstashStore(
                settings.upstash_redis_rest_url,
                settings.upstash_redis_rest_token,
                key_prefix=UPSTASH_KEY_PREFIX + prefix,
            )

        return ConversionService(
            client,
            TTLCache(min(settings.cache_ttl_seconds, SHARED_MEMORY_TTL_SECONDS)),
            HistoricalRatesStore(upstash("historical:")),
            shared_store=upstash("rates:"),
            latest_ttl_seconds=settings.cache_ttl_seconds,
            quota_guard=guard,
        )

    # Local development: history on disk (if configured), latest rates in memory.
    history_disk = DiskStore(settings.history_cache_dir) if settings.history_cache_dir else None
    return ConversionService(
        client,
        TTLCache(settings.cache_ttl_seconds),
        HistoricalRatesStore(history_disk),
        quota_guard=guard,
    )


def _cross_rate(snapshot: RatesSnapshot, from_code: str, to_code: str) -> Decimal:
    # Free plan rates are all relative to USD, so FROM -> TO is a cross rate:
    # 1 FROM = (USD->TO / USD->FROM) TO.
    return snapshot.rates[to_code] / snapshot.rates[from_code]


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


def _parse_days(days) -> int:
    message = f"Days must be a whole number between {MIN_HISTORY_DAYS} and {MAX_HISTORY_DAYS}."
    try:
        value = int(str(days).strip())
    except ValueError:
        raise InvalidDaysError(message) from None
    if not MIN_HISTORY_DAYS <= value <= MAX_HISTORY_DAYS:
        raise InvalidDaysError(message)
    return value
