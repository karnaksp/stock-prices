from __future__ import annotations

import logging

import apimoex
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from stock_prices._internal.lib.events import add_events, load_events
from stock_prices._internal.lib.file_utils import save_to_parquet
from stock_prices._internal.lib.validators import validate_quote_structure


class _TimeoutSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", 20)
        return super().request(method, url, **kwargs)


def _make_moex_session() -> requests.Session:
    session = _TimeoutSession()
    retries = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "stock-prices/0.1"})
    return session


def get_div_for_me(ticker: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    import yfinance as yf

    try:
        dividends = yf.Ticker(f"{ticker}.ME").dividends
    except Exception:
        dividends = pd.Series(dtype=float)
    if dividends.empty:
        return pd.DataFrame({"TRADEDATE": pd.Series(dtype="datetime64[ns]"), "DIVIDEND": pd.Series(dtype="float64")})
    if hasattr(dividends.index, "tz") and dividends.index.tz is not None:
        dividends.index = dividends.index.tz_convert(None)
    dividends = dividends.loc[start_date:end_date]
    if dividends.empty:
        return pd.DataFrame({"TRADEDATE": pd.Series(dtype="datetime64[ns]"), "DIVIDEND": pd.Series(dtype="float64")})
    dividends_df = dividends.reset_index().rename(columns={"Date": "TRADEDATE", "Dividends": "DIVIDEND"})
    dividends_df["TRADEDATE"] = pd.to_datetime(dividends_df["TRADEDATE"]).dt.floor("D")
    return dividends_df[["TRADEDATE", "DIVIDEND"]].sort_values("TRADEDATE")


def enrich_me_data(
    data_frame: pd.DataFrame,
    ticker: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    engine: str = "stock",
    market: str = "shares",
) -> pd.DataFrame:
    if data_frame.empty:
        raise ValueError(f"No MOEX rows for {ticker}")

    data_frame = data_frame.copy()
    data_frame["CLOSE"] = pd.to_numeric(data_frame["CLOSE"], errors="coerce")
    data_frame = data_frame.dropna(subset=["CLOSE"])
    if data_frame.empty:
        raise ValueError(f"No close prices for {ticker}")

    for column in ["VOLUME", "VALUE"]:
        if column not in data_frame:
            data_frame[column] = 0.0
        data_frame[column] = pd.to_numeric(data_frame[column], errors="coerce").fillna(0.0)

    grouped = data_frame.groupby("TRADEDATE", as_index=False).agg({"CLOSE": "mean", "VOLUME": "sum", "VALUE": "sum"})
    if engine == "stock" and market == "shares":
        grouped = grouped.merge(get_div_for_me(ticker, start_date, end_date), on="TRADEDATE", how="left")
        grouped["DIVIDEND"] = pd.to_numeric(grouped["DIVIDEND"], errors="coerce").fillna(0.0)
    else:
        grouped["DIVIDEND"] = 0.0
    add_events(grouped, load_events())
    return grouped


def download_moex_data(engine: str, market: str, ticker: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> None:
    date_str = f"{start_date:%Y%m%d}_{end_date:%Y%m%d}"
    with _make_moex_session() as session:
        data = apimoex.get_market_history(
            session,
            security=ticker,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            engine=engine,
            market=market,
        )
    if not data:
        raise ValueError(f"No data for {ticker}, {engine}, {market} in {start_date.date()} - {end_date.date()}")

    valid_data = [row for row in data if validate_quote_structure(row, engine, market)]
    if not valid_data:
        raise ValueError(f"No valid rows for {ticker}, {engine}, {market}")
    df = pd.DataFrame(valid_data)
    df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
    logging.info("[%s] Downloaded %s MOEX rows", ticker, len(df))
    save_to_parquet(enrich_me_data(df, ticker, start_date, end_date, engine, market), engine, market, ticker, date_str)
