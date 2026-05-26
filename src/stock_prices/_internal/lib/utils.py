from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from stock_prices._internal.models import parse_ticker_spec as parse_model_ticker_spec


def load_tickers_from_file(file_path: str) -> list[dict[str, str]]:
    ticker_specs = []
    with Path(file_path).open("r", encoding="utf-8") as file:
        for line_num, line in enumerate(file, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                ticker_specs.append(parse_ticker_spec(line))
            except ValueError as exc:
                msg = f"Error in line {line_num} of {file_path}: {exc}"
                raise ValueError(msg) from exc
    return ticker_specs


def get_ticker_specs(arguments: Any) -> list[dict[str, str]]:
    ticker_specs = []
    if getattr(arguments, "tickers", None):
        ticker_specs.extend(parse_ticker_spec(ticker_str) for ticker_str in arguments.tickers)
    if getattr(arguments, "ticker_file", None):
        ticker_specs.extend(load_tickers_from_file(arguments.ticker_file))
    if not ticker_specs:
        msg = "No tickers provided."
        raise ValueError(msg)

    seen = set()
    unique_specs = []
    for spec in ticker_specs:
        spec_key = (spec["ticker"], spec["engine"], spec["market"])
        if spec_key in seen:
            continue
        seen.add(spec_key)
        unique_specs.append(spec)
    return unique_specs


def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)


def configure_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        format="%(levelname)-7s:%(asctime)s: %(message)s",
        level=logging.INFO,
        handlers=[logging.FileHandler("./logs/requests.log", encoding="utf-8"), logging.StreamHandler()],
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def read_last_line(filepath: str) -> str:
    with Path(filepath).open("rb") as file:
        file.seek(0, os.SEEK_END)
        position = file.tell()
        if position == 0:
            return ""
        while position > 0:
            position -= 1
            file.seek(position)
            if file.read(1) == b"\n" and position != file.tell() - 1:
                break
        return file.readline().decode("utf-8").strip()


def parse_ticker_spec(spec: str) -> dict[str, str]:
    return parse_model_ticker_spec(spec).as_dict()
