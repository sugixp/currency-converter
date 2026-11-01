"""Tests for the key-value stores; Upstash is exercised with a fake HTTP session."""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import requests

from currency_converter.oxr_client import RatesSnapshot
from currency_converter.storage import DiskStore, UpstashStore, snapshot_from_json, snapshot_to_json

SNAPSHOT = RatesSnapshot(
    rates={"USD": Decimal("1"), "BRL": Decimal("5.070200")},
    timestamp=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc),
)


# --- Snapshot serialization ------------------------------------------------------


def test_snapshot_round_trips_with_exact_decimals():
    restored = snapshot_from_json(snapshot_to_json(SNAPSHOT))

    assert restored == SNAPSHOT
    assert str(restored.rates["BRL"]) == "5.070200"


@pytest.mark.parametrize("raw", [None, "", "{not json", "[]", '{"rates": {}}', '{"timestamp": 1, "rates": {"BRL": "x"}}'])
def test_unreadable_snapshot_is_a_cache_miss(raw):
    assert snapshot_from_json(raw) is None


# --- DiskStore ----------------------------------------------------------------------


def test_disk_store_round_trip(tmp_path):
    store = DiskStore(tmp_path / "cache")
    store.set("2026-10-15", "value")

    assert DiskStore(tmp_path / "cache").get("2026-10-15") == "value"
    assert (tmp_path / "cache" / "2026-10-15.json").read_text(encoding="utf-8") == "value"


def test_disk_store_get_many_returns_none_for_missing_keys(tmp_path):
    store = DiskStore(tmp_path)
    store.set("a", "1")

    assert store.get_many(["a", "b"]) == ["1", None]


# --- UpstashStore -------------------------------------------------------------------


def make_response(status_code, body):
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


class FakeSession:
    def __init__(self, *responses, exception=None):
        self.responses = list(responses)
        self.exception = exception
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.exception:
            raise self.exception
        return self.responses.pop(0)


def make_store(*responses, exception=None):
    session = FakeSession(*responses, exception=exception)
    store = UpstashStore(
        "https://example.upstash.io/", "secret-token", key_prefix="app:", timeout_seconds=3, session=session
    )
    return store, session


def test_upstash_get_sends_prefixed_command_with_bearer_token():
    store, session = make_store(make_response(200, {"result": "value"}))

    assert store.get("latest") == "value"
    assert session.calls == [
        {
            "url": "https://example.upstash.io",
            "json": ["GET", "app:latest"],
            "headers": {"Authorization": "Bearer secret-token"},
            "timeout": 3,
        }
    ]


def test_upstash_set_with_ttl_uses_ex():
    store, session = make_store(make_response(200, {"result": "OK"}))

    store.set("latest", "value", ttl_seconds=3600)

    assert session.calls[0]["json"] == ["SET", "app:latest", "value", "EX", 3600]


def test_upstash_set_without_ttl_never_expires():
    store, session = make_store(make_response(200, {"result": "OK"}))

    store.set("2026-10-15", "value")

    assert session.calls[0]["json"] == ["SET", "app:2026-10-15", "value"]


def test_upstash_get_many_uses_a_single_mget():
    store, session = make_store(make_response(200, {"result": ["a", None]}))

    assert store.get_many(["d1", "d2"]) == ["a", None]
    assert session.calls[0]["json"] == ["MGET", "app:d1", "app:d2"]


def test_upstash_get_many_with_no_keys_skips_the_request():
    store, session = make_store()

    assert store.get_many([]) == []
    assert session.calls == []


@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (401, {"error": "WRONGPASS invalid password"}),
        (400, {"error": "ERR max daily request limit exceeded"}),
        (200, {"error": "ERR something"}),
    ],
)
def test_upstash_errors_are_cache_misses_not_failures(status_code, body):
    store, _ = make_store(*(make_response(status_code, body) for _ in range(3)))

    assert store.get("latest") is None
    assert store.get_many(["a", "b"]) == [None, None]
    store.set("latest", "value")  # must not raise


@pytest.mark.parametrize("exception", [requests.Timeout("slow"), requests.ConnectionError("down")])
def test_upstash_network_failures_are_cache_misses(exception):
    store, _ = make_store(exception=exception)

    assert store.get("latest") is None
    assert store.get_many(["a"]) == [None]
    store.set("latest", "value")  # must not raise


def test_upstash_never_logs_the_token(caplog):
    store, _ = make_store(make_response(401, {"error": "WRONGPASS invalid password"}))

    store.get("latest")

    assert "secret-token" not in caplog.text
    assert "Upstash GET" in caplog.text
