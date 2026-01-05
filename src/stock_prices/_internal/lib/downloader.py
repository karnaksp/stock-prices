"""
Модуль для загрузки исторических данных по ценным бумагам
"""

import logging
from typing import Optional
import pandas as pd

from .moex_data import download_moex_data
from .global_data import download_global_data


def download_ticker_history(
    specs: list,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    currency: Optional[str] = None,
):
    """
    Загрузка исторических данных по тикерам

    Args:
        specs: Список спецификаций тикеров
        start_date: Начальная дата
        end_date: Конечная дата
        currency: Валюта для конвертации
    """
    for item in specs:
        ticker = item["ticker"]
        engine = item["engine"]
        market = item["market"]

        logging.info(f"[ЗАГРУЗКА] {ticker} ({engine}/{market})")
        if engine == "global":
            download_global_data(
                engine=engine,
                market=market,
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
            )
        else:
            download_moex_data(
                engine=engine,
                market=market,
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
            )
