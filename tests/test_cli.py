import pytest

from currency_converter.cli import main
from currency_converter.errors import InvalidApiKeyError


class FakeTerminal:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.lines = []

    def input(self, prompt):
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def print(self, text=""):
        self.lines.append(text)

    @property
    def text(self):
        return "\n".join(self.lines)


def run(service, argv, *answers):
    terminal = FakeTerminal(*answers)
    exit_code = main(argv, service=service, input_func=terminal.input, output=terminal.print)
    return exit_code, terminal.text


def test_one_shot_conversion(service):
    exit_code, text = run(service, ["usd", "brl", "100"])

    assert exit_code == 0
    assert "100 USD = 507.02 BRL" in text
    assert "Rate: 1 USD = 5.070200 BRL (as of 2026-11-01 12:00 UTC)" in text


def test_one_shot_error_returns_non_zero(service):
    exit_code, text = run(service, ["USD", "ZZZ", "1"])

    assert exit_code == 1
    assert "Error: Currency 'ZZZ' is not supported." in text


def test_one_shot_requires_all_arguments(service):
    with pytest.raises(SystemExit):
        run(service, ["USD", "BRL"])


def test_interactive_session_until_exit(service):
    exit_code, text = run(service, [], "EUR", "BRL", "100", "USD", "BRL", "-5", "exit")

    assert exit_code == 0
    assert "100 EUR = 551.11 BRL" in text
    assert "Error: Amount must be greater than zero." in text


def test_interactive_session_ends_on_eof(service):
    exit_code, _ = run(service, [], "USD")

    assert exit_code == 0


def test_interactive_session_reports_provider_errors(service, fake_client):
    fake_client.error = InvalidApiKeyError("Open Exchange Rates rejected the App ID.")

    _, text = run(service, [], "USD", "BRL", "1", "quit")

    assert "Error: Open Exchange Rates rejected the App ID." in text
