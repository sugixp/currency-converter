"""Permanent cache of historical rates, one entry per UTC day.

Rates for past days never change, so entries never expire: each day is fetched
from Open Exchange Rates at most once and then shared by every currency pair.
Entries are kept in memory and, optionally, in a persistent key-value store
(files locally, Upstash Redis in production) so they survive restarts.
"""

import threading
from datetime import date
from typing import Callable

from currency_converter.oxr_client import RatesSnapshot
from currency_converter.storage import KeyValueStore, snapshot_from_json, snapshot_to_json


class HistoricalRatesStore:
    def __init__(self, persistent: KeyValueStore | None = None):
        self._persistent = persistent
        self._snapshots: dict[date, RatesSnapshot] = {}
        # One lock per day: concurrent requests for the same day wait for a
        # single fetch, while different days can be fetched in parallel.
        self._day_locks: dict[date, threading.Lock] = {}
        self._day_locks_guard = threading.Lock()

    def missing_days(self, days: list[date]) -> list[date]:
        """Days that would need a provider request, after loading what the persistent store has.

        Uses a single batch read (MGET on Redis) instead of one read per day.
        """
        not_in_memory = [day for day in days if day not in self._snapshots]
        if not_in_memory and self._persistent is not None:
            stored = self._persistent.get_many([day.isoformat() for day in not_in_memory])
            for day, raw in zip(not_in_memory, stored):
                snapshot = snapshot_from_json(raw)
                if snapshot is not None:
                    self._snapshots[day] = snapshot
        return [day for day in days if day not in self._snapshots]

    def get_or_load(self, day: date, loader: Callable[[date], RatesSnapshot]) -> RatesSnapshot:
        with self._lock_for(day):
            snapshot = self._snapshots.get(day) or self._read_persistent(day)
            if snapshot is None:
                snapshot = loader(day)
                if self._persistent is not None:
                    self._persistent.set(day.isoformat(), snapshot_to_json(snapshot))
            self._snapshots[day] = snapshot
            return snapshot

    def _read_persistent(self, day: date) -> RatesSnapshot | None:
        if self._persistent is None:
            return None
        return snapshot_from_json(self._persistent.get(day.isoformat()))

    def _lock_for(self, day: date) -> threading.Lock:
        with self._day_locks_guard:
            return self._day_locks.setdefault(day, threading.Lock())
