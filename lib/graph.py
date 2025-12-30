import os
import random
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.colors import LinearSegmentedColormap
import colorsys
from dataclasses import dataclass
from datetime import datetime
import logging


def create_another_color(base_color, hue_shift=0.15, lightness_factor=0.9):
    """Создает другой цвет на основе базового цвета путем смещения оттенка."""
    rgb = plt.cm.colors.to_rgb(base_color)
    hls = colorsys.rgb_to_hls(rgb[0], rgb[1], rgb[2])
    new_hue = (hls[0] + hue_shift) % 1.0
    new_lightness = hls[1] * lightness_factor
    new_hls = (new_hue, new_lightness, hls[2])
    return colorsys.hls_to_rgb(*new_hls)


def transform_to_capital_growth(df, initial_investment=1000):
    """Преобразует датафрейм для отображения изменения капитала при единовременном вложении."""
    df_transformed = df.copy()
    df_transformed["TRADEDATE"] = pd.to_datetime(df_transformed["TRADEDATE"])
    df_transformed = df_transformed.sort_values("TRADEDATE").reset_index(drop=True)
    first_price = df_transformed["CLOSE"].iloc[0]
    df_transformed["CLOSE"] = initial_investment * (
        df_transformed["CLOSE"] / first_price
    )

    return df_transformed


def calculate_monthly_investment(df, monthly_investment, value_column="CLOSE"):
    """Рассчитывает капитал при регулярных ежемесячных вложениях."""
    df_monthly = df.copy()
    df_monthly["TRADEDATE"] = pd.to_datetime(df_monthly["TRADEDATE"])
    df_monthly = df_monthly.sort_values("TRADEDATE").reset_index(drop=True)
    df_monthly["year_month"] = df_monthly["TRADEDATE"].dt.to_period("M")
    monthly_end_points = (
        df_monthly.groupby("year_month")
        .apply(lambda x: x.loc[x["TRADEDATE"].idxmax()])
        .reset_index(drop=True)
    )
    monthly_end_points["shares_bought"] = (
        monthly_investment / monthly_end_points[value_column]
    )
    monthly_end_points["cumulative_shares"] = monthly_end_points[
        "shares_bought"
    ].cumsum()
    df_monthly = df_monthly.merge(
        monthly_end_points[["year_month", "cumulative_shares"]],
        left_on="year_month",
        right_on="year_month",
        how="left",
    )
    df_monthly["cumulative_shares"] = df_monthly["cumulative_shares"].fillna(
        method="ffill"
    )
    df_monthly["portfolio_value"] = (
        df_monthly["cumulative_shares"] * df_monthly[value_column]
    )
    return df_monthly


def calculate_yearly_investment(df, yearly_investment, value_column="CLOSE"):
    """Рассчитывает капитал при регулярных ежегодных вложениях."""
    df_yearly = df.copy()
    df_yearly["TRADEDATE"] = pd.to_datetime(df_yearly["TRADEDATE"])
    df_yearly = df_yearly.sort_values("TRADEDATE").reset_index(drop=True)
    df_yearly["year"] = df_yearly["TRADEDATE"].dt.to_period("Y")
    yearly_end_points = (
        df_yearly.groupby("year")
        .apply(lambda x: x.loc[x["TRADEDATE"].idxmax()])
        .reset_index(drop=True)
    )
    yearly_end_points["shares_bought"] = (
        yearly_investment / yearly_end_points[value_column]
    )
    yearly_end_points["cumulative_shares"] = yearly_end_points["shares_bought"].cumsum()
    df_yearly = df_yearly.merge(
        yearly_end_points[["year", "cumulative_shares"]],
        left_on="year",
        right_on="year",
        how="left",
    )
    df_yearly["cumulative_shares"] = df_yearly["cumulative_shares"].fillna(
        method="ffill"
    )
    df_yearly["portfolio_value"] = (
        df_yearly["cumulative_shares"] * df_yearly[value_column]
    )
    return df_yearly


def prepare_dataset(
    df, strategy="single_investment", value_column="CLOSE", **strategy_params
):
    """Подготавливает датасет в зависимости от выбранной стратегии."""
    if strategy == "single_investment":
        return transform_to_capital_growth(
            df, strategy_params.get("initial_investment", 1000)
        )
    elif strategy == "monthly_investment":
        return calculate_monthly_investment(
            df, strategy_params.get("monthly_investment", 1000), value_column
        )
    elif strategy == "yearly_investment":
        return calculate_yearly_investment(
            df, strategy_params.get("yearly_investment", 1000), value_column
        )
    else:
        raise ValueError(f"Unknown strategy: {strategy}")


def calculate_capital_with_reinvest(
    df,
    initial_investment=10000,
    monthly_investment=0,
    yearly_investment=0,
    price_col="CLOSE",
    dividend_col="DIVIDEND",
):
    """
    Рассчитывает капитал по двум направлениям:
    1) CAPITAL_REINVEST — капитал с реинвестированием дивидендов.
    2) savings — простые накопления: только вложенные деньги,
       без учета акций, роста цены и дивидендов.

    Параметры:
    initial_investment — стартовое вложение
    monthly_investment — ежемесячное пополнение
    yearly_investment — ежегодное пополнение
    """

    df = df.copy()
    df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
    df = df.sort_values("TRADEDATE").reset_index(drop=True)

    # ----------- Инициализация -----------
    first_price = df[price_col].iloc[0]
    shares = initial_investment / first_price

    df["shares"] = 0.0
    df["savings"] = 0.0

    df.at[0, "shares"] = shares
    df.at[0, "savings"] = initial_investment

    prev_date = df.loc[0, "TRADEDATE"]

    # ----------- Основной цикл по датам -----------
    for i in range(1, len(df)):
        row = df.loc[i]
        date = row["TRADEDATE"]
        price = row[price_col]
        dividend = row.get(dividend_col, 0.0)

        # продолжение количества акций
        shares = df.loc[i - 1, "shares"]

        # 1) Реинвестирование дивидендов
        if dividend > 0:
            total_div = dividend * shares
            shares += total_div / price

        # 2) Месячные пополнения (покупка акций + накопления)
        if monthly_investment > 0 and (date.month != prev_date.month):
            shares += monthly_investment / price
            df.loc[i, "savings"] = df.loc[i - 1, "savings"] + monthly_investment
        else:
            df.loc[i, "savings"] = df.loc[i - 1, "savings"]

        # 3) Годовые пополнения (покупка акций + накопления)
        if yearly_investment > 0 and (date.year != prev_date.year):
            shares += yearly_investment / price
            df.loc[i, "savings"] += (
                yearly_investment  # плюсуем к уже записанному в savings
            )

        df.loc[i, "shares"] = shares
        prev_date = date

    # итоговый капитал с реинвестом
    df["CAPITAL_REINVEST"] = df["shares"] * df[price_col]

    return df


def draw_gradient_line(ax, x_data, y_data, start_color, name, n_segments=50):
    """Рисует линию с плавным градиентным переходом цвета, оптимизировано для скорости."""
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


def draw_event_zones_anim(ax, events_df, frame_date):
    import matplotlib.dates as mdates

    frame_num = mdates.date2num(frame_date)

    grouped = events_df.groupby("EVENT_NAME")

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
            ax.text(
                start,
                ax.get_ylim()[1] * 0.95,
                event_name.replace("_", " "),
                fontsize=12,
                color="white",
                va="top",
                alpha=0.9,
                zorder=100,
            )


def event_color(impact):
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

    # --- объединяем данные ---
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
    # --- подготовка кадров ---
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

    def animate(i):
        frame_index = final_frame_index if i >= len(animation_frames) else all_frames[i]
        current_data = combined_df.iloc[: frame_index + 1]

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
        # --- Анимация событий ---
        frame_date = current_data["TRADEDATE"].iloc[-1]
        draw_event_zones_anim(ax, data_list[0]["data"], frame_date)
        # --- рисуем линии и дивиденды ---
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

            # линия цены
            ax.plot(
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
            # дивиденды
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
            # подпись последней цены
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
                # fontweight="bold",
                bbox=dict(
                    boxstyle="round,pad=0.4",
                    facecolor="#131314FF",
                    edgecolor=end_color if end_color else item["color"],
                ),
            )

        # диапазон по Y
        price_cols = [col for col in current_data.columns if col != "TRADEDATE"]
        valid_prices = current_data[price_cols].stack().dropna()
        if not valid_prices.empty:
            price_min, price_max = valid_prices.min(), valid_prices.max()
            margin = max(
                (price_max - price_min) * 0.05, 0.001 * (price_max - price_min)
            )
            ax.set_ylim(price_min - margin, price_max + margin)

    return animation.FuncAnimation(
        fig, animate, frames=len(all_frames), interval=1000 / fps, repeat=False
    )


def load_latest_parquet(engine, market, ticker):
    from pathlib import Path

    base = Path(engine) / market / ticker
    if not base.exists():
        raise FileNotFoundError(f"Path does not exist: {base}")
    files = list(base.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet files in: {base}")
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0]


def load_ticker_df(path, start_date=None, end_date=None):
    df = pd.read_parquet(path)
    df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"]).dt.date
    df = df.sort_values("TRADEDATE")
    if start_date:
        df = df[df["TRADEDATE"] >= start_date.date()]
    if end_date:
        df = df[df["TRADEDATE"] <= end_date.date()]
    return df


def validate_args(args):
    if not (args.ticker and args.engine and args.market):
        raise ValueError(
            "You must provide --ticker, --engine and --market for each dataset"
        )

    if not (len(args.ticker) == len(args.engine) == len(args.market)):
        raise ValueError(
            "Each --ticker must have a corresponding --engine and --market"
        )


def parse_dates(args):
    start = datetime.strptime(args.start_date, "%Y-%m-%d") if args.start_date else None
    end = datetime.strptime(args.end_date, "%Y-%m-%d") if args.end_date else None
    return start, end


# ------------------------ COLOR GENERATION -------------------------


def generate_unique_colors(n: int, palette_name="tab20"):
    cmap = plt.get_cmap(palette_name)
    colors = [cmap(i / n) for i in range(n)]
    return ["#%02x%02x%02x" % tuple(int(c * 255) for c in rgba[:3]) for rgba in colors]


# ------------------------ TICKER PROCESSING ------------------------


def load_and_prepare_dataset(
    ticker,
    engine,
    market,
    start_date,
    end_date,
    initial_investment: int = 100,
    monthly_investment: int = 100,
    yearly_investment: int = 0,
):
    parquet_path = load_latest_parquet(engine, market, ticker)
    df_raw = load_ticker_df(parquet_path, start_date, end_date)
    df_prepared = calculate_capital_with_reinvest(
        df_raw,
        initial_investment=initial_investment,
        monthly_investment=monthly_investment,
        yearly_investment=yearly_investment,
    )
    return df_prepared


def build_data_list(
    args,
    build_args,
    start_date,
    end_date,
):
    """
    Загружает все тикеры, присваивает уникальные цвета,
    возвращает список словарей для анимации.
    Если with_investments=True, добавляет отдельный датасет с инвестициями
    с параметрами reinvest.
    """

    tickers = getattr(build_args, "ticker", [])
    engines = getattr(build_args, "engine", [])
    markets = getattr(build_args, "market", [])
    with_investments = getattr(args, "with_investments", False)
    initial_investment = args.initial_investment
    monthly_investment = args.initial_investment
    yearly_investment = args.yearly_investment

    if not (tickers and engines and markets):
        raise ValueError("You must provide --ticker, --engine and --market")

    if len(tickers) != len(engines) != len(markets):
        raise ValueError("Each --ticker must have a --engine and --market")

    colors = generate_unique_colors(len(tickers))

    data_list = []
    investments_df = None

    for ticker, engine, market, color in zip(tickers, engines, markets, colors):
        try:
            df_raw = load_and_prepare_dataset(
                ticker,
                engine,
                market,
                start_date,
                end_date,
                initial_investment,
                monthly_investment,
                yearly_investment,
            )
        except Exception as e:
            logging.error(f"Error loading dataset for {ticker}: {e}")
            continue

        data_list.append({"data": df_raw, "name": ticker, "color": color})

        if with_investments and investments_df is None:
            try:
                df_prepared = calculate_capital_with_reinvest(
                    df_raw,
                    initial_investment=initial_investment,
                    monthly_investment=monthly_investment,
                    yearly_investment=yearly_investment,
                )
            except Exception as e:
                logging.error(f"Error calculating investments for {ticker}: {e}")
                continue

            investments_df = df_prepared[["TRADEDATE", "savings"]].copy()
            investments_df.rename(columns={"savings": "CAPITAL_REINVEST"}, inplace=True)

    if investments_df is not None:
        inv_color = "#%06x" % (hash("Инвестиции") & 0xFFFFFF)
        data_list.append(
            {"data": investments_df, "name": "Инвестиции", "color": inv_color}
        )
    return data_list


# --------------------------- MAIN LOGIC ----------------------------


@dataclass
class BuildArgs:
    ticker: list
    engine: list
    market: list
    with_investments: bool


def render_charts(args, specs, start_date, end_date):
    import logging

    logging.info("Preparing data for rendering charts...")

    build_args = BuildArgs(
        ticker=[x["ticker"] for x in specs],
        engine=[x["engine"] for x in specs],
        market=[x["market"] for x in specs],
        with_investments=args.with_investments,
    )

    logging.info(f"Tickers: {build_args.ticker}")
    logging.info(f"Engines: {build_args.engine}")
    logging.info(f"Markets: {build_args.market}")

    data_list = build_data_list(args, build_args, start_date, end_date)

    logging.info("Building animation...")
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

    logging.info(f"Saving animation to: {filepath}")
    anim.save(filepath, writer="ffmpeg", fps=args.fps, dpi=150)

    logging.info("Animation saved successfully.")
