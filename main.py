from lib.downloader import download_all
from lib.graph import render_charts


def parse_ticker_spec(spec: str):
    parts = spec.split("|")
    if len(parts) != 3:
        raise ValueError(
            f"Invalid ticker format '{spec}'. Expected: TICKER|ENGINE|MARKET"
        )
    return {"ticker": parts[0], "engine": parts[1], "market": parts[2]}


def parse_args():
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser(description="Universal downloader + chart builder")

    parser.add_argument(
        "--tickers",
        nargs="*",
        required=True,
        help="Ticker specifications: TICKER|ENGINE|MARKET",
    )
    parser.add_argument(
        "--ticker_file", help="File containing ticker specifications (one per line)"
    )

    parser.add_argument(
        "--start_date",
        required=True,
        type=lambda d: datetime.strptime(d, "%Y-%m-%d"),
    )
    parser.add_argument(
        "--end_date",
        required=True,
        type=lambda d: datetime.strptime(d, "%Y-%m-%d"),
    )

    parser.add_argument("--with_investments", action="store_true")
    parser.add_argument("--use_gradient", action="store_true")
    parser.add_argument(
        "--initial_investment",
        type=int,
        default=10000,
        help="Initial investment amount",
    )
    parser.add_argument(
        "--monthly_investment", type=int, default=0, help="Monthly investment amount"
    )
    parser.add_argument(
        "--yearly_investment", type=int, default=0, help="Yearly investment amount"
    )

    parser.add_argument("--value_col", default="CAPITAL_REINVEST")
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--no_legend", action="store_true")
    parser.add_argument("--currency", default="$")
    parser.add_argument("--title", default="")
    parser.add_argument("--under_title", default="")

    return parser.parse_args()


def main():
    import logging
    import pandas as pd

    args = parse_args()
    specs = []

    if args.tickers:
        for t in args.tickers:
            specs.append(parse_ticker_spec(t))
    if args.ticker_file:
        with open(args.ticker_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    specs.append(parse_ticker_spec(line.strip()))
    if not specs:
        raise ValueError("No tickers provided")
    start_date = pd.Timestamp(args.start_date).normalize()
    end_date = pd.Timestamp(args.end_date).normalize()
    logging.info(f"Processing {len(specs)} instruments")
    logging.info(f"Date range: {start_date.date()} -> {end_date.date()}")
    download_all(specs, start_date, end_date, args.currency)
    render_charts(args, specs, start_date, end_date)
    logging.info("DONE.")


if __name__ == "__main__":
    from lib.helpers import configure_logging

    configure_logging()
    main()
