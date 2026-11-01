"""Settings loaded from environment variables (and from a .env file, if present)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    oxr_app_id: str
    cache_ttl_seconds: int = 3600
    request_timeout_seconds: float = 10.0
    cors_origins: tuple[str, ...] = ("*",)
    # None disables the on-disk history cache (memory only).
    history_cache_dir: str | None = None
    # When both are set, caches live in Upstash Redis and survive restarts.
    upstash_redis_rest_url: str | None = None
    upstash_redis_rest_token: str | None = None
    # Requests kept for conversions: history pauses before eating into them.
    quota_reserve: int = 150


def load_settings() -> Settings:
    load_dotenv()
    upstash_url = os.getenv("UPSTASH_REDIS_REST_URL", "").strip() or None
    upstash_token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip() or None
    if bool(upstash_url) != bool(upstash_token):
        raise ValueError("Set both UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN, or neither.")
    return Settings(
        oxr_app_id=os.getenv("OXR_APP_ID", "").strip(),
        # Unset means the default folder; set but empty means disabled.
        history_cache_dir=os.getenv("HISTORY_CACHE_DIR", ".cache/historical").strip() or None,
        cache_ttl_seconds=_read_number("CACHE_TTL_SECONDS", int, Settings.cache_ttl_seconds),
        request_timeout_seconds=_read_number(
            "REQUEST_TIMEOUT_SECONDS", float, Settings.request_timeout_seconds
        ),
        cors_origins=_read_list("CORS_ORIGINS", Settings.cors_origins),
        upstash_redis_rest_url=upstash_url,
        upstash_redis_rest_token=upstash_token,
        quota_reserve=_read_number("QUOTA_RESERVE", int, Settings.quota_reserve),
    )


def _read_number(name, parse, default):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = parse(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero, got {raw!r}")
    return value


def _read_list(name, default):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())
