from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from stock_prices._internal.lib.file_utils import load_latest_parquet, load_ticker_df
from stock_prices._internal.lib.global_data import download_global_data
from stock_prices._internal.lib.moex_data import download_moex_data


def _has_cached_history(item: dict[str, str], start_date: pd.Timestamp, end_date: pd.Timestamp) -> bool:
    try:
        parquet_path = load_latest_parquet(item["engine"], item["market"], item["ticker"])
        cached = load_ticker_df(parquet_path)
    except Exception:
        return False
    if cached.empty:
        return False

    cached_start = pd.Timestamp(cached["TRADEDATE"].min()).floor("D")
    cached_end = pd.Timestamp(cached["TRADEDATE"].max()).floor("D")
    start_tolerance = pd.Timedelta(days=7)
    end_tolerance = pd.Timedelta(days=7)
    return cached_start <= start_date.floor("D") + start_tolerance and cached_end >= end_date.floor("D") - end_tolerance


def _download_one(
    item: dict[str, str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    currency: str | None,
    attempts: int = 3,
) -> None:
    ticker = item["ticker"]
    engine = item["engine"]
    market = item["market"]

    logging.info("[DOWNLOAD] %s (%s/%s)", ticker, engine, market)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            if engine == "global":
                download_global_data(engine, market, ticker, start_date, end_date, currency)
            else:
                download_moex_data(engine, market, ticker, start_date, end_date)
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                logging.warning("[%s] Download attempt %s/%s failed: %s", ticker, attempt, attempts, exc)
                time.sleep(min(attempt, 3))

    if _has_cached_history(item, start_date, end_date):
        logging.warning("[%s] Using cached history after download failure: %s", ticker, last_error)
        return
    if last_error is not None:
        raise last_error


def download_ticker_history(
    specs: list[dict[str, str]],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    currency: str | None = None,
    max_workers: int = 4,
) -> None:
    if len(specs) <= 1:
        for item in specs:
            _download_one(item, start_date, end_date, currency)
        return

    errors = []
    worker_count = min(max_workers, len(specs))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_download_one, item, start_date, end_date, currency) for item in specs]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                logging.exception("Ticker download failed")
                errors.append(exc)
    if errors:
        msg = "; ".join(str(error) for error in errors)
        raise RuntimeError(f"Failed to download {len(errors)} ticker(s): {msg}")
