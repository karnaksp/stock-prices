from __future__ import annotations

import os
from pathlib import Path

from stock_prices._internal.cli import get_bot_parser
from stock_prices._internal.env import (
    DEFAULT_MINI_APP_URL,
    get_cleanup_retention_days,
    get_mini_app_menu_button_enabled,
    get_mini_app_url,
    load_env_file,
)


def test_load_env_file_sets_missing_values(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=secret\nSTOCK_PRICES_FPS=24\n", encoding="utf-8")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("STOCK_PRICES_FPS", "12")

    load_env_file(env_file)

    assert os.environ["TELEGRAM_BOT_TOKEN"] == "secret"
    assert os.environ["STOCK_PRICES_FPS"] == "12"


def test_bot_help_does_not_print_token(monkeypatch, capsys) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    parser = get_bot_parser()

    try:
        parser.parse_args(["-h"])
    except SystemExit:
        pass

    assert "secret-token" not in capsys.readouterr().out


def test_bot_parser_reads_allowed_chat_ids_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_PRICES_ALLOWED_CHAT_IDS", "123, 456")

    args = get_bot_parser().parse_args([])

    assert args.allowed_chat_id == [123, 456]


def test_bot_parser_reads_mini_app_url_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_PRICES_MINI_APP_URL", "https://example.test/app/")

    args = get_bot_parser().parse_args([])

    assert args.mini_app_url == "https://example.test/app/"


def test_bot_parser_disables_mini_app_menu_button_by_default(monkeypatch) -> None:
    monkeypatch.delenv("STOCK_PRICES_MINI_APP_MENU_BUTTON", raising=False)

    args = get_bot_parser().parse_args([])

    assert args.mini_app_menu_button is False


def test_bot_parser_reads_mini_app_menu_button_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_PRICES_MINI_APP_MENU_BUTTON", "false")

    args = get_bot_parser().parse_args([])

    assert args.mini_app_menu_button is False


def test_bot_parser_allows_cli_to_disable_mini_app_menu_button(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_PRICES_MINI_APP_MENU_BUTTON", "true")

    args = get_bot_parser().parse_args(["--no-mini_app_menu_button"])

    assert args.mini_app_menu_button is False


def test_cleanup_retention_days_reads_primary_env(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_PRICES_RETENTION_DAYS", "14")

    assert get_cleanup_retention_days() == 14


def test_cleanup_retention_days_rejects_negative_values(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_PRICES_RETENTION_DAYS", "-1")

    try:
        get_cleanup_retention_days()
    except ValueError as exc:
        assert "non-negative integer" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_mini_app_url_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_PRICES_MINI_APP_URL", "https://example.test/miniapp/")

    assert get_mini_app_url() == "https://example.test/miniapp/"


def test_mini_app_url_uses_pages_default(monkeypatch) -> None:
    monkeypatch.delenv("STOCK_PRICES_MINI_APP_URL", raising=False)

    assert get_mini_app_url() == DEFAULT_MINI_APP_URL


def test_mini_app_menu_button_default_is_safe_for_send_data(monkeypatch) -> None:
    monkeypatch.delenv("STOCK_PRICES_MINI_APP_MENU_BUTTON", raising=False)

    assert get_mini_app_menu_button_enabled() is False


def test_mini_app_menu_button_reads_boolean_env(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_PRICES_MINI_APP_MENU_BUTTON", "off")

    assert get_mini_app_menu_button_enabled() is False

    monkeypatch.setenv("STOCK_PRICES_MINI_APP_MENU_BUTTON", "on")

    assert get_mini_app_menu_button_enabled() is True


def test_mini_app_menu_button_rejects_invalid_env(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_PRICES_MINI_APP_MENU_BUTTON", "maybe")

    try:
        get_mini_app_menu_button_enabled()
    except ValueError as exc:
        assert "boolean" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
