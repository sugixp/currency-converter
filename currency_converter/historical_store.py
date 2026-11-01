"""Permanent cache of historical rates, one entry per UTC day.

Rates for past days never change, so entries never expire: each day is fetched
from Open Exchange Rates at most once and then shared by every currency pair.
Entries are kept in memory and, optionally, as JSON files on disk so they
survive restarts (e.g. `uvicorn --reload`).
"""

import json
import logging
import os
import threading
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from currency_converter.oxr_client import RatesSnapshot

logger = logging.getLogger(__name__)


class HistoricalRatesStore:
    def __init__(self, cache_dir: str | Path | None = None):
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._snapshots: dict[date, RatesSnapshot] = {}
        # One lock per day: concurrent requests for the same day wait for a
        # single fetch, while different days can be fetched in parallel.
        self._day_locks: dict[date, threading.Lock] = {}
        self._day_locks_guard = threading.Lock()

    def get_or_load(self, day: date, loader: Callable[[date], RatesSnapshot]) -> RatesSnapshot:
        with self._lock_for(day):
            snapshot = self._snapshots.get(day) or self._read_file(day)
            if snapshot is None:
                snapshot = loader(day)
                self._write_file(day, snapshot)
            self._snapshots[day] = snapshot
            return snapshot

    def _lock_for(self, day: date) -> threading.Lock:
        with self._day_locks_guard:
            return self._day_locks.setdefault(day, threading.Lock())

    def _path_for(self, day: date) -> Path:
        return self._cache_dir / f"{day.isoformat()}.json"

    def _read_file(self, day: date) -> RatesSnapshot | None:
        if self._cache_dir is None:
            return None
        path = self._path_for(day)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return RatesSnapshot(
                rates={code: Decimal(value) for code, value in data["rates"].items()},
                timestamp=datetime.fromtimestamp(data["timestamp"], tz=timezone.utc),
            )
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError, AttributeError):
            logger.warning("Ignoring unreadable history cache file %s", path)
            return None

    def _write_file(self, day: date, snapshot: RatesSnapshot) -> None:
        if self._cache_dir is None:
            return
        # Rates are stored as strings so they round-trip as exact Decimals.
        data = {
            "timestamp": int(snapshot.timestamp.timestamp()),
            "rates": {code: str(rate) for code, rate in snapshot.rates.items()},
        }
        path = self._path_for(day)
        temp_path = path.with_suffix(".tmp")
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(json.dumps(data), encoding="utf-8")
            # Atomic rename: a crash mid-write never leaves a half-written file.
            os.replace(temp_path, path)
        except OSError:
            # The disk cache is an optimization; the in-memory copy still works.
            logger.warning("Could not write history cache file %s", path, exc_info=True)
