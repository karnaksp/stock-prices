"""
Модуль для загрузки и отображения графиков цен на акции
"""

import logging
import pandas as pd
from lib.downloader import download_ticker_history
from lib.plotting import render_charts
from lib.utils import configure_logging, parse_arguments, get_ticker_specs


def main():
    arguments = parse_arguments()
    ticker_specs = get_ticker_specs(arguments)
    start_date = pd.Timestamp(arguments.start_date).normalize()
    end_date = pd.Timestamp(arguments.end_date).normalize()
    logging.info(f"Обработка {len(ticker_specs)} инструментов")
    logging.info(f"Диапазон дат: {start_date.date()} -> {end_date.date()}")
    download_ticker_history(ticker_specs, start_date, end_date, arguments.currency)
    render_charts(arguments, ticker_specs, start_date, end_date)
    logging.info("ЗАВЕРШЕНО.")


if __name__ == "__main__":
    configure_logging()
    main()
