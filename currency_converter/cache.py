"""A small thread-safe in-memory cache whose entries expire after a fixed TTL."""

import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class TTLCache:
    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: dict[str, tuple[float, object]] = {}
        # The lock is held while loading, so concurrent requests for an expired
        # key trigger a single upstream call instead of one call each.
        self._lock = threading.Lock()

    def get_or_load(self, key: str, loader: Callable[[], T]) -> T:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and self._clock() < entry[0]:
                return entry[1]
            value = loader()
            self._entries[key] = (self._clock() + self._ttl_seconds, value)
            return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
