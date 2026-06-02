from __future__ import annotations

import logging
import random
from typing import Any

import pandas as pd

from stock_prices._internal.portfolio.calculations import InvestmentPlan, calculate_capital_with_reinvest


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
    investment_plan: InvestmentPlan | None = None,
) -> pd.DataFrame:
    from stock_prices._internal.lib.file_utils import load_latest_parquet, load_ticker_df

    parquet_path = load_latest_parquet(engine, market, ticker)
    df_raw = load_ticker_df(parquet_path, start_date, end_date)
    return calculate_capital_with_reinvest(
        df_raw,
        initial_investment=initial_investment,
        monthly_investment=monthly_investment,
        yearly_investment=yearly_investment,
        investment_plan=investment_plan,
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
    investment_plan = InvestmentPlan.from_args(args)

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
                investment_plan,
            )
        except Exception:
            logging.exception("Failed to prepare dataset for %s", ticker)
            continue

        data_list.append({"data": df_raw, "name": ticker, "color": color})
        if getattr(args, "with_investments", False) and investments_df is None:
            investments_df = df_raw[["TRADEDATE", "savings"]].copy()
            investments_df["CAPITAL_REINVEST"] = investments_df["savings"]

    if investments_df is not None:
        data_list.append({"data": investments_df, "name": "Invested", "color": "#8f9aa8"})
    if not data_list:
        raise ValueError("No datasets were prepared.")
    return data_list
