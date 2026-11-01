"""Build the rates snapshot published with the static site (frontend/snapshot.json).

The page shows this snapshot instantly while the API (which sleeps on Render's
free plan) wakes up. It is built only from what the API already cached in
Upstash Redis, read with a read-only token: it never calls Open Exchange Rates
and never wakes the API, so it costs no quota and no Render hours.

Usage (GitHub Actions):
    UPSTASH_REDIS_REST_URL=... UPSTASH_REDIS_REST_READONLY_TOKEN=... \\
        python scripts/build_snapshot.py --output frontend/snapshot.json
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from currency_converter.errors import ConverterError  # noqa: E402
from currency_converter.oxr_client import OpenExchangeRatesClient  # noqa: E402
from currency_converter.service import (  # noqa: E402
    LAST_KNOWN_RATES_KEY,
    LATEST_RATES_KEY,
    MAX_HISTORY_DAYS,
    UPSTASH_KEY_PREFIX,
)
from currency_converter.storage import KeyValueStore, UpstashStore, snapshot_from_json  # noqa: E402

logger = logging.getLogger("build_snapshot")

# The chart only needs about 7 significant digits; keeping all of them would
# roughly double the file. Latest rates keep full precision because the page
# uses them for its provisional conversion.
HISTORY_SIGNIFICANT_DIGITS = 7


def fetch_currency_names() -> dict[str, str]:
    """Currency names, so the page can fill its selects before the API answers.

    currencies.json needs no App ID and does not count toward the quota.
    """
    try:
        return OpenExchangeRatesClient(app_id="").fetch_currencies()
    except ConverterError:
        logger.warning("Could not fetch currency names; the page will show codes until the API answers.")
        return {}


def build_snapshot(store: KeyValueStore, now: datetime, currency_names: dict[str, str] | None = None) -> dict | None:
    """Snapshot dict from the cache, or None when the cache has no rates yet."""
    latest = snapshot_from_json(store.get(f"rates:{LAST_KNOWN_RATES_KEY}")) or snapshot_from_json(
        store.get(f"rates:{LATEST_RATES_KEY}")
    )
    if latest is None:
        return None

    today = latest.timestamp.date()
    days = [today - timedelta(days=offset) for offset in range(MAX_HISTORY_DAYS - 1, 0, -1)]
    stored = store.get_many([f"historical:{day.isoformat()}" for day in days])
    history = []
    for day, raw in zip(days, stored):
        snapshot = snapshot_from_json(raw)
        if snapshot is not None:  # days nobody has requested yet are simply absent
            history.append(
                {
                    "date": day.isoformat(),
                    "rates": {code: _short(rate) for code, rate in snapshot.rates.items()},
                }
            )

    return {
        "generated_at": _iso(now),
        "base": "USD",
        # Only currencies we actually have rates for, so every option can be converted.
        "currencies": {
            code: name for code, name in sorted((currency_names or {}).items()) if code in latest.rates
        },
        "latest": {
            "timestamp": _iso(latest.timestamp),
            "rates": {code: format(rate, "f") for code, rate in latest.rates.items()},
        },
        "history": history,
    }


def _short(rate: Decimal) -> str:
    return format(rate, f".{HISTORY_SIGNIFICANT_DIGITS}g")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True, help="where to write snapshot.json")
    args = parser.parse_args(argv)

    url = os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
    token = os.getenv("UPSTASH_REDIS_REST_READONLY_TOKEN", "").strip()
    if not url or not token:
        # The site still works without a snapshot (it just waits for the API).
        logger.warning("Upstash credentials not set; publishing without a snapshot.")
        return 0

    store = UpstashStore(url, token, key_prefix=UPSTASH_KEY_PREFIX)
    snapshot = build_snapshot(store, datetime.now(timezone.utc), fetch_currency_names())
    if snapshot is None:
        logger.warning("No cached rates found in Upstash; publishing without a snapshot.")
        return 0

    output = Path(args.output)
    output.write_text(json.dumps(snapshot, separators=(",", ":")), encoding="utf-8")
    logger.info(
        "Wrote %s: rates from %s, %d history days, %d bytes",
        output, snapshot["latest"]["timestamp"], len(snapshot["history"]), output.stat().st_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
