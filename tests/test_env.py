from __future__ import annotations

import os
from pathlib import Path

from stock_prices._internal.cli import get_bot_parser
from stock_prices._internal.env import load_env_file


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
