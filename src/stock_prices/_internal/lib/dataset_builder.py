from __future__ import annotations

import logging
import random
import re
from typing import Any

import pandas as pd


def calculate_capital_with_reinvest(
    data_frame: pd.DataFrame,
    initial_investment: int = 10000,
    monthly_investment: int = 0,
    yearly_investment: int = 0,
    price_col: str = "CLOSE",
    dividend_col: str = "DIVIDEND",
    ticker: str | None = None,
) -> pd.DataFrame:
    data_frame = data_frame.copy()
    if data_frame.empty:
        raise ValueError("Cannot calculate capital for an empty dataset.")
    if price_col not in data_frame:
        raise ValueError(f"Missing price column: {price_col}")

    data_frame["TRADEDATE"] = pd.to_datetime(data_frame["TRADEDATE"])
    data_frame = data_frame.sort_values("TRADEDATE").reset_index(drop=True)
    data_frame[price_col] = pd.to_numeric(data_frame[price_col], errors="coerce")
    data_frame = data_frame.dropna(subset=[price_col])
    if data_frame.empty or data_frame[price_col].iloc[0] <= 0:
        raise ValueError("Dataset has no positive starting price.")

    if ticker is not None and "EVENT_TYPE" in data_frame.columns:
        split_rows = data_frame[
            data_frame["EVENT_TYPE"].astype(str).str.contains(ticker, na=False)
            & data_frame["EVENT_TYPE"].astype(str).str.contains("Split", case=False, na=False)
        ]
        for idx, row in split_rows.iterrows():
            match = re.search(r"(\d+):(\d+)", str(row["EVENT_NAME"]))
            if not match:
                continue
            old_shares = int(match.group(1))
            new_shares = int(match.group(2))
            if new_shares:
                data_frame.loc[idx:, price_col] /= old_shares / new_shares

    first_price = float(data_frame[price_col].iloc[0])
    shares = initial_investment / first_price
    cash_buffer = 0.0
    data_frame["shares"] = 0.0
    data_frame["cash_buffer"] = 0.0
    data_frame["savings"] = 0.0
    data_frame["CAPITAL_REINVEST"] = 0.0
    data_frame.at[0, "shares"] = shares
    data_frame.at[0, "savings"] = initial_investment
    current_month = data_frame.loc[0, "TRADEDATE"].month
    current_year = data_frame.loc[0, "TRADEDATE"].year

    for idx in range(1, len(data_frame)):
        row = data_frame.loc[idx]
        previous = data_frame.loc[idx - 1]
        date = row["TRADEDATE"]
        price = float(row[price_col])
        dividend = float(row.get(dividend_col, 0.0) or 0.0)
        shares = float(previous["shares"])
        cash_buffer = float(previous["cash_buffer"])

        if cash_buffer > 0:
            shares += cash_buffer / price
            cash_buffer = 0.0
        if dividend > 0:
            cash_buffer += dividend * shares

        savings_add = 0.0
        if monthly_investment > 0 and date.month != current_month:
            shares += monthly_investment / price
            savings_add += monthly_investment
            current_month = date.month
        if yearly_investment > 0 and date.year != current_year:
            shares += yearly_investment / price
            savings_add += yearly_investment
            current_year = date.year

        data_frame.loc[idx, "savings"] = previous["savings"] + savings_add
        data_frame.loc[idx, "shares"] = shares
        data_frame.loc[idx, "cash_buffer"] = cash_buffer

    data_frame["CAPITAL_REINVEST"] = data_frame["shares"] * data_frame[price_col]
    return data_frame


def generate_unique_colors(n: int, palette_name: str = "tab10") -> list[str]:
    if n <= 0:
        return []
    palette = [
        "#FFD166",
        "#00D1B2",
        "#5B8CFF",
        "#EF476F",
        "#B36BFF",
        "#FF8A3D",
        "#2EC4B6",
        "#E9C46A",
        "#4D96FF",
        "#FF6B6B",
        "#7BD88F",
        "#C77DFF",
        "#F4A261",
        "#48CAE4",
        "#F72585",
        "#A3E635",
    ]
    colors = palette.copy()

    if n > len(colors):
        import matplotlib.pyplot as plt

        cmap = plt.get_cmap(palette_name)
        generated = ["#%02x%02x%02x" % tuple(int(channel * 255) for channel in cmap(i % cmap.N)[:3]) for i in range(n - len(colors))]
        colors.extend(generated)

    random.SystemRandom().shuffle(colors)
    return colors[:n]


def prepare_dataset(
    ticker: str,
    engine: str,
    market: str,
    start_date,
    end_date,
    initial_investment: int = 10000,
    monthly_investment: int = 0,
    yearly_investment: int = 0,
) -> pd.DataFrame:
    from stock_prices._internal.lib.file_utils import load_latest_parquet, load_ticker_df

    parquet_path = load_latest_parquet(engine, market, ticker)
    df_raw = load_ticker_df(parquet_path, start_date, end_date)
    return calculate_capital_with_reinvest(
        df_raw,
        initial_investment=initial_investment,
        monthly_investment=monthly_investment,
        yearly_investment=yearly_investment,
        ticker=ticker,
    )


def build_data_list(args: Any, build_args: Any, start_date, end_date) -> list[dict[str, Any]]:
    tickers = list(getattr(build_args, "ticker", []))
    engines = list(getattr(build_args, "engine", []))
    markets = list(getattr(build_args, "market", []))
    if not tickers or not engines or not markets:
        raise ValueError("Ticker, engine and market are required.")
    if not (len(tickers) == len(engines) == len(markets)):
        raise ValueError("Each ticker must have a matching engine and market.")

    colors = generate_unique_colors(len(tickers))
    data_list: list[dict[str, Any]] = []
    investments_df = None

    for ticker, engine, market, color in zip(tickers, engines, markets, colors):
        try:
            df_raw = prepare_dataset(
                ticker,
                engine,
                market,
                start_date,
                end_date,
                getattr(args, "initial_investment", 10000),
                getattr(args, "monthly_investment", 0),
                getattr(args, "yearly_investment", 0),
            )
        except Exception:
            logging.exception("Failed to prepare dataset for %s", ticker)
            continue

        data_list.append({"data": df_raw, "name": ticker, "color": color})
        if getattr(args, "with_investments", False) and investments_df is None:
            investments_df = df_raw[["TRADEDATE", "savings"]].copy()
            investments_df.rename(columns={"savings": "CAPITAL_REINVEST"}, inplace=True)

    if investments_df is not None:
        data_list.append({"data": investments_df, "name": "Invested", "color": "#8f9aa8"})
    if not data_list:
        raise ValueError("No datasets were prepared.")
    return data_list
