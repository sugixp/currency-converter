"""REST API exposing the conversion service.

Run with: uvicorn currency_converter.api:app --reload
"""

import logging
from datetime import date, datetime

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from currency_converter.config import Settings, load_settings
from currency_converter.errors import (
    ConverterError,
    ExchangeRateProviderError,
    HistoryPausedError,
    InvalidAmountError,
    InvalidApiKeyError,
    InvalidCurrencyError,
    InvalidDaysError,
    ProviderUnavailableError,
    RateLimitExceededError,
    UnknownCurrencyError,
)
from currency_converter.service import MAX_HISTORY_DAYS, ConversionService, create_service

logger = logging.getLogger(__name__)

# Most specific classes first: the first isinstance match wins.
# Provider problems are the server's fault, not the caller's, so their messages
# stay generic; the details go to the server log instead.
ERROR_RESPONSES = [
    (InvalidAmountError, 400, "invalid_amount", None),
    (InvalidCurrencyError, 400, "invalid_currency", None),
    (InvalidDaysError, 400, "invalid_days", None),
    (UnknownCurrencyError, 404, "unknown_currency", None),
    (HistoryPausedError, 503, "history_paused", None),
    (InvalidApiKeyError, 502, "provider_auth_error",
     "This server's exchange rate provider credentials are missing or invalid."),
    (RateLimitExceededError, 503, "provider_rate_limited",
     "The exchange rate provider quota was exceeded. Please try again later."),
    (ProviderUnavailableError, 503, "provider_unavailable",
     "The exchange rate provider is unavailable. Please try again later."),
    (ExchangeRateProviderError, 502, "provider_error",
     "The exchange rate provider returned an unexpected response."),
]


class Currency(BaseModel):
    code: str
    name: str


class CurrenciesResponse(BaseModel):
    currencies: list[Currency]


class ConversionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_currency: str = Field(alias="from")
    to_currency: str = Field(alias="to")
    # Monetary values are strings so clients never lose precision to JSON floats.
    amount: str
    converted_amount: str
    rate: str
    rate_timestamp: datetime


class HistoryPoint(BaseModel):
    date: date
    rate: str


class HistoryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_currency: str = Field(alias="from")
    to_currency: str = Field(alias="to")
    points: list[HistoryPoint]


class ErrorResponse(BaseModel):
    error: str
    detail: str


def create_app(service: ConversionService | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    service = service or create_service(settings)

    app = FastAPI(
        title="Currency Converter API",
        description="Real-time currency conversion backed by Open Exchange Rates.",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.exception_handler(ConverterError)
    async def handle_converter_error(request: Request, exc: ConverterError):
        for error_class, status_code, code, public_message in ERROR_RESPONSES:
            if isinstance(exc, error_class):
                if public_message:
                    logger.error("Exchange rate provider error: %s", exc)
                return _error(status_code, code, public_message or str(exc))
        logger.exception("Unhandled converter error", exc_info=exc)
        return _error(500, "internal_error", "Unexpected error.")

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        missing = [str(error["loc"][-1]) for error in exc.errors() if error["type"] == "missing"]
        if missing:
            detail = f"Missing required query parameter(s): {', '.join(missing)}."
        else:
            detail = "Invalid request parameters."
        return _error(400, "invalid_request", detail)

    error_responses = {
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    }

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/currencies", response_model=CurrenciesResponse, responses=error_responses)
    def list_currencies():
        currencies = service.list_currencies()
        return CurrenciesResponse(
            currencies=[Currency(code=code, name=currencies[code]) for code in sorted(currencies)]
        )

    @app.get("/convert", response_model=ConversionResponse, responses=error_responses)
    def convert(
        from_currency: str = Query(alias="from", description="Source currency, e.g. USD"),
        to_currency: str = Query(alias="to", description="Target currency, e.g. BRL"),
        amount: str = Query(description="Positive amount to convert, e.g. 100 or 19.90"),
    ):
        result = service.convert(from_currency, to_currency, amount)
        return ConversionResponse(
            from_currency=result.from_currency,
            to_currency=result.to_currency,
            amount=format(result.amount, "f"),
            converted_amount=format(result.converted_amount, "f"),
            rate=format(result.rate, "f"),
            rate_timestamp=result.rate_timestamp,
        )

    @app.get("/history", response_model=HistoryResponse, responses=error_responses)
    def history(
        from_currency: str = Query(alias="from", description="Source currency, e.g. EUR"),
        to_currency: str = Query(alias="to", description="Target currency, e.g. BRL"),
        days: str = Query(
            default=str(MAX_HISTORY_DAYS),
            description=f"Number of days ending today (2 to {MAX_HISTORY_DAYS})",
        ),
    ):
        result = service.get_history(from_currency, to_currency, days)
        return HistoryResponse(
            from_currency=result.from_currency,
            to_currency=result.to_currency,
            points=[
                HistoryPoint(date=point.day, rate=format(point.rate, "f"))
                for point in result.points
            ],
        )

    return app


def _error(status_code: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": code, "detail": detail})


app = create_app()
