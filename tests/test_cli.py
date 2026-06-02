"""Tests for the CLI."""

from __future__ import annotations

import pytest

from stock_prices import main
from stock_prices._internal.cli import get_bot_parser, parse_arguments, request_from_args
from stock_prices._internal import debug


def test_main() -> None:
    """Basic CLI test."""
    assert main([]) == 0


def test_show_help(capsys: pytest.CaptureFixture) -> None:
    """Show help.

    Parameters:
        capsys: Pytest fixture to capture output.
    """
    with pytest.raises(SystemExit):
        main(["-h"])
    captured = capsys.readouterr()
    assert "stock-prices" in captured.out


def test_show_version(capsys: pytest.CaptureFixture) -> None:
    """Show version.

    Parameters:
        capsys: Pytest fixture to capture output.
    """
    with pytest.raises(SystemExit):
        main(["-V"])
    captured = capsys.readouterr()
    assert debug._get_version() in captured.out


def test_show_debug_info(capsys: pytest.CaptureFixture) -> None:
    """Show debug information.

    Parameters:
        capsys: Pytest fixture to capture output.
    """
    with pytest.raises(SystemExit):
        main(["--debug-info"])
    captured = capsys.readouterr().out.lower()
    assert "python" in captured
    assert "system" in captured
    assert "environment" in captured
    assert "packages" in captured


def test_cli_request_accepts_theme() -> None:
    args = parse_arguments(
        [
            "--tickers",
            "LKOH",
            "--start_date",
            "2020-01-01",
            "--end_date",
            "2020-01-02",
            "--theme",
            "studio",
        ]
    )

    assert request_from_args(args).render.theme == "studio"


def test_bot_parser_reads_theme_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_PRICES_THEME", "aurora")

    args = get_bot_parser().parse_args([])

    assert args.theme == "aurora"
