from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from stock_prices._internal.lib.plotting import create_multi_line_animation


def _sample_data(ticker_count: int, row_count: int, include_events: bool = False) -> list[dict[str, object]]:
    dates = pd.date_range("2014-01-01", periods=row_count, freq="B")
    data_list: list[dict[str, object]] = []
    palette = ["#FFD166", "#00D1B2", "#5B8CFF", "#EF476F", "#B36BFF"]
    for index in range(ticker_count):
        prices = 100 + index * 15 + pd.Series(range(row_count), dtype=float).rolling(18, min_periods=1).mean()
        data_values: dict[str, object] = {
            "TRADEDATE": dates,
            "CLOSE": prices,
            "CAPITAL_REINVEST": prices * 100,
            "DIVIDEND": 0.0,
            "savings": 10_000.0,
        }
        if include_events and index == 0:
            event_names = [None] * row_count
            event_impacts = [0] * row_count
            for event_index, event_name in enumerate(("OIL_DROP", "FOMC_EASING", "RISK_ON"), start=1):
                start = min(row_count - 1, event_index * row_count // 5)
                end = min(row_count, start + max(5, row_count // 20))
                event_names[start:end] = [event_name] * (end - start)
                event_impacts[start:end] = [event_index - 2] * (end - start)
            data_values["EVENT_NAME"] = event_names
            data_values["EVENT_IMPACT"] = event_impacts
        data = pd.DataFrame(data_values)
        data_list.append({"data": data, "name": f"T{index + 1}", "color": palette[index % len(palette)]})
    return data_list


def main() -> int:
    parser = argparse.ArgumentParser(description="Render benchmark for the Matplotlib animation pipeline.")
    parser.add_argument("--tickers", type=int, default=3)
    parser.add_argument("--rows", type=int, default=1500)
    parser.add_argument("--duration", type=int, default=3)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--final-frame-duration", type=int, default=0)
    parser.add_argument("--draw-frames", type=int, default=1)
    parser.add_argument("--gradient", action="store_true")
    parser.add_argument("--events", action="store_true")
    args = parser.parse_args()

    started_at = time.perf_counter()
    chart_animation = create_multi_line_animation(
        _sample_data(args.tickers, args.rows, include_events=args.events),
        value_column="CAPITAL_REINVEST",
        y_label="RUB",
        target_duration=args.duration,
        fps=args.fps,
        final_frame_duration=args.final_frame_duration,
        use_gradient=args.gradient,
        title="Benchmark",
        under_title="Synthetic render",
    )
    elapsed = time.perf_counter() - started_at
    print(f"prepared animation in {elapsed:.3f}s")
    Path("animations").mkdir(exist_ok=True)
    total_frames = max(1, args.duration * args.fps) + max(0, args.final_frame_duration * args.fps)
    draw_frames = max(1, min(args.draw_frames, total_frames))
    started_at = time.perf_counter()
    chart_animation._init_draw()
    for frame_number in range(draw_frames):
        chart_animation._draw_next_frame(frame_number, blit=False)
    chart_animation._draw_was_started = True
    draw_elapsed = time.perf_counter() - started_at
    print(f"drew {draw_frames} frame(s) in {draw_elapsed:.3f}s")
    chart_animation._fig.savefig(Path("animations") / "benchmark-frame.png")
    import matplotlib.pyplot as plt

    plt.close(chart_animation._fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
