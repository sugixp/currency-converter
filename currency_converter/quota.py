"""Safety limit that keeps historical requests from draining the monthly quota.

Open Exchange Rates reports the account's real usage at usage.json, which
does not count toward the quota itself. Before fetching uncached history
days, the guard checks that enough requests would remain for conversions.
"""

import threading
import time
from typing import Callable

from currency_converter.errors import HistoryPausedError
from currency_converter.oxr_client import UsageInfo

USAGE_REFRESH_SECONDS = 600


class QuotaGuard:
    def __init__(
        self,
        fetch_usage: Callable[[], UsageInfo],
        reserve: int,
        refresh_seconds: float = USAGE_REFRESH_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._fetch_usage = fetch_usage
        self._reserve = reserve
        self._refresh_seconds = refresh_seconds
        self._clock = clock
        self._remaining: int | None = None  # None means the plan is unlimited
        self._refresh_at = float("-inf")
        self._lock = threading.Lock()

    def spend(self, requests_needed: int) -> None:
        """Allow `requests_needed` provider calls, or raise HistoryPausedError."""
        if requests_needed <= 0:
            return
        with self._lock:
            if self._clock() >= self._refresh_at:
                usage = self._fetch_usage()
                self._remaining = None if usage.unlimited else usage.requests_remaining
                self._refresh_at = self._clock() + self._refresh_seconds

            if self._remaining is None:  # unlimited plan
                return
            if self._remaining - requests_needed < self._reserve:
                raise HistoryPausedError(
                    "The history chart is paused to save this month's exchange rate quota. "
                    "Conversions still work."
                )
            # Count our own spending until the next refresh, so a burst of
            # requests between usage checks cannot overshoot the reserve.
            self._remaining -= requests_needed
