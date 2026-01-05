"""
Модуль для построения графиков цен на акции
"""

import os
import pandas as pd
import matplotlib.animation as animation
from matplotlib.colors import LinearSegmentedColormap
import colorsys
from dataclasses import dataclass
import logging
from .dataset_builder import build_data_list


def create_another_color(base_color, hue_shift=0.15, lightness_factor=0.9):
    """
    Создает другой цвет на основе базового цвета путем смещения оттенка.

    Args:
        base_color: Базовый цвет
        hue_shift: Сдвиг оттенка
        lightness_factor: Множитель яркости

    Returns:
        Новый цвет в формате RGB
    """
    import matplotlib.colors as mcolors

    rgb = mcolors.to_rgb(base_color)
    hls = colorsys.rgb_to_hls(rgb[0], rgb[1], rgb[2])
    new_hue = (hls[0] + hue_shift) % 1.0
    new_lightness = hls[1] * lightness_factor
    new_hls = (new_hue, new_lightness, hls[2])
    return colorsys.hls_to_rgb(*new_hls)


def draw_gradient_line(ax, x_data, y_data, start_color, name, n_segments=50):
    """
    Рисует линию с плавным градиентным переходом цвета, оптимизировано для скорости.

    Args:
        ax: Объект оси matplotlib
        x_data: Данные по оси X
        y_data: Данные по оси Y
        start_color: Начальный цвет
        name: Имя для цветовой карты
        n_segments: Количество сегментов градиента

    Returns:
        Конечный цвет
    """
    end_color = create_another_color(start_color)
    colors = [start_color, end_color]
    color_map = LinearSegmentedColormap.from_list(name, colors, N=n_segments)
    segment_size = max(1, len(x_data) // n_segments)
    for j in range(0, len(x_data) - 1, segment_size):
        end_idx = min(j + segment_size + 1, len(x_data))
        segment_x = x_data.iloc[j:end_idx]
        segment_y = y_data.iloc[j:end_idx]
        progress = (j + segment_size / 2) / len(x_data)
        segment_color = color_map(progress)
        ax.plot(segment_x, segment_y, color=segment_color, linewidth=2.5, alpha=0.85)
    return end_color


def draw_event_zones_anim(ax, events_df, frame_date, used_positions_global):
    """
    Рисует зоны событий на анимации

    Args:
        ax: Объект оси matplotlib
        events_df: DataFrame с событиями
        frame_date: Текущая дата анимации
        used_positions_global: Список используемых позиций для надписей
    """
    import matplotlib.dates as mdates
    import numpy as np

    frame_num = mdates.date2num(frame_date)
    grouped = events_df.groupby("EVENT_NAME")

    min_y_gap = (ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.05

    for event_name, group in grouped:
        start = mdates.date2num(group["TRADEDATE"].min())
        end = mdates.date2num(group["TRADEDATE"].max())
        impact = group["EVENT_IMPACT"].iloc[0]
        event_duration = end - start
        extended_duration = event_duration * 1.5
        extended_end = start + extended_duration

        if frame_num < start:
            continue

        visible_end = min(frame_num, end)
        ax.axvspan(
            start,
            visible_end,
            alpha=0.12,
            color=event_color(impact),
            linewidth=0,
            zorder=1,
        )

        if start <= frame_num <= extended_end:
            base_y_pos = ax.get_ylim()[1] * 0.95
            y_pos = base_y_pos
            attempt = 0
            max_attempts = 20

            while attempt < max_attempts:
                conflict = any(
                    abs(y_pos - used) < min_y_gap for used in used_positions_global
                )
                if not conflict:
                    break
                offset = min_y_gap * (attempt + 1) * 0.8
                if attempt % 2 == 0:
                    y_pos = base_y_pos - offset
                else:
                    y_pos = base_y_pos + offset

                ylim_bottom, ylim_top = ax.get_ylim()
                y_pos = np.clip(y_pos, ylim_bottom * 1.05, ylim_top * 0.98)

                attempt += 1

            used_positions_global.append(y_pos)

            ax.text(
                start,
                y_pos,
                event_name.replace("_", " "),
                fontsize=11,
                color="white",
                va="top",
                ha="left",
                alpha=0.9,
                zorder=100,
                bbox=dict(facecolor="black", alpha=0.5, edgecolor="none", pad=2),
            )


def event_color(impact):
    """
    Возвращает цвет для события в зависимости от его воздействия

    Args:
        impact: Воздействие события

    Returns:
        Цвет в формате RGBA
    """
    if impact == -3:
        return "#FF0000AA"
    if impact == -2:
        return "#FF8800AA"
    if impact == -1:
        return "#FFF000AA"
    if impact == 1:
        return "#00BFFF88"
    if impact == 2:
        return "#00FF0088"
    return "#88888855"


def wrap_text(text, width):
    """
    Обертывает текст по заданной ширине

    Args:
        text: Текст для оборачивания
        width: Ширина строки

    Returns:
        Обернутый текст
    """
    import textwrap

    return "\n".join(textwrap.wrap(text, width=width))


def create_multi_line_animation(
    data_list,
    value_column="CLOSE",
    y_label="Цена",
    target_duration=20,
    fps=20,
    use_gradient=True,
    final_frame_duration=3,
    use_legend=True,
    title="",
    under_title="",
):
    """
    Создает анимацию с несколькими линиями и стоп-кадром в конце.

    Parameters:
    data_list: список словарей с данными, именами и цветами
               [{"data": df, "name": "GAZP", "color": "#f3cd2c"}]
    value_column: название столбца для визуализации
    y_label: подпись оси Y
    target_duration: длительность основной анимации в секундах
    fps: частота кадров
    use_gradient: включать градиентное изменение цвета линий
    final_frame_duration: длительность стоп-кадра в секундах
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    combined_df = None
    for item in data_list:
        df_temp = item["data"].copy()
        df_temp[item["name"]] = df_temp[value_column]
        df_temp[f"DIVIDEND_{item['name']}"] = df_temp.get("DIVIDEND", 0.0)
        cols_to_merge = ["TRADEDATE", item["name"], f"DIVIDEND_{item['name']}"]
        if combined_df is None:
            combined_df = df_temp[cols_to_merge].copy()
        else:
            combined_df = combined_df.merge(
                df_temp[cols_to_merge], on="TRADEDATE", how="outer"
            )
    combined_df = combined_df.sort_values("TRADEDATE").reset_index(drop=True)
    combined_df = combined_df.ffill().fillna(
        {col: 0 for col in combined_df if col.startswith("DIVIDEND")}
    )
    total_frames = target_duration * fps
    sampling_step = max(1, len(combined_df) // total_frames)
    animation_frames = list(range(0, len(combined_df), sampling_step))
    final_frames_count = final_frame_duration * fps
    final_frame_index = len(combined_df) - 1
    all_frames = animation_frames + [final_frame_index] * final_frames_count
    plt.rcParams["figure.facecolor"] = "#0d0d0e"
    plt.rcParams["axes.facecolor"] = "#171b26"
    fig, ax = plt.subplots(figsize=(9, 16))
    ax.set_position((0.125, 0.25, 0.75, 0.5))
    global used_positions_global
    used_positions_global = []

    def animate(i):
        frame_index = final_frame_index if i >= len(animation_frames) else all_frames[i]
        current_data = (
            combined_df.iloc[: frame_index + 1]
            if combined_df is not None
            else pd.DataFrame()
        )

        ax.clear()
        ax.text(
            0.5,
            1.15,
            wrap_text(title, width=30),
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            fontsize=35,
            color="#fde164",
        )

        ax.text(
            0.5,
            -0.15,
            wrap_text(under_title, width=30),
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=25,
            color="#887937",
        )
        ax.grid(True, alpha=0.2, color="#848892")
        ax.set_ylabel(y_label, color="#848892", fontsize=15)
        ax.tick_params(
            axis="both", labelcolor="#848892", labelsize=12, colors="#848892"
        )
        if len(current_data) > 0 and len(data_list) > 0:
            frame_date = current_data["TRADEDATE"].iloc[-1]
            draw_event_zones_anim(
                ax, data_list[0]["data"], frame_date, used_positions_global
            )
        for item in data_list:
            name = item["name"]
            dividend_col = f"DIVIDEND_{name}"

            if name not in current_data.columns:
                continue

            x_data = current_data["TRADEDATE"]
            y_data = current_data[name]
            clean_y = y_data.dropna()
            if clean_y.empty:
                continue
            line = ax.plot(
                x_data,
                y_data,
                color=item["color"],
                linewidth=2.5,
                label=name,
                alpha=0.85,
            )
            end_color = None
            if use_gradient:
                end_color = draw_gradient_line(ax, x_data, y_data, item["color"], name)
            if dividend_col in current_data.columns:
                dividend_data = current_data[current_data[dividend_col] > 0]
                for _, row_div in dividend_data.iterrows():
                    y_val = row_div[name]
                    ax.scatter(
                        row_div["TRADEDATE"],
                        y_val,
                        s=100,
                        color=item["color"],
                        zorder=5,
                        alpha=0.6,
                    )
                    ax.text(
                        row_div["TRADEDATE"],
                        y_val,
                        "D",
                        color="white",
                        fontsize=10,
                        fontweight="bold",
                        ha="center",
                        va="center",
                        zorder=6,
                        alpha=0.2,
                    )
            last_y = y_data.dropna().iloc[-1]
            last_x = x_data[y_data.dropna().index[-1]]
            rounded_price = round(last_y / 10) * 10
            rounded_price = f"{name}: {rounded_price:,.0f}".replace(",", " ")
            last_x_num = mdates.date2num(last_x)
            xlim = ax.get_xlim()

            if last_x_num > xlim[1] - (xlim[1] - xlim[0]) * 0.05:
                ha = "right"
                x_pos = last_x - pd.Timedelta(days=(xlim[1] - xlim[0]) * 0.01)
            else:
                ha = "left"
                x_pos = last_x
            ax.text(
                x_pos,
                last_y,
                rounded_price,
                fontsize=15,
                color=end_color if end_color else item["color"],
                verticalalignment="bottom",
                horizontalalignment=ha,
                bbox=dict(
                    boxstyle="round,pad=0.4",
                    facecolor="#131314FF",
                    edgecolor=end_color if end_color else item["color"],
                ),
            )
        if combined_df is not None:
            price_cols = [col for col in current_data.columns if col != "TRADEDATE"]
            valid_prices = current_data[price_cols].stack().dropna()
            if not valid_prices.empty:
                price_min, price_max = valid_prices.min(), valid_prices.max()
                margin = max(
                    (price_max - price_min) * 0.05, 0.001 * (price_max - price_min)
                )
                ax.set_ylim(price_min - margin, price_max + margin)
        return ax.get_lines() + ax.texts + ax.patches

    return animation.FuncAnimation(
        fig, animate, frames=len(all_frames), interval=1000 / fps, repeat=False
    )


@dataclass
class BuildArgs:
    """
    Класс для хранения аргументов построения графиков
    """

    ticker: list
    engine: list
    market: list
    with_investments: bool


def render_charts(args, specs, start_date, end_date):
    """
    Основная функция отрисовки графиков

    Args:
        args: Аргументы командной строки
        specs: Спецификации тикеров
        start_date: Начальная дата
        end_date: Конечная дата
    """
    logging.info("Подготовка данных для отрисовки графиков...")

    build_args = BuildArgs(
        ticker=[x["ticker"] for x in specs],
        engine=[x["engine"] for x in specs],
        market=[x["market"] for x in specs],
        with_investments=args.with_investments,
    )

    logging.info(f"Тикеры: {build_args.ticker}")
    logging.info(f"Движки: {build_args.engine}")
    logging.info(f"Рынки: {build_args.market}")

    data_list = build_data_list(args, build_args, start_date, end_date)

    logging.info("Построение анимации...")
    anim = create_multi_line_animation(
        data_list,
        value_column=args.value_col,
        y_label=args.currency,
        target_duration=args.duration,
        fps=args.fps,
        use_gradient=args.use_gradient,
        final_frame_duration=6,
        use_legend=not args.no_legend,
        title=args.title,
        under_title=args.under_title,
    )

    os.makedirs("animations", exist_ok=True)
    safe_tickers = [ticker.replace(".", "_") for ticker in build_args.ticker]
    filename = "_".join(safe_tickers) + ".mp4"
    filepath = f"animations/{filename}"

    logging.info(f"Сохранение анимации в: {filepath}")
    anim.save(filepath, writer="ffmpeg", fps=args.fps, dpi=150)

    logging.info("Анимация успешно сохранена.")
