from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from stock_prices._internal.lib.plotting import create_multi_line_animation


def _sample_data(ticker_count: int, row_count: int) -> list[dict[str, object]]:
    dates = pd.date_range("2014-01-01", periods=row_count, freq="B")
    data_list: list[dict[str, object]] = []
    palette = ["#FFD166", "#00D1B2", "#5B8CFF", "#EF476F", "#B36BFF"]
    for index in range(ticker_count):
        prices = 100 + index * 15 + pd.Series(range(row_count), dtype=float).rolling(18, min_periods=1).mean()
        data = pd.DataFrame(
            {
                "TRADEDATE": dates,
                "CLOSE": prices,
                "CAPITAL_REINVEST": prices * 100,
                "DIVIDEND": 0.0,
                "savings": 10_000.0,
            }
        )
        data_list.append({"data": data, "name": f"T{index + 1}", "color": palette[index % len(palette)]})
    return data_list


def main() -> int:
    parser = argparse.ArgumentParser(description="Render benchmark for the Matplotlib animation pipeline.")
    parser.add_argument("--tickers", type=int, default=3)
    parser.add_argument("--rows", type=int, default=1500)
    parser.add_argument("--duration", type=int, default=3)
    parser.add_argument("--fps", type=int, default=10)
    args = parser.parse_args()

    started_at = time.perf_counter()
    animation = create_multi_line_animation(
        _sample_data(args.tickers, args.rows),
        value_column="CAPITAL_REINVEST",
        y_label="RUB",
        target_duration=args.duration,
        fps=args.fps,
        final_frame_duration=0,
        title="Benchmark",
        under_title="Synthetic render",
    )
    elapsed = time.perf_counter() - started_at
    print(f"prepared animation in {elapsed:.3f}s")
    Path("animations").mkdir(exist_ok=True)
    animation._init_draw()
    animation._draw_next_frame(0, blit=False)
    animation._draw_was_started = True
    animation._fig.savefig(Path("animations") / "benchmark-frame.png")
    import matplotlib.pyplot as plt

    plt.close(animation._fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
