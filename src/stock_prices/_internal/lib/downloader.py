from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from stock_prices._internal.lib.global_data import download_global_data
from stock_prices._internal.lib.moex_data import download_moex_data

HistoryKey = tuple[str, str, str]
HistoryData = dict[HistoryKey, pd.DataFrame]


def _download_one(
    item: dict[str, str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    currency: str | None,
    attempts: int = 3,
) -> tuple[HistoryKey, pd.DataFrame]:
    ticker = item["ticker"]
    engine = item["engine"]
    market = item["market"]
    key = (engine, market, ticker)

    logging.info("[DOWNLOAD] %s (%s/%s)", ticker, engine, market)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            if engine == "global":
                data = download_global_data(engine, market, ticker, start_date, end_date, currency)
            else:
                data = download_moex_data(engine, market, ticker, start_date, end_date)
            return key, data
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                logging.warning("[%s] Download attempt %s/%s failed: %s", ticker, attempt, attempts, exc)
                time.sleep(min(attempt, 3))

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to download {ticker}")


def download_ticker_history(
    specs: list[dict[str, str]],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    currency: str | None = None,
    max_workers: int = 4,
) -> HistoryData:
    history: HistoryData = {}
    if len(specs) <= 1:
        for item in specs:
            key, data = _download_one(item, start_date, end_date, currency)
            history[key] = data
        return history

    errors = []
    worker_count = min(max_workers, len(specs))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_download_one, item, start_date, end_date, currency) for item in specs]
        for future in as_completed(futures):
            try:
                key, data = future.result()
                history[key] = data
            except Exception as exc:
                logging.exception("Ticker download failed")
                errors.append(exc)
    if errors:
        msg = "; ".join(str(error) for error in errors)
        raise RuntimeError(f"Failed to download {len(errors)} ticker(s): {msg}")
    return history
