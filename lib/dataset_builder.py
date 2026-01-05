"""
Модуль для подготовки датасетов с торговыми данными по заданным параметрам
"""

import re
import pandas as pd
import logging


def calculate_capital_with_reinvest(
    data_frame,
    initial_investment=10000,
    monthly_investment=0,
    yearly_investment=0,
    price_col="CLOSE",
    dividend_col="DIVIDEND",
    ticker=None,
):
    """
    Рассчитывает капитал с реинвестированием дивидендов ежемесячным, ежегодным.

    Args:
        data_frame: DataFrame с торговыми данными
        initial_investment: Начальная сумма инвестиций
        monthly_investment: Ежемесячные инвестиции
        yearly_investment: Ежегодные инвестиции
        price_col: Колонка с ценами
        dividend_col: Колонка с дивидендами (в денежных единцах на акцию)
        ticker: Тикер (необязательно): если есть, ищет Сплит в данных об ивентах по этому тикеру и делит цену на коэффициент сплита.

    Returns:
        DataFrame с рассчитанным капиталом
    """
    data_frame = data_frame.copy()
    data_frame["TRADEDATE"] = pd.to_datetime(data_frame["TRADEDATE"])
    data_frame = data_frame.sort_values("TRADEDATE").reset_index(drop=True)
    first_price = data_frame[price_col].iloc[0]
    shares = initial_investment / first_price
    cash_buffer = 0.0
    data_frame["shares"] = 0.0
    data_frame["cash_buffer"] = 0.0
    data_frame["savings"] = 0.0
    data_frame["CAPITAL_REINVEST"] = 0.0
    data_frame.at[0, "shares"] = shares
    data_frame.at[0, "savings"] = initial_investment
    data_frame.at[0, "cash_buffer"] = 0.0
    current_month = data_frame.loc[0, "TRADEDATE"].month
    current_year = data_frame.loc[0, "TRADEDATE"].year

    if ticker is not None and "EVENT_TYPE" in data_frame.columns:
        split_rows = data_frame[
            data_frame["EVENT_TYPE"].str.contains(ticker, na=False)
            & data_frame["EVENT_TYPE"].str.contains("Split", case=False, na=False)
        ]

        for idx, row in split_rows.iterrows():
            event_text = row["EVENT_NAME"]
            match = re.search(r"(\d+):(\d+)", event_text)
            if match:
                old_shares = int(match.group(1))
                new_shares = int(match.group(2))
                if new_shares == 0:
                    continue
                ratio = old_shares / new_shares
                data_frame.loc[idx:, price_col] /= ratio

    for i in range(1, len(data_frame)):
        row = data_frame.loc[i]
        prev_row = data_frame.loc[i - 1]
        date = row["TRADEDATE"]
        price = row[price_col]
        dividend = row.get(dividend_col, 0.0)
        shares = prev_row["shares"]
        cash_buffer = prev_row["cash_buffer"]
        if cash_buffer > 0:
            shares += cash_buffer / price
            cash_buffer = 0.0
        if dividend > 0:
            div_cash = dividend * shares
            cash_buffer += div_cash
        new_month = date.month != current_month
        new_year = date.year != current_year
        savings_add = 0.0
        if monthly_investment > 0 and new_month:
            shares += monthly_investment / price
            savings_add += monthly_investment
            current_month = date.month
        if yearly_investment > 0 and new_year:
            shares += yearly_investment / price
            savings_add += yearly_investment
            current_year = date.year
        data_frame.loc[i, "savings"] = prev_row["savings"] + savings_add
        data_frame.loc[i, "shares"] = shares
        data_frame.loc[i, "cash_buffer"] = cash_buffer
    data_frame["CAPITAL_REINVEST"] = data_frame["shares"] * data_frame[price_col]
    return data_frame


def generate_unique_colors(n: int, palette_name="hsv"):
    """
    Генерирует уникальные цвета

    Args:
        n: Количество цветов
        palette_name: Название цветовой палитры

    Returns:
        Список уникальных цветов в формате HEX
    """
    import matplotlib.pyplot as plt

    cmap = plt.get_cmap(palette_name)
    colors = [cmap(i / n) for i in range(n)]
    return ["#%02x%02x%02x" % tuple(int(c * 255) for c in rgba[:3]) for rgba in colors]


def prepare_dataset(
    ticker,
    engine,
    market,
    start_date,
    end_date,
    initial_investment: int = 100,
    monthly_investment: int = 100,
    yearly_investment: int = 0,
):
    """
    Загружает и подготавливает датасет для тикера

    Args:
        ticker: Тикер
        engine: Движок торгов
        market: Рынок
        start_date: Начальная дата
        end_date: Конечная дата
        initial_investment: Начальная сумма инвестиций
        monthly_investment: Ежемесячные инвестиции
        yearly_investment: Ежегодные инвестиции

    Returns:
        Подготовленный DataFrame
    """
    from .file_utils import load_latest_parquet, load_ticker_df

    parquet_path = load_latest_parquet(engine, market, ticker)
    df_raw = load_ticker_df(parquet_path, start_date, end_date)
    df_prepared = calculate_capital_with_reinvest(
        df_raw,
        initial_investment=initial_investment,
        monthly_investment=monthly_investment,
        yearly_investment=yearly_investment,
        ticker=ticker,
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
    monthly_investment = args.monthly_investment
    yearly_investment = args.yearly_investment

    if not (tickers and engines and markets):
        raise ValueError("Необходимо указать --ticker, --engine и --market")

    if len(tickers) != len(engines) != len(markets):
        raise ValueError("Каждый --ticker должен иметь --engine и --market")

    colors = generate_unique_colors(len(tickers))

    data_list = []
    investments_df = None

    for ticker, engine, market, color in zip(tickers, engines, markets, colors):
        try:
            df_raw = prepare_dataset(
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
            logging.error(f"Ошибка при загрузке набора данных для {ticker}: {e}")
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
                logging.error(f"Ошибка при расчете инвестиций для {ticker}: {e}")
                continue

            investments_df = df_prepared[["TRADEDATE", "savings"]].copy()
            investments_df.rename(columns={"savings": "CAPITAL_REINVEST"}, inplace=True)

    if investments_df is not None:
        inv_color = "#%06x" % (hash("Инвестиции") & 0xFFFFFF)
        data_list.append(
            {"data": investments_df, "name": "Инвестиции", "color": inv_color}
        )
    return data_list
