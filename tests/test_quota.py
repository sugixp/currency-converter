import pytest

from currency_converter.errors import HistoryPausedError
from currency_converter.oxr_client import UsageInfo
from currency_converter.quota import QuotaGuard


class UsageSource:
    def __init__(self, remaining, quota=1000):
        self.usage = UsageInfo(requests_remaining=remaining, requests_quota=quota)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.usage


def make_guard(clock, remaining, reserve=150, quota=1000):
    source = UsageSource(remaining, quota)
    return QuotaGuard(source, reserve=reserve, refresh_seconds=600, clock=clock), source


def test_allows_spending_above_the_reserve(clock):
    guard, source = make_guard(clock, remaining=500)

    guard.spend(29)

    assert source.calls == 1


def test_pauses_when_spending_would_cross_the_reserve(clock):
    guard, _ = make_guard(clock, remaining=170, reserve=150)

    with pytest.raises(HistoryPausedError, match="Conversions still work"):
        guard.spend(29)


def test_spending_exactly_down_to_the_reserve_is_allowed(clock):
    guard, _ = make_guard(clock, remaining=179, reserve=150)

    guard.spend(29)


def test_counts_its_own_spending_between_usage_checks(clock):
    guard, source = make_guard(clock, remaining=200, reserve=150)

    guard.spend(29)  # 171 left by our own count
    with pytest.raises(HistoryPausedError):
        guard.spend(29)  # would leave 142, below the reserve
    assert source.calls == 1


def test_refreshes_real_usage_after_the_interval(clock):
    guard, source = make_guard(clock, remaining=210, reserve=150)
    guard.spend(29)

    clock.now = 600
    source.usage = UsageInfo(requests_remaining=900, requests_quota=1000)  # e.g. a new month
    guard.spend(29)

    assert source.calls == 2


def test_no_usage_check_when_nothing_needs_fetching(clock):
    guard, source = make_guard(clock, remaining=0)

    guard.spend(0)

    assert source.calls == 0


def test_unlimited_plans_are_never_paused(clock):
    guard, source = make_guard(clock, remaining=-1, quota=-1)

    for _ in range(5):
        guard.spend(29)

    assert source.calls == 1
