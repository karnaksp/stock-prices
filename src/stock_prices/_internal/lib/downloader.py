from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from stock_prices._internal.lib.global_data import download_global_data
from stock_prices._internal.lib.moex_data import download_moex_data


def _download_one(
    item: dict[str, str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    currency: str | None,
) -> None:
    ticker = item["ticker"]
    engine = item["engine"]
    market = item["market"]

    logging.info("[DOWNLOAD] %s (%s/%s)", ticker, engine, market)
    if engine == "global":
        download_global_data(engine, market, ticker, start_date, end_date, currency)
    else:
        download_moex_data(engine, market, ticker, start_date, end_date)


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
