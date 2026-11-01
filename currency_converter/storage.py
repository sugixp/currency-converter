"""Key-value stores used to keep caches across restarts.

- DiskStore: JSON files in a folder (local development).
- UpstashStore: Upstash Redis over its REST API (production on hosts whose
  disk is wiped on every restart, like Render's free plan).

Stores are an optimization: every failure is logged and treated as a cache
miss, so a storage outage never breaks a conversion.
"""

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import requests

from currency_converter.oxr_client import RatesSnapshot

logger = logging.getLogger(__name__)


class KeyValueStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def get_many(self, keys: list[str]) -> list[str | None]: ...

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...


def snapshot_to_json(snapshot: RatesSnapshot) -> str:
    # Rates are stored as strings so they round-trip as exact Decimals.
    return json.dumps(
        {
            "timestamp": int(snapshot.timestamp.timestamp()),
            "rates": {code: str(rate) for code, rate in snapshot.rates.items()},
        }
    )


def snapshot_from_json(raw: str | None) -> RatesSnapshot | None:
    """Parse a stored snapshot; anything unreadable counts as a cache miss."""
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return RatesSnapshot(
            rates={code: Decimal(value) for code, value in data["rates"].items()},
            timestamp=datetime.fromtimestamp(data["timestamp"], tz=timezone.utc),
        )
    except (ValueError, KeyError, TypeError, ArithmeticError, AttributeError):
        logger.warning("Ignoring unreadable cached rates snapshot")
        return None


class DiskStore:
    """One JSON file per key. TTLs are ignored: only permanent data is stored here."""

    def __init__(self, directory: str | Path):
        self._directory = Path(directory)

    def get(self, key: str) -> str | None:
        path = self._path_for(key)
        try:
            return path.read_text(encoding="utf-8") if path.exists() else None
        except OSError:
            logger.warning("Could not read cache file %s", path, exc_info=True)
            return None

    def get_many(self, keys: list[str]) -> list[str | None]:
        return [self.get(key) for key in keys]

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        path = self._path_for(key)
        temp_path = path.with_suffix(".tmp")
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(value, encoding="utf-8")
            # Atomic rename: a crash mid-write never leaves a half-written file.
            os.replace(temp_path, path)
        except OSError:
            logger.warning("Could not write cache file %s", path, exc_info=True)

    def _path_for(self, key: str) -> Path:
        return self._directory / f"{key}.json"


class UpstashStore:
    """Upstash Redis via REST: each command is a JSON array POSTed with a bearer token."""

    def __init__(
        self,
        url: str,
        token: str,
        key_prefix: str = "",
        timeout_seconds: float = 5.0,
        session=None,
    ):
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._key_prefix = key_prefix
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def get(self, key: str) -> str | None:
        return self._command("GET", self._key_prefix + key)

    def get_many(self, keys: list[str]) -> list[str | None]:
        if not keys:
            return []
        result = self._command("MGET", *(self._key_prefix + key for key in keys))
        return result if isinstance(result, list) else [None] * len(keys)

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        command = ["SET", self._key_prefix + key, value]
        if ttl_seconds:
            command += ["EX", int(ttl_seconds)]
        self._command(*command)

    def _command(self, *command):
        try:
            response = self._session.post(
                self._url, json=list(command), headers=self._headers, timeout=self._timeout_seconds
            )
            body = response.json()
        except (requests.RequestException, ValueError):
            logger.warning("Upstash %s failed; continuing without the shared cache", command[0], exc_info=True)
            return None
        if response.status_code != 200 or not isinstance(body, dict) or "error" in body:
            error = body.get("error") if isinstance(body, dict) else None
            logger.warning(
                "Upstash %s returned HTTP %s (%s); continuing without the shared cache",
                command[0], response.status_code, error,
            )
            return None
        return body.get("result")
