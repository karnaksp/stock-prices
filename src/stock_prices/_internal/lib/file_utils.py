from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd


def _safe_path_part(value: str) -> str:
    return value.replace("/", "_").replace("\\", "_").replace("..", "_")


def get_parquet_filepath(engine: str, market: str, ticker: str, date_str: str) -> str:
    path = Path(_safe_path_part(engine)) / _safe_path_part(market) / _safe_path_part(ticker) / f"{date_str}.parquet"
    return str(path)


def save_to_parquet(data: pd.DataFrame, engine: str, market: str, ticker: str, date_str: str) -> None:
    filepath = Path(get_parquet_filepath(engine, market, ticker, date_str))
    filepath.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(filepath, index=False)
    logging.info("[%s] Data saved to %s", ticker, filepath)


def load_latest_parquet(engine: str, market: str, ticker: str) -> Path:
    base = Path(_safe_path_part(engine)) / _safe_path_part(market) / _safe_path_part(ticker)
    if not base.exists():
        raise FileNotFoundError(f"Path does not exist: {base}")
    files = list(base.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet files in: {base}")
    files.sort(key=lambda file: file.stat().st_mtime, reverse=True)
    return files[0]


def load_ticker_df(path: str | Path, start_date=None, end_date=None) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"]).dt.floor("D")
    df = df.sort_values("TRADEDATE")
    if start_date is not None:
        df = df[df["TRADEDATE"] >= pd.Timestamp(start_date).floor("D")]
    if end_date is not None:
        df = df[df["TRADEDATE"] <= pd.Timestamp(end_date).floor("D")]
    return df.reset_index(drop=True)
