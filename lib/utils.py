"""
Вспомогательные функции
"""

import os
import logging
from datetime import timedelta
import argparse


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


def load_tickers_from_file(file_path: str) -> list:
    """
    Загрузка тикеров из файла

    Args:
        file_path: Путь к файлу с тикерами

    Returns:
        Список спецификаций тикеров
    """
    ticker_specs = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    ticker_specs.append(parse_ticker_spec(line))
                except ValueError as e:
                    raise ValueError(
                        f"Ошибка в строке {line_num} файла {file_path}: {e}"
                    )
    return ticker_specs


def get_ticker_specs(arguments) -> list:
    ticker_specs = []

    if arguments.tickers:
        for ticker_str in arguments.tickers:
            ticker_specs.append(parse_ticker_spec(ticker_str))

    if arguments.ticker_file:
        file_specs = load_tickers_from_file(arguments.ticker_file)
        ticker_specs.extend(file_specs)

    if not ticker_specs:
        raise ValueError("Не предоставлено ни одного тикера")

    seen = set()
    unique_specs = []
    for spec in ticker_specs:
        spec_key = (spec["ticker"], spec["engine"], spec["market"])
        if spec_key not in seen:
            seen.add(spec_key)
            unique_specs.append(spec)

    return unique_specs


def daterange(start_date, end_date):
    """
    Генерирует диапазон дат между двумя датами

    Args:
        start_date: Начальная дата
        end_date: Конечная дата

    Yields:
        Даты в диапазоне
    """
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)


def configure_logging():
    """
    Настраивает логирование
    """
    logging.basicConfig(
        format="%(levelname)-7s:%(asctime)s: %(message)s",
        level=logging.INFO,
        handlers=[logging.FileHandler("./logs/requests.log"), logging.StreamHandler()],
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def read_last_line(filepath):
    """
    Читает последнюю строку из файла

    Args:
        filepath: Путь к файлу

    Returns:
        Последняя строка файла
    """
    with open(filepath, "rb") as f:
        f.seek(-2, os.SEEK_END)
        while f.read(1) != b"\n":
            f.seek(-2, os.SEEK_CUR)
        return f.readline().decode().replace("\n", "")


def parse_ticker_spec(spec: str) -> dict:
    """
    Преобразует строку вида 'AAPL|global|shares'
    в структуру {ticker, engine, market}
    """
    parts = spec.split("|")
    if len(parts) != 3:
        raise ValueError(
            f"Неверный формат для '{spec}'. Ожидается ticker|engine|market"
        )
    return {
        "ticker": parts[0],
        "engine": parts[1],
        "market": parts[2],
    }
