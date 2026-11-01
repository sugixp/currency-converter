"""Command-line interface on top of the conversion service.

Interactive:  python -m currency_converter
One-shot:     python -m currency_converter USD BRL 100
"""

import argparse

from currency_converter.config import load_settings
from currency_converter.errors import ConverterError
from currency_converter.service import ConversionResult, ConversionService, create_service

EXIT_WORDS = {"exit", "quit"}


def main(argv=None, service: ConversionService | None = None, input_func=input, output=print) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m currency_converter",
        description="Convert currencies using real-time Open Exchange Rates data.",
    )
    parser.add_argument("from_currency", nargs="?", metavar="FROM", help="source currency, e.g. USD")
    parser.add_argument("to_currency", nargs="?", metavar="TO", help="target currency, e.g. BRL")
    parser.add_argument("amount", nargs="?", metavar="AMOUNT", help="amount to convert, e.g. 100")
    args = parser.parse_args(argv)

    provided = [args.from_currency, args.to_currency, args.amount]
    if any(provided) and not all(provided):
        parser.error("provide FROM, TO and AMOUNT, or no arguments for interactive mode")

    try:
        service = service or create_service(load_settings())
    except ValueError as exc:
        output(f"Configuration error: {exc}")
        return 1

    if all(provided):
        return _convert_once(service, *provided, output=output)
    _interactive(service, input_func, output)
    return 0


def _convert_once(service, from_currency, to_currency, amount, output) -> int:
    try:
        output(_format_result(service.convert(from_currency, to_currency, amount)))
    except ConverterError as exc:
        output(f"Error: {exc}")
        return 1
    return 0


def _interactive(service, input_func, output) -> None:
    output("=== Currency Converter ===")
    output("Type 'exit' to quit.\n")

    prompts = (
        "From currency (e.g. USD, BRL, EUR): ",
        "To currency (e.g. USD, BRL, EUR): ",
        "Amount: ",
    )
    while True:
        answers = []
        for prompt in prompts:
            try:
                answer = input_func(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                output("")
                return
            if answer.lower() in EXIT_WORDS:
                return
            answers.append(answer)

        output("")
        _convert_once(service, *answers, output=output)
        output("")


def _format_result(result: ConversionResult) -> str:
    timestamp = result.rate_timestamp.strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"{result.amount:f} {result.from_currency} = "
        f"{result.converted_amount:f} {result.to_currency}\n"
        f"Rate: 1 {result.from_currency} = {result.rate:f} {result.to_currency} "
        f"(as of {timestamp})"
    )
