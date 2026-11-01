import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from currency_converter.oxr_client import RatesSnapshot
from currency_converter.storage import snapshot_to_json
from scripts import build_snapshot as script
from tests.conftest import FakeStore

NOW = datetime(2026, 11, 1, 15, 17, tzinfo=timezone.utc)
LATEST = RatesSnapshot(
    rates={"USD": Decimal("1"), "BRL": Decimal("5.43840"), "BTC": Decimal("0.0000141234567")},
    timestamp=datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc),
)


def history_snapshot(day):
    return RatesSnapshot(
        rates={"USD": Decimal("1"), "BRL": Decimal("5.123456789")},
        timestamp=datetime(day.year, day.month, day.day, 23, 0, tzinfo=timezone.utc),
    )


def store_with(latest_key="rates:last-known", history_days=()):
    store = FakeStore()
    store.data[latest_key] = snapshot_to_json(LATEST)
    for day in history_days:
        store.data[f"historical:{day.isoformat()}"] = snapshot_to_json(history_snapshot(day))
    return store


def test_snapshot_has_latest_rates_with_full_precision():
    snapshot = script.build_snapshot(store_with(), NOW)

    assert snapshot["generated_at"] == "2026-11-01T15:17:00Z"
    assert snapshot["base"] == "USD"
    assert snapshot["latest"]["timestamp"] == "2026-11-01T14:00:00Z"
    assert snapshot["latest"]["rates"]["BRL"] == "5.43840"
    assert snapshot["latest"]["rates"]["BTC"] == "0.0000141234567"


def test_history_covers_the_29_days_before_the_rates_date_and_is_shortened():
    days = [date(2026, 11, 1) - timedelta(days=offset) for offset in range(29, 0, -1)]

    snapshot = script.build_snapshot(store_with(history_days=days), NOW)

    assert [point["date"] for point in snapshot["history"]] == [d.isoformat() for d in days]
    assert snapshot["history"][0]["rates"]["BRL"] == "5.123457"


def test_history_is_read_with_one_batch_call_and_skips_missing_days():
    store = store_with(history_days=[date(2026, 10, 30)])

    snapshot = script.build_snapshot(store, NOW)

    assert [op[0] for op in store.operations] == ["get", "get_many"]
    assert [point["date"] for point in snapshot["history"]] == ["2026-10-30"]


def test_falls_back_to_the_expiring_latest_key():
    snapshot = script.build_snapshot(store_with(latest_key="rates:latest"), NOW)

    assert snapshot["latest"]["rates"]["BRL"] == "5.43840"


def test_no_snapshot_when_the_cache_is_empty():
    assert script.build_snapshot(FakeStore(), NOW) is None


def test_main_without_credentials_writes_nothing_and_succeeds(tmp_path, monkeypatch):
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_READONLY_TOKEN", raising=False)
    output = tmp_path / "snapshot.json"

    assert script.main(["--output", str(output)]) == 0
    assert not output.exists()


def test_main_writes_compact_json(tmp_path, monkeypatch):
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://x.upstash.io")
    monkeypatch.setenv("UPSTASH_REDIS_REST_READONLY_TOKEN", "read-only")
    monkeypatch.setattr(script, "UpstashStore", lambda *args, **kwargs: store_with())
    monkeypatch.setattr(script, "fetch_currency_names", lambda: {"BRL": "Brazilian Real"})
    output = tmp_path / "snapshot.json"

    assert script.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["latest"]["rates"]["BRL"] == "5.43840"


def test_currency_names_only_for_currencies_with_rates():
    names = {"USD": "United States Dollar", "BRL": "Brazilian Real", "ZZZ": "Not In Rates"}

    snapshot = script.build_snapshot(store_with(), NOW, names)

    assert snapshot["currencies"] == {"BRL": "Brazilian Real", "USD": "United States Dollar"}


def test_snapshot_without_names_still_works():
    assert script.build_snapshot(store_with(), NOW)["currencies"] == {}


def test_currency_names_failure_is_not_fatal(monkeypatch):
    from currency_converter.errors import ProviderUnavailableError

    class FailingClient:
        def __init__(self, app_id):
            pass

        def fetch_currencies(self):
            raise ProviderUnavailableError("down")

    monkeypatch.setattr(script, "OpenExchangeRatesClient", FailingClient)

    assert script.fetch_currency_names() == {}
