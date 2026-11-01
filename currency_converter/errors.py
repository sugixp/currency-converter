"""Domain exceptions shared by the service, the CLI and the API."""


class ConverterError(Exception):
    """Base class for every error raised by this package."""


class InvalidAmountError(ConverterError):
    """The amount is not a number, is not positive, or is too large."""


class InvalidDaysError(ConverterError):
    """The number of history days is not an integer within the allowed range."""


class InvalidCurrencyError(ConverterError):
    """The currency code is not a 3-letter code."""


class UnknownCurrencyError(ConverterError):
    """The currency code is well formed but not offered by the provider."""


class ExchangeRateProviderError(ConverterError):
    """Open Exchange Rates returned something we could not use."""


class ProviderUnavailableError(ExchangeRateProviderError):
    """Open Exchange Rates is down, unreachable or timed out."""


class InvalidApiKeyError(ExchangeRateProviderError):
    """The App ID is missing or was rejected by Open Exchange Rates."""


class RateLimitExceededError(ExchangeRateProviderError):
    """The account exceeded its Open Exchange Rates request quota."""
