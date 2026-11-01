import pytest

from currency_converter.cache import TTLCache


def test_returns_cached_value_until_ttl_expires(clock):
    cache = TTLCache(ttl_seconds=60, clock=clock)
    calls = []

    def loader():
        calls.append(clock.now)
        return len(calls)

    assert cache.get_or_load("key", loader) == 1
    clock.now = 59.9
    assert cache.get_or_load("key", loader) == 1
    clock.now = 60
    assert cache.get_or_load("key", loader) == 2
    assert calls == [0.0, 60]


def test_keys_are_cached_independently(clock):
    cache = TTLCache(ttl_seconds=60, clock=clock)

    assert cache.get_or_load("a", lambda: "A") == "A"
    assert cache.get_or_load("b", lambda: "B") == "B"
    assert cache.get_or_load("a", lambda: "other") == "A"


def test_failed_load_is_not_cached(clock):
    cache = TTLCache(ttl_seconds=60, clock=clock)

    def failing_loader():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        cache.get_or_load("key", failing_loader)
    assert cache.get_or_load("key", lambda: "ok") == "ok"


def test_clear_forces_reload(clock):
    cache = TTLCache(ttl_seconds=60, clock=clock)
    cache.get_or_load("key", lambda: "old")
    cache.clear()
    assert cache.get_or_load("key", lambda: "new") == "new"
