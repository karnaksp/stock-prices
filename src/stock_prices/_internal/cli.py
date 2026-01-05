# Why does this file exist, and why not put this in `__main__`?
#
# You might be tempted to import things from `__main__` later,
# but that will cause problems: the code will get executed twice:
#
# - When you run `python -m stock_prices` python will execute
#   `__main__.py` as a script. That means there won't be any
#   `stock_prices.__main__` in `sys.modules`.
# - When you import `__main__` it will get executed again (as a module) because
#   there's no `stock_prices.__main__` in `sys.modules`.

from __future__ import annotations

import argparse
import sys
from typing import Any
import logging
import pandas as pd
from lib.downloader import download_ticker_history
from lib.plotting import render_charts
from lib.utils import configure_logging, get_ticker_specs

from stock_prices._internal import debug


class _DebugInfo(argparse.Action):
    def __init__(self, nargs: int | str | None = 0, **kwargs: Any) -> None:
        super().__init__(nargs=nargs, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        debug._print_debug_info()
        sys.exit(0)


class CustomHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """
    Форматтер для аргументов командной строки
    """

    def __init__(self, prog, indent_increment=2, max_help_position=30, width=120):
        super().__init__(prog, indent_increment, max_help_position, width)


def parse_arguments():
    """
    Разбор аргументов командной строки

    Returns:
        Объект с аргументами командной строки
    """
    from datetime import datetime

    parser = argparse.ArgumentParser(
        description="Формирование видео графика на основе исторических цен",
        formatter_class=CustomHelpFormatter,
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {debug._get_version()}"
    )
    parser.add_argument(
        "--debug-info", action=_DebugInfo, help="Print debug information."
    )
    parser.add_argument(
        "--tickers",
        nargs="*",
        help="Спецификации тикеров: TICKER|ENGINE|MARKET",
    )
    parser.add_argument(
        "--ticker_file",
        help="Файл, содержащий спецификации тикеров (по одной на строку)",
    )
    parser.add_argument(
        "--start_date",
        required=True,
        type=lambda d: datetime.strptime(d, "%Y-%m-%d"),
        help="Дата начала в формате YYYY-MM-DD",
    )
    parser.add_argument(
        "--end_date",
        required=True,
        type=lambda d: datetime.strptime(d, "%Y-%m-%d"),
        help="Дата окончания в формате YYYY-MM-DD",
    )
    parser.add_argument(
        "--with_investments",
        action="store_true",
        help="Учитывать инвестиции при расчетах",
    )
    parser.add_argument(
        "--use_gradient",
        action="store_true",
        help="Использовать градиентное изменение цвета",
    )
    parser.add_argument(
        "--initial_investment",
        type=int,
        default=10000,
        help="Начальная сумма инвестиций",
    )
    parser.add_argument(
        "--monthly_investment", type=int, default=0, help="Ежемесячные инвестиции"
    )
    parser.add_argument(
        "--yearly_investment", type=int, default=0, help="Ежегодные инвестиции"
    )
    parser.add_argument(
        "--value_col",
        default="CAPITAL_REINVEST",
        help="Колонка значений для отображения",
    )
    parser.add_argument(
        "--duration", type=int, default=30, help="Продолжительность анимации в секундах"
    )
    parser.add_argument("--fps", type=int, default=20, help="Частота кадров в секунду")
    parser.add_argument(
        "--no_legend", action="store_true", help="Не отображать легенду"
    )
    parser.add_argument("--currency", default="$", help="Валюта отображения")
    parser.add_argument("--title", default="", help="Заголовок графика")
    parser.add_argument("--under_title", default="", help="Подзаголовок графика")
    args = parser.parse_args()
    if not args.tickers and not args.ticker_file:
        parser.error("Необходимо указать либо --tickers, либо --ticker_file")
    return args


def main():
    configure_logging()
    arguments = parse_arguments()
    ticker_specs = get_ticker_specs(arguments)
    start_date = pd.Timestamp(arguments.start_date).normalize()
    end_date = pd.Timestamp(arguments.end_date).normalize()
    logging.info(f"Обработка {len(ticker_specs)} инструментов")
    logging.info(f"Диапазон дат: {start_date.date()} -> {end_date.date()}")
    download_ticker_history(ticker_specs, start_date, end_date, arguments.currency)
    render_charts(arguments, ticker_specs, start_date, end_date)
    logging.info("ЗАВЕРШЕНО.")
