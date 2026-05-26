from __future__ import annotations

import logging

import pandas as pd

from stock_prices._internal.lib.events import add_events, load_events
from stock_prices._internal.lib.file_utils import save_to_parquet


def get_ticker_currency(ticker: str) -> str:
    import yfinance as yf

    try:
        info = yf.Ticker(ticker).info
        currency = info.get("currency") or "UNKNOWN"
        logging.info("[%s] Source currency: %s", ticker, currency)
        return currency
    except Exception as exc:
        logging.warning("[%s] Failed to get ticker currency: %s", ticker, exc)
        return "UNKNOWN"


def get_yf_data(ticker: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    import yfinance as yf

    try:
        history = yf.Ticker(ticker).history(start=start_date, end=end_date + pd.Timedelta(days=1), auto_adjust=False)
    except Exception as exc:
        logging.error("Failed to download history for %s: %s", ticker, exc)
        return pd.DataFrame()
    if history.empty:
        logging.warning("No historical data for %s", ticker)
        return pd.DataFrame()
    return history


def make_hard_columns(history: pd.DataFrame) -> pd.DataFrame:
    if isinstance(history.index, pd.Index) and hasattr(history.index, "tz") and history.index.tz is not None:
        history.index = history.index.tz_convert(None)

    df = history.reset_index().rename(columns={"Date": "TRADEDATE"})
    df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"]).dt.floor("D")
    df["OPEN"] = df.get("Open")
    df["HIGH"] = df.get("High")
    df["LOW"] = df.get("Low")
    df["CLOSE"] = df.get("Close")
    df["VOLUME"] = df.get("Volume", 0).fillna(0) if "Volume" in df else 0
    df["VALUE"] = df["CLOSE"] * df["VOLUME"]
    return df.groupby("TRADEDATE", as_index=False).agg(
        {"OPEN": "first", "HIGH": "max", "LOW": "min", "CLOSE": "last", "VOLUME": "sum", "VALUE": "sum"}
    )


def get_dividends(ticker: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    import yfinance as yf

    try:
        dividends = yf.Ticker(ticker).dividends
    except Exception:
        dividends = pd.Series(dtype=float)
    if dividends.empty:
        return pd.DataFrame({"TRADEDATE": pd.Series(dtype="datetime64[ns]"), "DIVIDEND": pd.Series(dtype="float64")})

    if hasattr(dividends.index, "tz") and dividends.index.tz is not None:
        dividends.index = dividends.index.tz_convert(None)
    dividends = dividends.loc[start_date:end_date]
    dividends_df = dividends.reset_index().rename(columns={"Date": "TRADEDATE", "Dividends": "DIVIDEND"})
    dividends_df["TRADEDATE"] = pd.to_datetime(dividends_df["TRADEDATE"]).dt.floor("D")
    return dividends_df.groupby("TRADEDATE", as_index=False).agg({"DIVIDEND": "sum"})


def add_dividends_to_df(df: pd.DataFrame, dividends_df: pd.DataFrame) -> pd.DataFrame:
    df = df.merge(dividends_df, on="TRADEDATE", how="left")
    df["DIVIDEND"] = pd.to_numeric(df["DIVIDEND"], errors="coerce").fillna(0.0)
    return df


def save_original_values(df: pd.DataFrame) -> pd.DataFrame:
    for column in ["OPEN", "HIGH", "LOW", "CLOSE", "VALUE", "DIVIDEND"]:
        df[f"{column}_ORIG"] = df[column]
    return df


def convert_to_rub_if_needed(df: pd.DataFrame, ticker: str, base_currency: str, convert_to_rub: bool) -> pd.DataFrame:
    if not convert_to_rub or base_currency in {"UNKNOWN", "RUB"}:
        if convert_to_rub and base_currency == "RUB":
            logging.info("[%s] Ticker is already in RUB", ticker)
        return df

    logging.info("[%s] Converting %s to RUB", ticker, base_currency)
    try:
        from currency_converter import CurrencyConverter

        converter = CurrencyConverter(fallback_on_missing_rate=True, fallback_on_wrong_date=True)
        rates = []
        for trade_date in pd.to_datetime(df["TRADEDATE"]).dt.date.unique():
            try:
                rates.append({"TRADEDATE": pd.Timestamp(trade_date), "FX_RATE": converter.convert(1, base_currency, "RUB", date=trade_date)})
            except ValueError as exc:
                logging.warning("[%s] Missing %s/RUB rate for %s: %s", ticker, base_currency, trade_date, exc)
                rates.append({"TRADEDATE": pd.Timestamp(trade_date), "FX_RATE": None})
        fx_df = pd.DataFrame(rates)
        df = df.merge(fx_df, on="TRADEDATE", how="left")
        df["FX_RATE"] = df["FX_RATE"].ffill().bfill()
        price_cols = ["OPEN", "HIGH", "LOW", "CLOSE", "VALUE", "DIVIDEND"]
        df[price_cols] = df[price_cols].multiply(df["FX_RATE"], axis=0)
    except Exception as exc:
        logging.error("[%s] Currency conversion failed: %s", ticker, exc)
    return df


def download_global_data(
    engine: str,
    market: str,
    ticker: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    currency: str | None = None,
) -> None:
    rub_variants = {"RUB", "R", "РУБЛЬ", "РУБ", "₽", "Р"}
    convert_to_rub = bool(currency and str(currency).strip().upper() in rub_variants)
    start_date = pd.Timestamp(start_date).tz_localize(None)
    end_date = pd.Timestamp(end_date).tz_localize(None)
    date_str = f"{start_date:%Y%m%d}_{end_date:%Y%m%d}"

    logging.info("[%s] Downloading %s to %s", ticker, start_date.date(), end_date.date())
    base_currency = get_ticker_currency(ticker)
    history = get_yf_data(ticker, start_date, end_date)
    if history.empty:
        raise ValueError(f"No historical data for {ticker}")

    df = make_hard_columns(history)
    df = add_dividends_to_df(df, get_dividends(ticker, start_date, end_date))
    df = save_original_values(df)
    df = convert_to_rub_if_needed(df, ticker, base_currency, convert_to_rub)
    add_events(df, load_events())
    df.attrs["ticker"] = ticker
    df.attrs["base_currency"] = base_currency
    df.attrs["target_currency"] = "RUB" if convert_to_rub else base_currency
    save_to_parquet(df, engine, market, ticker, date_str)
