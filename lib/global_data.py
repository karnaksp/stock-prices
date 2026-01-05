"""
Модуль для загрузки глобальных данных через yfinance
"""

import logging
import pandas as pd
from typing import Optional
from .events import load_events, add_events
from .file_utils import save_to_parquet


def get_ticker_currency(ticker: str) -> str:
    """
    Получение валюты тикера
    Args:
        ticker: Тикер
    Returns:
        Валюта тикера
    """
    import yfinance as yf

    yf_ticker = yf.Ticker(ticker)
    try:
        info = yf_ticker.info
        base_currency = info.get("currency") or "UNKNOWN"
        logging.info(f"[{ticker}] Исходная валюта тикера: {base_currency}")
        return base_currency
    except Exception as e:
        logging.warning(f"[{ticker}] Не удалось получить валюту тикера: {e}")
        return "UNKNOWN"


def get_yf_data(
    ticker: str, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> pd.DataFrame:
    """
    Загрузка исторических данных с Yahoo Finance

    Args:
        ticker: Тикер
        start_date: Начальная дата
        end_date: Конечная дата

    Returns:
        DataFrame с историческими данными
    """
    import yfinance as yf

    try:
        yf_ticker = yf.Ticker(ticker)
        hist = yf_ticker.history(start=start_date, end=end_date, auto_adjust=False)
    except Exception as e:
        logging.error(f"Ошибка при загрузке истории для {ticker}: {e}")
        return pd.DataFrame()

    if hist.empty:
        logging.warning(f"Нет исторических данных для {ticker}")
        return pd.DataFrame()

    return hist


def make_hard_columns(hist: pd.DataFrame) -> pd.DataFrame:
    """
    Подготовка DataFrame с торговыми данными в нужном формате столбцов
    Args:
        hist: Исторические данные из yfinance
    Returns:
        Подготовленный DataFrame
    """
    if isinstance(hist.index, pd.Index) and hasattr(hist.index, "tz"):
        hist.index = hist.index.tz_convert(None)

    df = hist.reset_index().rename(columns={"Date": "TRADEDATE"})
    df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"]).dt.floor("D")
    df["OPEN"] = df.get("Open")
    df["HIGH"] = df.get("High")
    df["LOW"] = df.get("Low")
    df["CLOSE"] = df.get("Close")
    if "Volume" in df.columns:
        df["VOLUME"] = df["Volume"].fillna(0)
    else:
        df["VOLUME"] = 0
    df["VALUE"] = df["CLOSE"] * df["VOLUME"]
    df = df.groupby("TRADEDATE", as_index=False).agg(
        {
            "OPEN": "first",
            "HIGH": "max",
            "LOW": "min",
            "CLOSE": "last",
            "VOLUME": "sum",
            "VALUE": "sum",
        }
    )

    return df


def get_dividends(
    ticker: str, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> pd.DataFrame:
    """
    Загрузка дивидендов для тикера
    Args:
        ticker: Тикер
        start_date: Начальная дата
        end_date: Конечная дата
    Returns:
        DataFrame с дивидендами
    """
    import yfinance as yf

    yf_ticker = yf.Ticker(ticker)
    try:
        dividends = yf_ticker.dividends
    except Exception:
        dividends = pd.Series(dtype=float)

    if not dividends.empty:
        if hasattr(dividends.index, "tz") and dividends.index.tz is not None:
            dividends.index = dividends.index.tz_convert(None)
        dividends = dividends.loc[start_date:end_date]
        dividends_df = dividends.reset_index().rename(
            columns={"Date": "TRADEDATE", "Dividends": "DIVIDEND"}
        )
        if hasattr(dividends_df["TRADEDATE"].dt, "floor"):
            dividends_df["TRADEDATE"] = dividends_df["TRADEDATE"].dt.floor("D")
        else:
            dividends_df["TRADEDATE"] = pd.to_datetime(
                dividends_df["TRADEDATE"]
            ).dt.floor("D")

        dividends_df = dividends_df.groupby("TRADEDATE", as_index=False).agg(
            {"DIVIDEND": "sum"}
        )
    else:
        dividends_df = pd.DataFrame(columns=["TRADEDATE", "DIVIDEND"])

    return dividends_df


def add_dividends_to_df(df: pd.DataFrame, dividends_df: pd.DataFrame) -> pd.DataFrame:
    """
    Добавление дивидендов к основному DataFrame

    Args:
        df: Основной DataFrame
        dividends_df: DataFrame с дивидендами

    Returns:
        DataFrame с добавленными дивидендами
    """
    df = df.merge(dividends_df, on="TRADEDATE", how="left")
    df["DIVIDEND"] = df["DIVIDEND"].fillna(0.0)
    return df


def save_original_values(df: pd.DataFrame) -> pd.DataFrame:
    """
    Сохранение оригинальных значений перед конвертацией

    Args:
        df: DataFrame с торговыми данными

    Returns:
        DataFrame с сохраненными оригинальными значениями
    """
    for col in ["OPEN", "HIGH", "LOW", "CLOSE", "VALUE", "DIVIDEND"]:
        df[f"{col}_ORIG"] = df[col]
    return df


def convert_to_rub_if_needed(
    df: pd.DataFrame, ticker: str, base_currency: str, convert_to_rub: bool
) -> pd.DataFrame:
    """
    Конвертация цен в рубли при необходимости

    Args:
        df: DataFrame с торговыми данными
        ticker: Тикер
        base_currency: Исходная валюта
        convert_to_rub: Флаг необходимости конвертации в рубли

    Returns:
        DataFrame с конвертированными ценами
    """
    import logging

    if convert_to_rub and base_currency != "UNKNOWN" and base_currency != "RUB":
        if base_currency == "RUB":
            logging.info(f"[{ticker}] Тикер уже в рублях — конвертация не требуется")
        else:
            logging.info(
                f"[{ticker}] Загружаем исторические курсы {base_currency}/RUB от ECB через CurrencyConverter"
            )
            try:
                from currency_converter import CurrencyConverter

                converter = CurrencyConverter(
                    fallback_on_missing_rate=True, fallback_on_wrong_date=True
                )
                rates_data = []
                unique_dates = pd.to_datetime(df["TRADEDATE"]).dt.date.unique()
                for trade_date in unique_dates:
                    try:
                        rate = converter.convert(
                            1, base_currency, "RUB", date=trade_date
                        )
                        rates_data.append(
                            {"TRADEDATE": pd.Timestamp(trade_date), "FX_RATE": rate}
                        )
                    except ValueError as ve:
                        logging.warning(
                            f"[{ticker}] Курс {base_currency}/RUB недоступен на {trade_date}: {ve}"
                        )
                        rates_data.append(
                            {"TRADEDATE": pd.Timestamp(trade_date), "FX_RATE": None}
                        )

                if not rates_data:
                    logging.error(
                        f"[{ticker}] Не удалось загрузить курсы {base_currency}/RUB"
                    )
                else:
                    fx_df = pd.DataFrame(rates_data)
                    df = df.merge(fx_df, on="TRADEDATE", how="left")
                    df["FX_RATE"] = df["FX_RATE"].ffill().bfill()
                    if df["FX_RATE"].isna().any():
                        logging.warning(
                            f"[{ticker}] Некоторые даты без курса после fill — останутся NaN"
                        )
                    price_cols = ["OPEN", "HIGH", "LOW", "CLOSE", "VALUE", "DIVIDEND"]
                    df[price_cols] = df[price_cols].multiply(df["FX_RATE"], axis=0)
                    logging.info(
                        f"[{ticker}] Конвертация в рубли через ECB (CurrencyConverter) завершена успешно"
                    )
            except ImportError:
                logging.error(
                    "Библиотека CurrencyConverter не установлена: pip install CurrencyConverter"
                )
            except Exception as e:
                logging.error(
                    f"[{ticker}] Ошибка при конвертации через CurrencyConverter: {e}"
                )
    elif convert_to_rub and base_currency == "RUB":
        logging.info(f"[{ticker}] Тикер уже в рублях — конвертация не требуется")

    return df


def download_global_data(
    engine: str,
    market: str,
    ticker: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    currency: Optional[str] = None,
) -> None:
    """
    Универсальный загрузчик данных по тикерам через yfinance
    с опциональной конвертацией всех ценовых колонок в рубли (RUB) через forex-python (ECB rates).

    Args:
        engine: Торговая система
        market: Рынок
        ticker: Тикер
        start_date: Начальная дата
        end_date: Конечная дата
        currency: Валюта для конвертации (по умолчанию None)

    Returns:
        None
    """
    convert_to_rub = False
    rub_variants = {"RUB", "R", "РУБЛЬ", "РУБ", "₽", "Р"}
    if currency and str(currency).strip().upper() in rub_variants:
        convert_to_rub = True
        logging.info(f"[{ticker}] Запрошена конвертация данных в рубли (RUB)")

    start_date = pd.Timestamp(start_date).tz_localize(None)
    end_date = pd.Timestamp(end_date).tz_localize(None)
    date_str = f"{start_date:%Y%m%d}_{end_date:%Y%m%d}"
    logging.info(
        f"[{ticker}] Загрузка данных с {start_date.date()} по {end_date.date()}"
    )
    base_currency = get_ticker_currency(ticker)
    hist = get_yf_data(ticker, start_date, end_date)
    if hist.empty:
        return
    df = make_hard_columns(hist)
    dividends_df = get_dividends(ticker, start_date, end_date)
    df = add_dividends_to_df(df, dividends_df)
    df = save_original_values(df)
    df = convert_to_rub_if_needed(df, ticker, base_currency, convert_to_rub)
    events_df = load_events()
    add_events(df, events_df)
    df.attrs["ticker"] = ticker
    df.attrs["base_currency"] = base_currency
    df.attrs["target_currency"] = "RUB" if convert_to_rub else base_currency
    save_to_parquet(df, engine, market, ticker, date_str)
