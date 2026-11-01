import json
import threading
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest

from currency_converter import config
from currency_converter.errors import (
    InvalidDaysError,
    ProviderUnavailableError,
    UnknownCurrencyError,
)
from currency_converter.historical_store import HistoricalRatesStore
from currency_converter.oxr_client import RatesSnapshot
from tests.conftest import RATES_TIMESTAMP, USD_RATES, historical_timestamp, historical_usd_rates

TODAY = RATES_TIMESTAMP.date()  # 2026-11-01, the date of the fake latest rates


def past_days(count):
    """The `count` days before TODAY, oldest first."""
    return [TODAY - timedelta(days=offset) for offset in range(count, 0, -1)]


# --- Service -------------------------------------------------------------------


def test_returns_one_point_per_day_ending_today(service):
    history = service.get_history("USD", "BRL", 30)

    assert (history.from_currency, history.to_currency) == ("USD", "BRL")
    assert [point.day for point in history.points] == past_days(29) + [TODAY]
    assert history.points[0].rate == Decimal("5.030000")  # 2026-10-03: 5 + 3/100
    assert history.points[-2].rate == Decimal("5.310000")  # 2026-10-31
    assert history.points[-1].rate == Decimal("5.070200")  # today, from latest rates


def test_history_uses_cross_rate(service):
    history = service.get_history("eur", "brl", 2)

    # 2026-10-31: USD->BRL 5.31 / USD->EUR 0.92 = 5.7717391...
    assert history.points[0].rate == Decimal("5.771739")


def test_fetches_only_past_days_and_never_today(service, fake_client):
    service.get_history("USD", "BRL", 30)

    assert sorted(fake_client.historical_calls) == past_days(29)
    assert fake_client.rates_calls == 1


def test_each_day_is_fetched_once_for_any_currency_pair(service, fake_client):
    service.get_history("USD", "BRL", 30)
    service.get_history("EUR", "JPY", 30)
    service.get_history("BRL", "EUR", 7)

    assert len(fake_client.historical_calls) == 29


@pytest.mark.parametrize("days", ["1", "31", "0", "-5", "abc", "", "2.5"])
def test_rejects_invalid_days_without_calling_the_api(service, fake_client, days):
    with pytest.raises(InvalidDaysError):
        service.get_history("USD", "BRL", days)
    assert fake_client.rates_calls == 0
    assert fake_client.historical_calls == []


def test_minimum_window_is_yesterday_and_today(service):
    history = service.get_history("USD", "BRL", "2")

    assert [point.day for point in history.points] == [TODAY - timedelta(days=1), TODAY]


def test_unknown_currency_fails_before_fetching_history(service, fake_client):
    with pytest.raises(UnknownCurrencyError):
        service.get_history("USD", "ZZZ", 30)
    assert fake_client.historical_calls == []


def test_skips_days_when_a_currency_did_not_exist_yet(service, fake_client, monkeypatch):
    first_day_with_eur = date(2026, 10, 20)

    def rates_without_old_eur(day):
        rates = historical_usd_rates(day)
        if day < first_day_with_eur:
            del rates["EUR"]
        return RatesSnapshot(rates=rates, timestamp=historical_timestamp(day))

    monkeypatch.setattr(fake_client, "fetch_historical_rates", rates_without_old_eur)

    history = service.get_history("EUR", "BRL", 30)

    assert history.points[0].day == first_day_with_eur
    assert history.points[-1].day == TODAY


def test_failed_day_propagates_and_successful_days_stay_cached(service, fake_client, monkeypatch):
    failing_day = TODAY - timedelta(days=10)
    real_fetch = fake_client.fetch_historical_rates

    def fetch_failing_one_day(day):
        if day == failing_day:
            raise ProviderUnavailableError("timeout")
        return real_fetch(day)

    monkeypatch.setattr(fake_client, "fetch_historical_rates", fetch_failing_one_day)
    with pytest.raises(ProviderUnavailableError):
        service.get_history("USD", "BRL", 30)

    monkeypatch.setattr(fake_client, "fetch_historical_rates", real_fetch)
    fake_client.historical_calls.clear()
    service.get_history("USD", "BRL", 30)

    assert fake_client.historical_calls == [failing_day]


# --- Store ---------------------------------------------------------------------


def make_snapshot(day):
    return RatesSnapshot(rates=historical_usd_rates(day), timestamp=historical_timestamp(day))


class CountingLoader:
    def __init__(self):
        self.calls = []

    def __call__(self, day):
        self.calls.append(day)
        return make_snapshot(day)


def test_store_persists_to_disk_and_survives_restart(tmp_path):
    day = date(2026, 10, 15)
    loader = CountingLoader()
    HistoricalRatesStore(tmp_path).get_or_load(day, loader)

    restarted = HistoricalRatesStore(tmp_path)
    snapshot = restarted.get_or_load(day, loader)

    assert loader.calls == [day]
    assert snapshot == make_snapshot(day)


def test_store_keeps_rates_as_exact_decimals_on_disk(tmp_path):
    day = date(2026, 10, 15)
    HistoricalRatesStore(tmp_path).get_or_load(day, CountingLoader())

    data = json.loads((tmp_path / "2026-10-15.json").read_text(encoding="utf-8"))
    assert data["rates"]["BRL"] == "5.15"
    assert data["rates"]["EUR"] == str(USD_RATES["EUR"])


def test_store_without_directory_is_memory_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    loader = CountingLoader()
    store = HistoricalRatesStore(None)

    store.get_or_load(date(2026, 10, 15), loader)
    store.get_or_load(date(2026, 10, 15), loader)

    assert len(loader.calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_store_refetches_when_cache_file_is_corrupt(tmp_path):
    (tmp_path / "2026-10-15.json").write_text("{not json", encoding="utf-8")
    loader = CountingLoader()

    snapshot = HistoricalRatesStore(tmp_path).get_or_load(date(2026, 10, 15), loader)

    assert loader.calls == [date(2026, 10, 15)]
    assert snapshot == make_snapshot(date(2026, 10, 15))


def test_store_still_works_when_disk_is_not_writable(tmp_path):
    not_a_directory = tmp_path / "file.txt"
    not_a_directory.write_text("x", encoding="utf-8")
    loader = CountingLoader()
    store = HistoricalRatesStore(not_a_directory)

    store.get_or_load(date(2026, 10, 15), loader)
    store.get_or_load(date(2026, 10, 15), loader)

    assert len(loader.calls) == 1


def test_concurrent_requests_for_the_same_day_fetch_once():
    store = HistoricalRatesStore(None)
    calls = []

    def slow_loader(day):
        calls.append(day)
        time.sleep(0.05)
        return make_snapshot(day)

    threads = [
        threading.Thread(target=store.get_or_load, args=(date(2026, 10, 15), slow_loader))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1


# --- Config --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [(None, ".cache/historical"), ("", None), ("  ", None), ("data/history", "data/history")],
)
def test_history_cache_dir_setting(monkeypatch, env_value, expected):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)  # ignore the developer's .env
    if env_value is None:
        monkeypatch.delenv("HISTORY_CACHE_DIR", raising=False)
    else:
        monkeypatch.setenv("HISTORY_CACHE_DIR", env_value)

    assert config.load_settings().history_cache_dir == expected
