from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import matplotlib.animation as animation
import pandas as pd

from stock_prices._internal.lib.dataset_builder import build_data_list
from stock_prices._internal.models import TickerSpec, safe_video_stem


def event_color(impact: int) -> str:
    if impact <= -3:
        return "#d94848"
    if impact == -2:
        return "#e58b3a"
    if impact == -1:
        return "#d7b948"
    if impact == 1:
        return "#4d9fd7"
    if impact >= 2:
        return "#58b368"
    return "#8f9aa8"


def wrap_text(text: str, width: int) -> str:
    import textwrap

    return "\n".join(textwrap.wrap(text or "", width=width))


def _compact_number(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def _series_summary(name: str, values: pd.Series) -> str:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return f"{name}: n/a"
    return f"{name}: {_compact_number(float(clean.iloc[-1]))}"


def create_another_color(base_color: str, hue_shift: float = 0.08, lightness_factor: float = 1.12) -> tuple[float, float, float]:
    import colorsys
    import matplotlib.colors as mcolors

    red, green, blue = mcolors.to_rgb(base_color)
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    return colorsys.hls_to_rgb((hue + hue_shift) % 1.0, min(lightness * lightness_factor, 1), saturation)


def draw_gradient_line(ax, x_data, y_data, start_color: str, name: str, n_segments: int = 50):
    from matplotlib.collections import LineCollection
    from matplotlib.colors import LinearSegmentedColormap
    import matplotlib.dates as mdates
    import numpy as np

    if len(x_data) < 2:
        return create_another_color(start_color)
    end_color = create_another_color(start_color)
    color_map = LinearSegmentedColormap.from_list(name, [start_color, end_color], N=n_segments)
    x_num = mdates.date2num(pd.to_datetime(x_data))
    points = np.array([x_num, pd.to_numeric(y_data, errors="coerce")]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    collection = LineCollection(segments, cmap=color_map, linewidth=2.8, alpha=0.9)
    collection.set_array(np.linspace(0, 1, len(segments)))
    ax.add_collection(collection)
    return end_color


def _configure_ffmpeg() -> None:
    import matplotlib as mpl
    from imageio_ffmpeg import get_ffmpeg_exe

    mpl.rcParams["animation.ffmpeg_path"] = get_ffmpeg_exe()


def _combine_data(data_list: list[dict[str, Any]], value_column: str) -> tuple[pd.DataFrame, list[str], dict[str, str]]:
    combined_df: pd.DataFrame | None = None
    value_columns = []
    dividend_columns: dict[str, str] = {}

    for item in data_list:
        name = item["name"]
        df_temp = item["data"].copy()
        if value_column not in df_temp:
            raise ValueError(f"{name} has no column {value_column}")
        df_temp["TRADEDATE"] = pd.to_datetime(df_temp["TRADEDATE"])
        df_temp[name] = pd.to_numeric(df_temp[value_column], errors="coerce")
        dividend_col = f"DIVIDEND_{name}"
        dividend_values = df_temp["DIVIDEND"] if "DIVIDEND" in df_temp else pd.Series(0.0, index=df_temp.index)
        df_temp[dividend_col] = pd.to_numeric(dividend_values, errors="coerce").fillna(0.0)
        columns = ["TRADEDATE", name, dividend_col]
        combined_df = df_temp[columns].copy() if combined_df is None else combined_df.merge(df_temp[columns], on="TRADEDATE", how="outer")
        value_columns.append(name)
        dividend_columns[name] = dividend_col

    if combined_df is None or combined_df.empty:
        raise ValueError("No data to render.")

    combined_df = combined_df.sort_values("TRADEDATE").reset_index(drop=True)
    combined_df[value_columns] = combined_df[value_columns].ffill()
    combined_df[list(dividend_columns.values())] = combined_df[list(dividend_columns.values())].fillna(0.0)
    return combined_df, value_columns, dividend_columns


def _frame_indexes(row_count: int, target_duration: int, fps: int, final_frame_duration: int) -> list[int]:
    import numpy as np

    final_index = row_count - 1
    frame_count = max(1, int(target_duration * fps))
    animated = np.unique(np.linspace(0, final_index, num=frame_count, dtype=int)).tolist()
    return animated + [final_index] * max(0, int(final_frame_duration * fps))


def _active_events(events_df: pd.DataFrame, frame_date: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp, str, int]]:
    if events_df.empty or "EVENT_NAME" not in events_df:
        return []
    events = events_df.dropna(subset=["EVENT_NAME"]).copy()
    if events.empty:
        return []
    events["TRADEDATE"] = pd.to_datetime(events["TRADEDATE"])

    active = []
    for event_name, group in events.groupby("EVENT_NAME"):
        start = group["TRADEDATE"].min()
        end = group["TRADEDATE"].max()
        if frame_date < start:
            continue
        visible_end = min(frame_date, end)
        impact = int(group["EVENT_IMPACT"].iloc[0])
        active.append((start, visible_end, str(event_name).replace("_", " "), impact))
    return active


def create_multi_line_animation(
    data_list: list[dict[str, Any]],
    value_column: str = "CLOSE",
    y_label: str = "Price",
    target_duration: int = 20,
    fps: int = 20,
    use_gradient: bool = False,
    final_frame_duration: int = 3,
    use_legend: bool = True,
    title: str = "",
    under_title: str = "",
):
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.ticker import FuncFormatter

    combined_df, value_columns, dividend_columns = _combine_data(data_list, value_column)
    all_frames = _frame_indexes(len(combined_df), target_duration, fps, final_frame_duration)

    plt.rcParams["figure.facecolor"] = "#0D0E11"
    plt.rcParams["axes.facecolor"] = "#15171C"
    fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
    fig.subplots_adjust(left=0.12, right=0.86, top=0.76, bottom=0.24)
    x_start = combined_df["TRADEDATE"].min()
    x_end = combined_df["TRADEDATE"].max()
    x_span_days = max(1, (x_end - x_start).days)
    ax.set_xlim(x_start, x_end + pd.Timedelta(days=x_span_days * 0.12))
    ax.grid(True, alpha=0.2, color="#B6BCC6", linewidth=0.8)
    ax.set_ylabel(y_label, color="#B6BCC6", fontsize=14)
    ax.tick_params(axis="both", labelcolor="#B6BCC6", labelsize=11, colors="#B6BCC6")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: _compact_number(value)))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=7))
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
    for spine in ax.spines.values():
        spine.set_color("#343942")

    by_name = {item["name"]: item for item in data_list}
    summary_columns = min(max(len(value_columns), 1), 3)
    summary_x_positions = [0.08, 0.36, 0.64][:summary_columns]
    summary_font_size = 17 if len(value_columns) <= 4 else 13
    summary_wrap_width = 24
    summary_row_gap = 0.038

    fig.text(0.08, 0.955, "MARKET MOTION", ha="left", va="top", fontsize=10, color="#858B96", weight="bold")
    title_artist = fig.text(0.08, 0.925, wrap_text(title, 24), ha="left", va="top", fontsize=34, color="#f8fafc", weight="bold")
    subtitle_artist = fig.text(0.08, 0.165, wrap_text(under_title, 40), ha="left", va="bottom", fontsize=16, color="#A2A9B3")
    summary_artists = {
        name: fig.text(
            summary_x_positions[index % summary_columns],
            0.135 - (index // summary_columns) * summary_row_gap,
            "",
            ha="left",
            va="top",
            fontsize=summary_font_size,
            color=by_name[name]["color"],
            weight="bold",
            linespacing=1.2,
        )
        for index, name in enumerate(value_columns)
    }
    fig.text(0.92, 0.055, "stock-prices", ha="right", va="bottom", fontsize=10, color="#595F6B")
    date_artist = ax.text(
        0.98,
        0.97,
        "",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=18,
        color="#f8fafc",
        weight="bold",
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "#0D0E11", "edgecolor": "#343942", "alpha": 0.92},
    )

    lines = {}
    labels = {}
    dividend_markers = {}
    gradient_collections = []
    fill_artists = []
    for name in value_columns:
        color = by_name[name]["color"]
        (line,) = ax.plot([], [], color=color, linewidth=3.0, alpha=0.92, label=name, solid_capstyle="round")
        lines[name] = line
        labels[name] = ax.text(
            combined_df["TRADEDATE"].iloc[0],
            0,
            "",
            fontsize=14,
            color=color,
            va="center",
            ha="right",
            bbox={"boxstyle": "round,pad=0.35", "facecolor": "#10131a", "edgecolor": color, "alpha": 0.92},
        )
        dividend_markers[name] = ax.scatter([], [], s=55, color=color, alpha=0.7, zorder=5)
    if use_legend:
        legend = ax.legend(loc="upper left", frameon=False, fontsize=12)
        for text in legend.get_texts():
            text.set_color("#d6dce6")

    event_artists = []

    def clear_transient_artists() -> None:
        while event_artists:
            event_artists.pop().remove()
        while gradient_collections:
            gradient_collections.pop().remove()
        while fill_artists:
            fill_artists.pop().remove()

    def animate(frame_number: int):
        clear_transient_artists()
        frame_index = all_frames[frame_number]
        current_data = combined_df.iloc[: frame_index + 1]
        frame_date = pd.Timestamp(current_data["TRADEDATE"].iloc[-1])
        date_artist.set_text(frame_date.strftime("%d.%m.%Y"))

        values = current_data[value_columns].stack().dropna()
        if not values.empty:
            y_min = float(values.min())
            y_max = float(values.max())
            margin = max((y_max - y_min) * 0.12, abs(y_max) * 0.02, 1.0)
            ax.set_ylim(y_min - margin, y_max + margin)

        label_targets: list[tuple[str, pd.Timestamp, float, str]] = []
        for name in value_columns:
            x_data = current_data["TRADEDATE"]
            y_data = current_data[name]
            clean = y_data.dropna()
            if clean.empty:
                labels[name].set_text("")
                summary_artists[name].set_text("")
                continue
            line_x = x_data.loc[clean.index]
            if use_gradient:
                lines[name].set_data(line_x, clean)
                lines[name].set_alpha(0.42)
                gradient_tail_points = 180
                tail_x = line_x.iloc[-gradient_tail_points:]
                tail_y = clean.iloc[-gradient_tail_points:]
                before = len(ax.collections)
                draw_gradient_line(ax, tail_x, tail_y, by_name[name]["color"], name)
                gradient_collections.extend(ax.collections[before:])
            else:
                lines[name].set_alpha(0.92)
                lines[name].set_data(line_x, clean)
            if len(clean) > 1:
                fill_artists.append(
                    ax.fill_between(
                        line_x,
                        clean,
                        ax.get_ylim()[0],
                        color=by_name[name]["color"],
                        alpha=0.045,
                        linewidth=0,
                    )
                )

            last_idx = clean.index[-1]
            last_x = x_data.loc[last_idx]
            last_y = float(clean.iloc[-1])
            label_text = _series_summary(name, clean)
            labels[name].set_text(label_text)
            label_targets.append((name, last_x, last_y, label_text))
            summary_artists[name].set_text(wrap_text(_series_summary(name, clean), summary_wrap_width))

            dividend_data = current_data[current_data[dividend_columns[name]] > 0]
            if dividend_data.empty:
                dividend_markers[name].set_offsets(np.empty((0, 2)))
            else:
                offsets = np.column_stack([mdates.date2num(dividend_data["TRADEDATE"]), dividend_data[name]])
                dividend_markers[name].set_offsets(offsets)

        y_bottom, y_top = ax.get_ylim()
        min_gap = (y_top - y_bottom) * 0.065
        used_y: list[float] = []
        label_x = combined_df["TRADEDATE"].iloc[-1] + pd.Timedelta(days=x_span_days * 0.105)
        for name, _last_x, last_y, _label_text in sorted(label_targets, key=lambda item: item[2]):
            adjusted_y = min(max(last_y, y_bottom + min_gap), y_top - min_gap)
            while any(abs(adjusted_y - used) < min_gap for used in used_y):
                adjusted_y += min_gap
                if adjusted_y > y_top - min_gap:
                    adjusted_y = max(y_bottom + min_gap, last_y - min_gap)
                    break
            used_y.append(adjusted_y)
            labels[name].set_position((label_x, adjusted_y))
        source_events = data_list[0]["data"] if data_list else pd.DataFrame()
        for event_index, (start, visible_end, event_name, impact) in enumerate(_active_events(source_events, frame_date)):
            color = event_color(impact)
            patch = ax.axvspan(start, visible_end, alpha=0.12, color=color, linewidth=0, zorder=0)
            label_x = start + (visible_end - start) / 2
            label_padding = pd.Timedelta(days=x_span_days * 0.045)
            label_x = max(x_start + label_padding, min(label_x, x_end - label_padding))
            label = ax.text(
                label_x,
                0.035 + (event_index % 3) * 0.048,
                wrap_text(event_name, 18),
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="bottom",
                fontsize=9,
                color="#eef2f6",
                bbox={"boxstyle": "round,pad=0.28", "facecolor": "#0D0E11", "edgecolor": color, "alpha": 0.88},
                clip_on=True,
                zorder=6,
            )
            event_artists.extend([patch, label])

        return [
            *fill_artists,
            *lines.values(),
            *labels.values(),
            *dividend_markers.values(),
            date_artist,
            title_artist,
            subtitle_artist,
            *summary_artists.values(),
            *event_artists,
        ]

    return animation.FuncAnimation(fig, animate, frames=len(all_frames), interval=1000 / fps, repeat=False, blit=False)


@dataclass
class BuildArgs:
    ticker: list[str]
    engine: list[str]
    market: list[str]
    with_investments: bool = False


def render_charts(args: Any, specs: list[dict[str, str]], start_date: pd.Timestamp, end_date: pd.Timestamp) -> Path:
    logging.info("Preparing chart datasets...")
    build_args = BuildArgs(
        ticker=[item["ticker"] for item in specs],
        engine=[item["engine"] for item in specs],
        market=[item["market"] for item in specs],
        with_investments=getattr(args, "with_investments", False),
    )
    data_list = build_data_list(args, build_args, start_date, end_date)
    default_title = " / ".join(build_args.ticker)
    default_subtitle = f"{start_date:%d.%m.%Y} - {end_date:%d.%m.%Y}"

    anim = create_multi_line_animation(
        data_list,
        value_column=getattr(args, "value_col", "CAPITAL_REINVEST"),
        y_label=getattr(args, "currency", ""),
        target_duration=getattr(args, "duration", 30),
        fps=getattr(args, "fps", 20),
        use_gradient=getattr(args, "use_gradient", False),
        final_frame_duration=4,
        use_legend=not getattr(args, "no_legend", False),
        title=getattr(args, "title", "") or default_title,
        under_title=getattr(args, "under_title", "") or default_subtitle,
    )

    output_dir = Path(getattr(args, "output_dir", "animations"))
    output_dir.mkdir(parents=True, exist_ok=True)
    ticker_specs = [TickerSpec(item["ticker"], item["engine"], item["market"]) for item in specs]
    filename = f"{safe_video_stem(ticker_specs)}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_{uuid4().hex[:8]}.mp4"
    filepath = output_dir / filename

    _configure_ffmpeg()
    writer = animation.FFMpegWriter(
        fps=getattr(args, "fps", 20),
        codec="libx264",
        bitrate=-1,
        extra_args=["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-preset", "veryfast", "-crf", "21"],
    )
    logging.info("Saving animation to %s", filepath)
    anim.save(filepath, writer=writer)
    import matplotlib.pyplot as plt

    plt.close(anim._fig)
    logging.info("Animation saved.")
    return filepath
