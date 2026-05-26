from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from stock_prices._internal import debug
from stock_prices._internal.env import load_env_file
from stock_prices._internal.models import RenderSettings, VideoRequest, parse_ticker_spec
from stock_prices._internal.pipeline import generate_video
from stock_prices._internal.telegram_bot import TelegramBotSettings, run_telegram_bot
from stock_prices._internal.lib.utils import configure_logging, get_ticker_specs


class _DebugInfo(argparse.Action):
    def __init__(self, nargs: int | str | None = 0, **kwargs: Any) -> None:
        super().__init__(nargs=nargs, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        debug._print_debug_info()
        raise SystemExit(0)


class _HelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str, indent_increment: int = 2, max_help_position: int = 34, width: int = 120) -> None:
        super().__init__(prog, indent_increment, max_help_position, width)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_chat_ids(value: str | None) -> list[int]:
    if not value:
        return []
    chat_ids = []
    for raw_chat_id in value.replace(";", ",").split(","):
        raw_chat_id = raw_chat_id.strip()
        if raw_chat_id:
            chat_ids.append(int(raw_chat_id))
    return chat_ids


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock-prices",
        description="Generate animated stock-price videos.",
        formatter_class=_HelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {debug._get_version()}")
    parser.add_argument("--debug-info", action=_DebugInfo, help="Print debug information and exit.")
    parser.add_argument("--tickers", nargs="*", help="Ticker specs: TICKER or TICKER|ENGINE|MARKET.")
    parser.add_argument("--ticker_file", help="UTF-8 file with one ticker spec per line.")
    parser.add_argument("--start_date", type=_parse_date, default=date(2010, 1, 1), help="Start date, YYYY-MM-DD.")
    parser.add_argument("--end_date", type=_parse_date, default=date.today(), help="End date, YYYY-MM-DD.")
    parser.add_argument("--with_investments", action="store_true", help="Show reinvested-capital value.")
    parser.add_argument("--use_gradient", action="store_true", help="Use gradient line tails.")
    parser.add_argument("--initial_investment", type=int, default=10000, help="Initial investment amount.")
    parser.add_argument("--monthly_investment", type=int, default=0, help="Monthly investment amount.")
    parser.add_argument("--yearly_investment", type=int, default=0, help="Yearly investment amount.")
    parser.add_argument("--value_col", default="CAPITAL_REINVEST", help="Column rendered on the Y axis.")
    parser.add_argument("--duration", type=int, default=30, help="Animation duration in seconds.")
    parser.add_argument("--fps", type=int, default=20, help="Frames per second.")
    parser.add_argument("--no_legend", action="store_true", help="Hide legend.")
    parser.add_argument("--currency", default="RUB", help="Display currency label.")
    parser.add_argument("--title", default="", help="Chart title.")
    parser.add_argument("--under_title", default="", help="Chart subtitle.")
    parser.add_argument("--output_dir", default="animations", help="Directory for generated videos.")
    return parser


def get_bot_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock-prices bot",
        description="Run a Telegram bot that generates a video for each ticker message.",
        formatter_class=_HelpFormatter,
    )
    parser.add_argument("--token", default=None, help="Telegram bot token; defaults to TELEGRAM_BOT_TOKEN.")
    parser.add_argument("--allowed_chat_id", action="append", type=int, default=_parse_chat_ids(os.getenv("STOCK_PRICES_ALLOWED_CHAT_IDS")), help="Allowed Telegram chat id. Can also be set with STOCK_PRICES_ALLOWED_CHAT_IDS.")
    parser.add_argument("--default_engine", default=os.getenv("STOCK_PRICES_DEFAULT_ENGINE", "stock"))
    parser.add_argument("--default_market", default=os.getenv("STOCK_PRICES_DEFAULT_MARKET", "shares"))
    parser.add_argument("--start_date", type=_parse_date, default=date(2010, 1, 1))
    parser.add_argument("--end_date", type=_parse_date, default=date.today())
    parser.add_argument("--duration", type=int, default=int(os.getenv("STOCK_PRICES_DURATION", "30")))
    parser.add_argument("--fps", type=int, default=int(os.getenv("STOCK_PRICES_FPS", "20")))
    parser.add_argument("--currency", default=os.getenv("STOCK_PRICES_CURRENCY", "RUB"))
    parser.add_argument("--output_dir", default=os.getenv("STOCK_PRICES_OUTPUT_DIR", "animations"))
    parser.add_argument("--poll_timeout", type=int, default=30)
    parser.add_argument("--once", action="store_true", help="Process currently available updates once and exit.")
    return parser


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = get_parser()
    args = parser.parse_args(argv)
    if not args.tickers and not args.ticker_file:
        parser.error("Specify --tickers or --ticker_file.")
    if args.end_date < args.start_date:
        parser.error("--end_date must be greater than or equal to --start_date.")
    return args


def request_from_args(args: argparse.Namespace) -> VideoRequest:
    return VideoRequest(
        ticker_specs=[
            parse_ticker_spec(f"{spec['ticker']}|{spec['engine']}|{spec['market']}")
            for spec in get_ticker_specs(args)
        ],
        render=RenderSettings(
            start_date=args.start_date,
            end_date=args.end_date,
            value_col=args.value_col,
            duration=args.duration,
            fps=args.fps,
            currency=args.currency,
            title=args.title,
            under_title=args.under_title,
            use_gradient=args.use_gradient,
            show_legend=not args.no_legend,
            initial_investment=args.initial_investment,
            monthly_investment=args.monthly_investment,
            yearly_investment=args.yearly_investment,
            with_investments=args.with_investments,
            output_dir=Path(args.output_dir),
        ),
    )


def _run_generate(argv: Sequence[str]) -> int:
    parser = get_parser()
    if not argv:
        parser.print_help()
        return 0
    args = parse_arguments(argv)
    output_path = generate_video(request_from_args(args))
    logging.info("Video saved: %s", output_path)
    return 0


def _run_bot(argv: Sequence[str]) -> int:
    parser = get_bot_parser()
    args = parser.parse_args(argv)
    token = args.token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        parser.error("Provide --token or TELEGRAM_BOT_TOKEN.")

    settings = TelegramBotSettings(
        token=token,
        allowed_chat_ids=set(args.allowed_chat_id),
        default_engine=args.default_engine,
        default_market=args.default_market,
        poll_timeout=args.poll_timeout,
        once=args.once,
        render=RenderSettings(
            start_date=args.start_date,
            end_date=args.end_date,
            duration=args.duration,
            fps=args.fps,
            currency=args.currency,
            output_dir=Path(args.output_dir),
        ),
    )
    run_telegram_bot(settings)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    load_env_file()
    configure_logging()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "bot":
        return _run_bot(args[1:])
    return _run_generate(args)
