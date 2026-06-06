from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import matplotlib.animation as animation
import pandas as pd

from stock_prices._internal.lib.dataset_builder import build_data_list
from stock_prices._internal.models import TickerSpec
from stock_prices._internal.rendering.filenames import safe_video_stem
from stock_prices._internal.rendering.theme import ChartTheme, get_chart_theme


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


def _format_return(start: float, current: float) -> str:
    if start == 0:
        return "0.0%"
    percent = ((current / start) - 1) * 100
    if round(percent, 1) == 0:
        return "0.0%"
    return f"{percent:+.1f}%"


def _return_from_series(values: pd.Series, basis: pd.Series | None = None) -> str:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return "n/a"

    if basis is not None:
        basis_clean = pd.to_numeric(basis, errors="coerce").reindex(clean.index).dropna()
        positive_basis = basis_clean[basis_clean > 0]
        if not positive_basis.empty:
            last_index = positive_basis.index[-1]
            return _format_return(float(positive_basis.loc[last_index]), float(clean.loc[last_index]))

    non_zero = clean[clean != 0]
    if non_zero.empty:
        return "0.0%"
    return _format_return(float(non_zero.iloc[0]), float(clean.iloc[-1]))


def _amount_summary(name: str, values: pd.Series) -> str:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return f"{name}: n/a"
    return f"{name}: {_compact_number(float(clean.iloc[-1]))}"


def _return_summary(name: str, values: pd.Series, basis: pd.Series | None = None) -> str:
    if name == "Invested":
        return _amount_summary(name, values)
    return f"{name}: {_return_from_series(values, basis)}"


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


def _combine_data(data_list: list[dict[str, Any]], value_column: str) -> tuple[pd.DataFrame, list[str], dict[str, str], dict[str, str]]:
    combined_df: pd.DataFrame | None = None
    value_columns = []
    dividend_columns: dict[str, str] = {}
    basis_columns: dict[str, str] = {}
    valid_date_ranges: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    use_investment_basis = value_column == "CAPITAL_REINVEST"

    for item in data_list:
        name = item["name"]
        df_temp = item["data"].copy()
        if value_column not in df_temp:
            raise ValueError(f"{name} has no column {value_column}")
        df_temp["TRADEDATE"] = pd.to_datetime(df_temp["TRADEDATE"])
        valid_date_ranges[name] = (df_temp["TRADEDATE"].min(), df_temp["TRADEDATE"].max())
        df_temp[name] = pd.to_numeric(df_temp[value_column], errors="coerce")
        dividend_col = f"DIVIDEND_{name}"
        dividend_values = df_temp["DIVIDEND"] if "DIVIDEND" in df_temp else pd.Series(0.0, index=df_temp.index)
        df_temp[dividend_col] = pd.to_numeric(dividend_values, errors="coerce").fillna(0.0)
        columns = ["TRADEDATE", name, dividend_col]
        if use_investment_basis and "savings" in df_temp:
            basis_col = f"SAVINGS_{name}"
            df_temp[basis_col] = pd.to_numeric(df_temp["savings"], errors="coerce")
            columns.append(basis_col)
            basis_columns[name] = basis_col
        combined_df = df_temp[columns].copy() if combined_df is None else combined_df.merge(df_temp[columns], on="TRADEDATE", how="outer")
        value_columns.append(name)
        dividend_columns[name] = dividend_col

    if combined_df is None or combined_df.empty:
        raise ValueError("No data to render.")

    combined_df = combined_df.sort_values("TRADEDATE").reset_index(drop=True)
    combined_df[value_columns] = combined_df[value_columns].ffill()
    combined_df[list(dividend_columns.values())] = combined_df[list(dividend_columns.values())].fillna(0.0)
    if basis_columns:
        combined_df[list(basis_columns.values())] = combined_df[list(basis_columns.values())].ffill()
    for name, (_first_date, last_date) in valid_date_ranges.items():
        after_last = combined_df["TRADEDATE"] > last_date
        combined_df.loc[after_last, name] = float("nan")
        if name in basis_columns:
            combined_df.loc[after_last, basis_columns[name]] = float("nan")
    return combined_df, value_columns, dividend_columns, basis_columns


def _frame_indexes(row_count: int, target_duration: int, fps: int, final_frame_duration: int) -> list[int]:
    import numpy as np

    final_index = row_count - 1
    frame_count = max(1, int(target_duration * fps))
    animated = np.unique(np.linspace(0, final_index, num=frame_count, dtype=int)).tolist()
    return animated + [final_index] * max(0, int(final_frame_duration * fps))


def _prefix_y_limits(values: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    import numpy as np

    numeric_values = values.apply(pd.to_numeric, errors="coerce")
    matrix = numeric_values.to_numpy(dtype=float)
    row_count = len(numeric_values)
    row_min = np.full(row_count, np.nan)
    row_max = np.full(row_count, np.nan)

    if row_count:
        valid_rows = ~np.isnan(matrix).all(axis=1)
        if valid_rows.any():
            row_min[valid_rows] = np.nanmin(matrix[valid_rows], axis=1)
            row_max[valid_rows] = np.nanmax(matrix[valid_rows], axis=1)

    min_input = np.where(np.isnan(row_min), np.inf, row_min)
    max_input = np.where(np.isnan(row_max), -np.inf, row_max)
    prefix_min = np.minimum.accumulate(min_input)
    prefix_max = np.maximum.accumulate(max_input)
    prefix_min[prefix_min == np.inf] = np.nan
    prefix_max[prefix_max == -np.inf] = np.nan
    return pd.Series(prefix_min, index=values.index), pd.Series(prefix_max, index=values.index)


def _visible_x_span_days(x_start: pd.Timestamp, frame_date: pd.Timestamp, total_span_days: int) -> int:
    return max(1, total_span_days)


def _animation_frame_data(combined_df: pd.DataFrame, frame_index: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    current_data = combined_df.iloc[: frame_index + 1]
    line_data = combined_df
    return current_data, line_data


EventRange = tuple[pd.Timestamp, pd.Timestamp, str, int]


def _event_ranges(events_df: pd.DataFrame) -> list[EventRange]:
    if events_df.empty or "EVENT_NAME" not in events_df:
        return []
    events = events_df.dropna(subset=["EVENT_NAME"]).copy()
    if events.empty:
        return []
    events["TRADEDATE"] = pd.to_datetime(events["TRADEDATE"])
    if "EVENT_IMPACT" in events:
        events["EVENT_IMPACT"] = pd.to_numeric(events["EVENT_IMPACT"], errors="coerce").fillna(0).astype(int)
    else:
        events["EVENT_IMPACT"] = 0

    ranges = []
    for event_name, group in events.groupby("EVENT_NAME"):
        start = group["TRADEDATE"].min()
        end = group["TRADEDATE"].max()
        impact = int(group["EVENT_IMPACT"].iloc[0])
        ranges.append((start, end, str(event_name).replace("_", " "), impact))
    return ranges


def _active_event_ranges(event_ranges: list[EventRange], frame_date: pd.Timestamp) -> list[EventRange]:
    active = []
    for start, end, event_name, impact in event_ranges:
        if frame_date < start:
            continue
        visible_end = min(frame_date, end)
        active.append((start, visible_end, event_name, impact))
    return active


def _active_events(events_df: pd.DataFrame, frame_date: pd.Timestamp) -> list[EventRange]:
    return _active_event_ranges(_event_ranges(events_df), frame_date)


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
    theme: str | ChartTheme = "default",
):
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.ticker import FuncFormatter

    chart_theme = get_chart_theme(theme) if isinstance(theme, str) else theme
    combined_df, value_columns, dividend_columns, basis_columns = _combine_data(data_list, value_column)
    all_frames = _frame_indexes(len(combined_df), target_duration, fps, final_frame_duration)

    plt.rcParams["figure.facecolor"] = chart_theme.figure_bg
    plt.rcParams["axes.facecolor"] = chart_theme.axes_bg
    fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
    fig.subplots_adjust(left=0.12, right=0.86, top=0.76, bottom=0.24)
    x_start = combined_df["TRADEDATE"].min()
    x_end = combined_df["TRADEDATE"].max()
    x_span_days = max(1, (x_end - x_start).days)
    source_events = data_list[0]["data"] if data_list else pd.DataFrame()
    event_ranges = _event_ranges(source_events)
    ax.set_xlim(x_start, x_end + pd.Timedelta(days=x_span_days * 0.12))
    full_values = combined_df[value_columns].stack().dropna()
    if not full_values.empty:
        y_min = float(full_values.min())
        y_max = float(full_values.max())
        margin = max((y_max - y_min) * 0.12, abs(y_max) * 0.02, 1.0)
        ax.set_ylim(y_min - margin, y_max + margin)
    ax.grid(True, alpha=0.2, color=chart_theme.grid_color, linewidth=0.8)
    ax.set_ylabel(y_label, color=chart_theme.axis_color, fontsize=14)
    ax.tick_params(axis="both", labelcolor=chart_theme.axis_color, labelsize=11, colors=chart_theme.axis_color)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: _compact_number(value)))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=7))
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
    for spine in ax.spines.values():
        spine.set_color(chart_theme.spine_color)

    by_name = {item["name"]: item for item in data_list}
    summary_columns = min(max(len(value_columns), 1), 3)
    summary_x_positions = [0.08, 0.36, 0.64][:summary_columns]
    summary_font_size = 17 if len(value_columns) <= 4 else 13
    summary_wrap_width = 24
    summary_row_gap = 0.038

    fig.text(0.08, 0.955, "MARKET MOTION", ha="left", va="top", fontsize=10, color=chart_theme.muted_color, weight="bold")
    title_artist = fig.text(0.08, 0.925, wrap_text(title, 24), ha="left", va="top", fontsize=34, color=chart_theme.title_color, weight="bold")
    subtitle_artist = fig.text(0.08, 0.165, wrap_text(under_title, 40), ha="left", va="bottom", fontsize=16, color=chart_theme.subtitle_color)
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
    fig.text(0.92, 0.055, "stock-prices", ha="right", va="bottom", fontsize=10, color=chart_theme.footer_color)
    date_artist = ax.text(
        0.98,
        0.97,
        "",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=18,
        color=chart_theme.title_color,
        weight="bold",
        bbox={"boxstyle": "round,pad=0.35", "facecolor": chart_theme.date_box_bg, "edgecolor": chart_theme.date_box_edge, "alpha": 0.92},
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
            bbox={"boxstyle": "round,pad=0.35", "facecolor": chart_theme.label_box_bg, "edgecolor": color, "alpha": 0.92},
        )
        dividend_markers[name] = ax.scatter([], [], s=55, color=color, alpha=0.7, zorder=5)
    if use_legend:
        legend = ax.legend(loc="upper left", frameon=False, fontsize=12)
        for text in legend.get_texts():
            text.set_color(chart_theme.title_color)

    event_artists = []
    last_frame_index: int | None = None
    last_artists: list[Any] | None = None

    def clear_transient_artists() -> None:
        while event_artists:
            event_artists.pop().remove()
        while gradient_collections:
            gradient_collections.pop().remove()
        while fill_artists:
            fill_artists.pop().remove()

    def animate(frame_number: int):
        nonlocal last_frame_index, last_artists
        frame_index = all_frames[frame_number]
        if frame_index == last_frame_index and last_artists is not None:
            return last_artists

        clear_transient_artists()
        current_data, line_data = _animation_frame_data(combined_df, frame_index)
        frame_date = pd.Timestamp(current_data["TRADEDATE"].iloc[-1])
        date_artist.set_text(frame_date.strftime("%d.%m.%Y"))
        visible_x_span_days = _visible_x_span_days(x_start, frame_date, x_span_days)
        ax.set_xlim(x_start, x_start + pd.Timedelta(days=visible_x_span_days * 1.12))

        label_targets: list[tuple[str, pd.Timestamp, float, str]] = []
        for name in value_columns:
            line_x_data = line_data["TRADEDATE"]
            line_y_data = line_data[name]
            line_clean = line_y_data.dropna()
            current_x_data = current_data["TRADEDATE"]
            current_clean = current_data[name].dropna()
            if line_clean.empty or current_clean.empty:
                labels[name].set_text("")
                summary_artists[name].set_text("")
                continue
            line_x = line_x_data.loc[line_clean.index]
            current_line_x = current_x_data.loc[current_clean.index]
            if use_gradient:
                lines[name].set_data(line_x, line_clean)
                lines[name].set_alpha(0.42)
                gradient_tail_points = 180
                tail_x = current_line_x.iloc[-gradient_tail_points:]
                tail_y = current_clean.iloc[-gradient_tail_points:]
                before = len(ax.collections)
                draw_gradient_line(ax, tail_x, tail_y, by_name[name]["color"], name)
                gradient_collections.extend(ax.collections[before:])
            else:
                lines[name].set_alpha(0.92)
                lines[name].set_data(line_x, line_clean)
            if len(line_clean) > 1:
                fill_artists.append(
                    ax.fill_between(
                        line_x,
                        line_clean,
                        ax.get_ylim()[0],
                        color=by_name[name]["color"],
                        alpha=0.045,
                        linewidth=0,
                    )
                )

            last_idx = current_clean.index[-1]
            last_x = current_x_data.loc[last_idx]
            last_y = float(current_clean.iloc[-1])
            basis = current_data[basis_columns[name]] if name in basis_columns else None
            label_text = _amount_summary(name, current_clean)
            labels[name].set_text(label_text)
            label_targets.append((name, last_x, last_y, label_text))
            summary_artists[name].set_text(wrap_text(_return_summary(name, current_clean, basis), summary_wrap_width))

            dividend_data = current_data[current_data[dividend_columns[name]] > 0]
            if dividend_data.empty:
                dividend_markers[name].set_offsets(np.empty((0, 2)))
            else:
                offsets = np.column_stack([mdates.date2num(dividend_data["TRADEDATE"]), dividend_data[name]])
                dividend_markers[name].set_offsets(offsets)

        y_bottom, y_top = ax.get_ylim()
        min_gap = (y_top - y_bottom) * 0.065
        used_y: list[float] = []
        label_x = frame_date + pd.Timedelta(days=visible_x_span_days * 0.105)
        for name, _last_x, last_y, _label_text in sorted(label_targets, key=lambda item: item[2]):
            adjusted_y = min(max(last_y, y_bottom + min_gap), y_top - min_gap)
            while any(abs(adjusted_y - used) < min_gap for used in used_y):
                adjusted_y += min_gap
                if adjusted_y > y_top - min_gap:
                    adjusted_y = max(y_bottom + min_gap, last_y - min_gap)
                    break
            used_y.append(adjusted_y)
            labels[name].set_position((label_x, adjusted_y))
        for event_index, (start, visible_end, event_name, impact) in enumerate(_active_event_ranges(event_ranges, frame_date)):
            color = event_color(impact)
            patch = ax.axvspan(start, visible_end, alpha=0.12, color=color, linewidth=0, zorder=0)
            label_x = start + (visible_end - start) / 2
            label_padding = pd.Timedelta(days=visible_x_span_days * 0.045)
            x_right = x_start + pd.Timedelta(days=visible_x_span_days)
            label_x = max(x_start + label_padding, min(label_x, x_right - label_padding))
            label = ax.text(
                label_x,
                0.035 + (event_index % 3) * 0.048,
                wrap_text(event_name, 18),
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="bottom",
                fontsize=9,
                color=chart_theme.title_color,
                bbox={"boxstyle": "round,pad=0.28", "facecolor": chart_theme.date_box_bg, "edgecolor": color, "alpha": 0.88},
                clip_on=True,
                zorder=6,
            )
            event_artists.extend([patch, label])

        artists = [
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
        last_frame_index = frame_index
        last_artists = artists
        return artists

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
        theme=getattr(args, "theme", "default"),
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
