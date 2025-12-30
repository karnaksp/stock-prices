# -*- coding: utf-8 -*-

import os
import logging
import requests

import apimoex
import pandas as pd
import json


def load_events(json_path="events.json"):
    events = pd.read_json(json_path)
    events["start"] = pd.to_datetime(events["start"])
    events["end"] = pd.to_datetime(events["end"])
    return events


def enrich_with_events(df, events_df):
    df["EVENT_NAME"] = None
    df["EVENT_TYPE"] = None
    df["EVENT_IMPACT"] = 0

    for _, ev in events_df.iterrows():
        mask = (df["TRADEDATE"] >= ev["start"]) & (df["TRADEDATE"] <= ev["end"])
        df.loc[mask, "EVENT_NAME"] = ev["event"]
        df.loc[mask, "EVENT_TYPE"] = ev["type"]
        df.loc[mask, "EVENT_IMPACT"] = ev["impact"]

    return df


def get_parquet_filepath(engine, market, ticker, date_str):
    """
    Generate filepath for parquet files organized by date intervals
    """
    return f"./{engine}/{market}/{ticker}/{date_str}.parquet"


def save_to_parquet(data, engine, market, ticker, date_str):
    """
    Save data to parquet format with interval-based folder naming
    """
    filepath = get_parquet_filepath(engine, market, ticker, date_str)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    data.to_parquet(filepath, index=False)
    logging.info(f"Saved data to {filepath}")


def validate_float_val(quote, key):
    val = quote.get(key)
    return val is not None and isinstance(val, (int, float)) and val > 0


def validate_quote(quote, engine, market):
    if engine == "currency" and market == "selt":
        return (
            validate_float_val(quote, "VOLRUR")
            or validate_float_val(quote, "NUMTRADES")
            or validate_float_val(quote, "CLOSE")
        )
    elif engine == "stock" and market in ["bonds", "shares"]:
        return (
            validate_float_val(quote, "VOLUME")
            or validate_float_val(quote, "NUMTRADES")
            or validate_float_val(quote, "CLOSE")
        )
    elif engine == "stock" and market == "index":
        return validate_float_val(quote, "CLOSE")

    assert False, "Unknown quote type"


def div_data(ticker, start_date, end_date):
    """
    Получение данных по дивидендам через yfinance.
    Возвращает dataframe с колонками: TRADEDATE, DIVIDEND.
    Даты start_date и end_date используются для фильтрации.
    """
    import yfinance as yf
    import pandas as pd

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


def validate_data(df, ticker, start_date, end_date):
    """
    Обработка данных MOEX:
    - удаление BOARDID
    - группировка по TRADEDATE
    - CLOSE → mean
    - VOLUME → sum
    - VALUE → sum
    - объединение с дивидендами
    """
    if "BOARDID" in df.columns:
        df = df.drop(columns=["BOARDID"])
    grouped = (
        df.groupby("TRADEDATE")
        .agg({"CLOSE": "mean", "VOLUME": "sum", "VALUE": "sum"})
        .reset_index()
    )
    div_df = div_data(ticker, start_date, end_date)
    merged = grouped.merge(div_df, on="TRADEDATE", how="left")
    merged["DIVIDEND"] = merged["DIVIDEND"].fillna(0)
    events_df = load_events()
    merged = enrich_with_events(merged, events_df)
    return merged


def moex_data(engine, market, ticker, start_date, end_date):
    import pandas as pd

    date_str = f"{int(start_date.timestamp())}-{int(end_date.timestamp())}"
    with requests.Session() as session:
        data = apimoex.get_market_history(
            session,
            security=ticker,
            start=start_date,
            end=end_date,
            engine=engine,
            market=market,
        )
        if data:
            valid_data = [row for row in data if validate_quote(row, engine, market)]
            df = pd.DataFrame(valid_data)
            df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
            validated = validate_data(df, ticker, start_date, end_date)
            save_to_parquet(
                validated, engine, market, ticker, date_str.replace("-", "")
            )
        else:
            logging.error(
                'No data received for "{}, {}, {}"'.format(engine, market, date_str)
            )


def international_data(engine, market, ticker, start_date, end_date):
    """
    Универсальный загрузчик данных по любым международным тикерам через yfinance.
    Работает с акциями, индексами, ETF, фондами, криптой, фьючерсами и любыми другими инструментами.

    Создает колонки:
        TRADEDATE, OPEN, HIGH, LOW, CLOSE, VOLUME, VALUE, DIVIDEND

    Особенности:
    - Приводит все даты к типу date (без часового пояса).
    - Заполняет отсутствующие поля (для инструментов без объёмов и дивидендов).
    - Агрегирует дубликаты дат.
    - Гибкая обработка ошибок.
    """
    import yfinance as yf
    import pandas as pd
    import logging
    import os

    # --- Normalize dates ---
    start_date = pd.Timestamp(start_date).tz_localize(None)
    end_date = pd.Timestamp(end_date).tz_localize(None)
    date_str = f"{start_date:%Y%m%d}_{end_date:%Y%m%d}"

    logging.info(f"[{ticker}] Loading from {start_date.date()} to {end_date.date()}")

    yf_ticker = yf.Ticker(ticker)

    # --- HISTORICAL PRICES ---
    try:
        hist = yf_ticker.history(start=start_date, end=end_date, auto_adjust=False)
    except Exception as e:
        logging.error(f"Error loading history for {ticker}: {e}")
        return

    if hist.empty:
        logging.warning(f"No historical data for {ticker}")
        return

    # Remove timezone
    if hist.index.tz is not None:
        hist.index = hist.index.tz_convert(None)

    # Reset & rename
    df = hist.reset_index().rename(columns={"Date": "TRADEDATE"})
    df["TRADEDATE"] = df["TRADEDATE"].dt.floor("D")

    # Standard columns – even if missing
    df["OPEN"] = df.get("Open")
    df["HIGH"] = df.get("High")
    df["LOW"] = df.get("Low")
    df["CLOSE"] = df.get("Close")

    # Some instruments have no volume
    if "Volume" in df.columns:
        df["VOLUME"] = df["Volume"].fillna(0)
    else:
        df["VOLUME"] = 0

    df["VALUE"] = df["CLOSE"] * df["VOLUME"]

    # Aggregate per day
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

    # --- DIVIDENDS ---
    try:
        divs = yf_ticker.dividends
    except Exception:
        divs = pd.Series(dtype=float)

    if divs.empty:
        divs_df = pd.DataFrame(columns=["TRADEDATE", "DIVIDEND"])
    else:
        if divs.index.tz is not None:
            divs.index = divs.index.tz_convert(None)
        divs = divs.loc[start_date:end_date]
        divs_df = divs.reset_index().rename(
            columns={"Date": "TRADEDATE", "Dividends": "DIVIDEND"}
        )
        divs_df["TRADEDATE"] = divs_df["TRADEDATE"].dt.floor("D")
        divs_df = divs_df.groupby("TRADEDATE", as_index=False).agg({"DIVIDEND": "sum"})

    # Merge
    df = df.merge(divs_df, on="TRADEDATE", how="left")
    df["DIVIDEND"] = df["DIVIDEND"].fillna(0.0)

    # --- SAVE ---
    filepath = get_parquet_filepath(engine, market, ticker, date_str)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Optional enrich
    events_df = load_events()
    df = enrich_with_events(df, events_df)

    df.to_parquet(filepath, index=False)
    logging.info(f"[{ticker}] Saved parquet to {filepath}")
