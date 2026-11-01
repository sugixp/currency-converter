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


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        oxr_app_id=os.getenv("OXR_APP_ID", "").strip(),
        cache_ttl_seconds=_read_number("CACHE_TTL_SECONDS", int, Settings.cache_ttl_seconds),
        request_timeout_seconds=_read_number(
            "REQUEST_TIMEOUT_SECONDS", float, Settings.request_timeout_seconds
        ),
        cors_origins=_read_list("CORS_ORIGINS", Settings.cors_origins),
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
