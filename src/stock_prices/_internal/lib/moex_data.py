"""
Модуль для загрузки данных с Московской биржи
"""

import logging
import requests
import pandas as pd
import apimoex
from .events import load_events, add_events
from .file_utils import save_to_parquet
from .validators import validate_quote_structure


def get_div_for_me(
    ticker: str, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> pd.DataFrame:
    """
    Получение данных по дивидендам через yfinance только для акций Московской биржи, т.к. к тикеру сразу добавляется {ticker}.ME

    Args:
        ticker: Тикер ценной бумаги
        start_date: Начальная дата
        end_date: Конечная дата

    Returns:
        DataFrame с дивидендами
    """
    import yfinance as yf

    symbol = f"{ticker}.ME"
    yf_ticker = yf.Ticker(symbol)
    dividends = yf_ticker.dividends.loc[
        start_date.strftime("%Y-%m-%d") : end_date.strftime("%Y-%m-%d")
    ]
    if dividends.empty:
        return pd.DataFrame(columns=["TRADEDATE", "DIVIDEND"])
    dividends = dividends.reset_index()
    dividends["Date"] = pd.to_datetime(dividends["Date"]).dt.tz_localize(None)
    dividends = dividends.rename(columns={"Date": "TRADEDATE", "Dividends": "DIVIDEND"})
    dividends = dividends[["TRADEDATE", "DIVIDEND"]]
    dividends = dividends.sort_values("TRADEDATE")
    return dividends


def enrich_me_data(
    data_frame: pd.DataFrame,
    ticker: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """
    Обогощение данных MOEX (+ дивы + события)

    Args:
        data_frame: DataFrame с исходными данными
        ticker: Тикер
        start_date: Начальная дата
        end_date: Конечная дата

    Returns:
        Обработанный DataFrame
    """
    if "BOARDID" in data_frame.columns:
        data_frame = data_frame.drop(columns=["BOARDID"])
    grouped = (
        data_frame.groupby("TRADEDATE")
        .agg({"CLOSE": "mean", "VOLUME": "sum", "VALUE": "sum"})
        .reset_index()
    )
    div_df = get_div_for_me(ticker, start_date, end_date)
    merged = grouped.merge(div_df, on="TRADEDATE", how="left")
    merged["DIVIDEND"] = merged["DIVIDEND"].fillna(0)
    events_df = load_events()
    add_events(merged, events_df)
    return merged


def download_moex_data(
    engine: str,
    market: str,
    ticker: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
):
    """
    Загрузка данных с MOEX

    Args:
        engine: Движок торгов
        market: Рынок
        ticker: Тикер
        start_date: Начальная дата
        end_date: Конечная дата
    """
    date_str = f"{int(start_date.timestamp())}-{int(end_date.timestamp())}"
    with requests.Session() as session:
        data = apimoex.get_market_history(
            session,
            security=ticker,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            engine=engine,
            market=market,
        )
        if data:
            valid_data = [
                row for row in data if validate_quote_structure(row, engine, market)
            ]
            df = pd.DataFrame(valid_data)
            df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
            validated = enrich_me_data(df, ticker, start_date, end_date)
            save_to_parquet(
                validated, engine, market, ticker, date_str.replace("-", "")
            )
        else:
            logging.error(
                f'Нет данных для "{ticker}, {engine}, {market}" за период {start_date} - {end_date}'
            )
