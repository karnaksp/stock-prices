"""
Модуль для работы с файлами
"""

import os
import logging
import pandas as pd


def get_parquet_filepath(engine: str, market: str, ticker: str, date_str: str) -> str:
    """
    Генерация пути к файлу parquet по заданным параметрам

    Args:
        engine: Движок торгов
        market: Рынок
        ticker: Тикер
        date_str: Строковое представление диапазона дат

    Returns:
        Путь к файлу
    """
    return f"./{engine}/{market}/{ticker}/{date_str}.parquet"


def save_to_parquet(
    data: pd.DataFrame, engine: str, market: str, ticker: str, date_str: str
):
    """
    Сохранение данных в формате parquet

    Args:
        data: DataFrame с данными
        engine: Движок торгов
        market: Рынок
        ticker: Тикер
        date_str: Строковое представление диапазона дат
    """
    filepath = get_parquet_filepath(engine, market, ticker, date_str)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    data.to_parquet(filepath, index=False)
    logging.info(f"[{ticker}] Данные сохранены в {filepath}")


def load_latest_parquet(engine, market, ticker):
    """
    Загружает последний parquet файл для заданного тикера

    Args:
        engine: Движок торгов
        market: Рынок
        ticker: Тикер

    Returns:
        Путь к последнему parquet файлу
    """
    from pathlib import Path

    base = Path(engine) / market / ticker
    if not base.exists():
        raise FileNotFoundError(f"Путь не существует: {base}")
    files = list(base.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"Нет parquet файлов в: {base}")
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0]


def load_ticker_df(path, start_date=None, end_date=None):
    """
    Загружает DataFrame из parquet файла

    Args:
        path: Путь к parquet файлу
        start_date: Начальная дата фильтрации
        end_date: Конечная дата фильтрации

    Returns:
        DataFrame с торговыми данными
    """
    df = pd.read_parquet(path)
    df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"]).dt.date
    df = df.sort_values("TRADEDATE")
    if start_date:
        df = df[df["TRADEDATE"] >= start_date.date()]
    if end_date:
        df = df[df["TRADEDATE"] <= end_date.date()]
    return df
