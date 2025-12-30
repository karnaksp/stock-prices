# -*- coding: utf-8 -*-

import os
import logging
import requests

import apimoex
import pandas as pd


def load_events(json_path="events.json"):
    events = pd.read_json(json_path)
    events["start"] = pd.to_datetime(events["start"])
    events["end"] = pd.to_datetime(events["end"])
    return events


def enrich_with_events(df, events_df):
    df["EVENT_NAME"] = None
    df["EVENT_TYPE"] = None
    df["EVENT_IMPACT"] = 0

    for _, ev in events_df.iterrows():
        mask = (df["TRADEDATE"] >= ev["start"]) & (df["TRADEDATE"] <= ev["end"])
        df.loc[mask, "EVENT_NAME"] = ev["event"]
        df.loc[mask, "EVENT_TYPE"] = ev["type"]
        df.loc[mask, "EVENT_IMPACT"] = ev["impact"]

    return df


def get_parquet_filepath(engine, market, ticker, date_str):
    """
    Generate filepath for parquet files organized by date intervals
    """
    return f"./{engine}/{market}/{ticker}/{date_str}.parquet"


def save_to_parquet(data, engine, market, ticker, date_str):
    """
    Save data to parquet format with interval-based folder naming
    """
    filepath = get_parquet_filepath(engine, market, ticker, date_str)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    data.to_parquet(filepath, index=False)
    logging.info(f"Saved data to {filepath}")


def validate_float_val(quote, key):
    val = quote.get(key)
    return val is not None and isinstance(val, (int, float)) and val > 0


def validate_quote(quote, engine, market):
    if engine == "currency" and market == "selt":
        return (
            validate_float_val(quote, "VOLRUR")
            or validate_float_val(quote, "NUMTRADES")
            or validate_float_val(quote, "CLOSE")
        )
    elif engine == "stock" and market in ["bonds", "shares"]:
        return (
            validate_float_val(quote, "VOLUME")
            or validate_float_val(quote, "NUMTRADES")
            or validate_float_val(quote, "CLOSE")
        )
    elif engine == "stock" and market == "index":
        return validate_float_val(quote, "CLOSE")

    assert False, "Unknown quote type"


def div_data(ticker, start_date, end_date):
    """
    Получение данных по дивидендам через yfinance.
    Возвращает dataframe с колонками: TRADEDATE, DIVIDEND.
    Даты start_date и end_date используются для фильтрации.
    """
    import yfinance as yf
    import pandas as pd

    symbol = f"{ticker}.ME"
    yf_ticker = yf.Ticker(symbol)
    dividends = yf_ticker.dividends.loc[
        start_date.strftime("%Y-%m-%d") : end_date.strftime("%Y-%m-%d")
    ]
    if dividends.empty:
        return pd.DataFrame(columns=["TRADEDATE", "DIVIDEND"])
    dividends = dividends.reset_index()
    dividends["Date"] = pd.to_datetime(dividends["Date"]).dt.tz_localize(None)
    dividends = dividends.rename(columns={"Date": "TRADEDATE", "Dividends": "DIVIDEND"})
    dividends = dividends[["TRADEDATE", "DIVIDEND"]]
    dividends = dividends.sort_values("TRADEDATE")
    return dividends


def validate_data(df, ticker, start_date, end_date):
    """
    Обработка данных MOEX:
    - удаление BOARDID
    - группировка по TRADEDATE
    - CLOSE → mean
    - VOLUME → sum
    - VALUE → sum
    - объединение с дивидендами
    """
    if "BOARDID" in df.columns:
        df = df.drop(columns=["BOARDID"])
    grouped = (
        df.groupby("TRADEDATE")
        .agg({"CLOSE": "mean", "VOLUME": "sum", "VALUE": "sum"})
        .reset_index()
    )
    div_df = div_data(ticker, start_date, end_date)
    merged = grouped.merge(div_df, on="TRADEDATE", how="left")
    merged["DIVIDEND"] = merged["DIVIDEND"].fillna(0)
    events_df = load_events()
    merged = enrich_with_events(merged, events_df)
    return merged


def moex_data(engine, market, ticker, start_date, end_date):
    import pandas as pd

    date_str = f"{int(start_date.timestamp())}-{int(end_date.timestamp())}"
    with requests.Session() as session:
        data = apimoex.get_market_history(
            session,
            security=ticker,
            start=start_date,
            end=end_date,
            engine=engine,
            market=market,
        )
        if data:
            valid_data = [row for row in data if validate_quote(row, engine, market)]
            df = pd.DataFrame(valid_data)
            df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
            validated = validate_data(df, ticker, start_date, end_date)
            save_to_parquet(
                validated, engine, market, ticker, date_str.replace("-", "")
            )
        else:
            logging.error(
                'No data received for "{}, {}, {}"'.format(engine, market, date_str)
            )


def international_data(
    engine,
    market,
    ticker,
    start_date,
    end_date,
    currency=None,  # None или 'RUB' (в любом виде: 'Рубль', 'R', '₽' и т.д.)
):
    """
    Универсальный загрузчик данных по международным тикерам через yfinance
    с опциональной конвертацией всех ценовых колонок в рубли (RUB) через forex-python (ECB rates).
    """
    import yfinance as yf
    import pandas as pd
    import logging
    import os
    from datetime import datetime
    from forex_python.converter import CurrencyRates, RatesNotAvailableError

    # --- Нормализация параметра currency ---
    convert_to_rub = False
    rub_variants = {"RUB", "R", "РУБЛЬ", "РУБ", "₽", "Р"}
    if currency and str(currency).strip().upper() in rub_variants:
        convert_to_rub = True
        logging.info(f"[{ticker}] Запрошена конвертация данных в рубли (RUB)")

    # --- Normalize dates ---
    start_date = pd.Timestamp(start_date).tz_localize(None)
    end_date = pd.Timestamp(end_date).tz_localize(None)
    date_str = f"{start_date:%Y%m%d}_{end_date:%Y%m%d}"

    logging.info(f"[{ticker}] Loading from {start_date.date()} to {end_date.date()}")

    yf_ticker = yf.Ticker(ticker)

    # --- Определение валюты тикера ---
    base_currency = "UNKNOWN"
    try:
        info = yf_ticker.info
        base_currency = info.get("currency") or "UNKNOWN"
        logging.info(f"[{ticker}] Исходная валюта тикера: {base_currency}")
    except Exception as e:
        logging.warning(f"[{ticker}] Не удалось получить валюту тикера: {e}")

    # --- Загрузка исторических цен (без изменений) ---
    try:
        hist = yf_ticker.history(start=start_date, end=end_date, auto_adjust=False)
    except Exception as e:
        logging.error(f"Error loading history for {ticker}: {e}")
        return

    if hist.empty:
        logging.warning(f"No historical data for {ticker}")
        return

    if hist.index.tz is not None:
        hist.index = hist.index.tz_convert(None)

    df = hist.reset_index().rename(columns={"Date": "TRADEDATE"})
    df["TRADEDATE"] = df["TRADEDATE"].dt.floor("D")

    df["OPEN"] = df.get("Open")
    df["HIGH"] = df.get("High")
    df["LOW"] = df.get("Low")
    df["CLOSE"] = df.get("Close")

    if "Volume" in df.columns:
        df["VOLUME"] = df["Volume"].fillna(0)
    else:
        df["VOLUME"] = 0

    df["VALUE"] = df["CLOSE"] * df["VOLUME"]

    df = df.groupby("TRADEDATE", as_index=False).agg(
        {
            "OPEN": "first",
            "HIGH": "max",
            "LOW": "min",
            "CLOSE": "last",
            "VOLUME": "sum",
            "VALUE": "sum",
        }
    )

    # --- Дивиденды ---
    try:
        divs = yf_ticker.dividends
    except Exception:
        divs = pd.Series(dtype=float)

    if not divs.empty:
        if divs.index.tz is not None:
            divs.index = divs.index.tz_convert(None)
        divs = divs.loc[start_date:end_date]
        divs_df = divs.reset_index().rename(
            columns={"Date": "TRADEDATE", "Dividends": "DIVIDEND"}
        )
        divs_df["TRADEDATE"] = divs_df["TRADEDATE"].dt.floor("D")
        divs_df = divs_df.groupby("TRADEDATE", as_index=False).agg({"DIVIDEND": "sum"})
    else:
        divs_df = pd.DataFrame(columns=["TRADEDATE", "DIVIDEND"])

    df = df.merge(divs_df, on="TRADEDATE", how="left")
    df["DIVIDEND"] = df["DIVIDEND"].fillna(0.0)

    # --- Сохраняем оригинальные значения ---
    for col in ["OPEN", "HIGH", "LOW", "CLOSE", "VALUE", "DIVIDEND"]:
        df[f"{col}_ORIG"] = df[col]

    # --- Конвертация в рубли через CurrencyConverter (ECB, batch загрузка) ---
    if convert_to_rub and base_currency != "UNKNOWN" and base_currency != "RUB":
        if base_currency == "RUB":
            logging.info(f"[{ticker}] Тикер уже в рублях — конвертация не требуется")
        else:
            logging.info(
                f"[{ticker}] Загружаем исторические курсы {base_currency}/RUB от ECB через CurrencyConverter"
            )

            try:
                from currency_converter import CurrencyConverter

                # Создаём конвертер — он автоматически скачает/закэширует полный архив ECB при первом использовании
                c = CurrencyConverter(
                    fallback_on_missing_rate=True, fallback_on_wrong_date=True
                )

                # Если валюта не поддерживается напрямую ECB (редко), будет fallback на ближайший доступный курс
                rates_data = []
                unique_dates = df[
                    "TRADEDATE"
                ].dt.date.unique()  # Только уникальные даты

                for trade_date in unique_dates:
                    try:
                        rate = c.convert(1, base_currency, "RUB", date=trade_date)
                        rates_data.append(
                            {"TRADEDATE": pd.Timestamp(trade_date), "FX_RATE": rate}
                        )
                    except ValueError as ve:
                        # Если курс недоступен для этой даты/валюты — fallback уже внутри, но на всякий лог
                        logging.warning(
                            f"[{ticker}] Курс {base_currency}/RUB недоступен на {trade_date}: {ve}"
                        )
                        rates_data.append(
                            {"TRADEDATE": pd.Timestamp(trade_date), "FX_RATE": None}
                        )

                if not rates_data:
                    logging.error(
                        f"[{ticker}] Не удалось загрузить курсы {base_currency}/RUB"
                    )
                else:
                    fx_df = pd.DataFrame(rates_data)

                    df = df.merge(fx_df, on="TRADEDATE", how="left")

                    # Заполняем пропуски (выходные/праздники/отсутствие данных)
                    df["FX_RATE"] = df["FX_RATE"].ffill().bfill()

                    if df["FX_RATE"].isna().any():
                        logging.warning(
                            f"[{ticker}] Некоторые даты без курса после fill — останутся NaN"
                        )

                    # Конвертируем цены
                    price_cols = ["OPEN", "HIGH", "LOW", "CLOSE", "VALUE", "DIVIDEND"]
                    df[price_cols] = df[price_cols].multiply(df["FX_RATE"], axis=0)

                    # df.drop(columns=["FX_RATE"], inplace=True)
                    logging.info(
                        f"[{ticker}] Конвертация в рубли через ECB (CurrencyConverter) завершена успешно"
                    )

            except ImportError:
                logging.error(
                    "Библиотека CurrencyConverter не установлена: pip install CurrencyConverter"
                )
            except Exception as e:
                logging.error(
                    f"[{ticker}] Ошибка при конвертации через CurrencyConverter: {e}"
                )

    elif convert_to_rub and base_currency == "RUB":
        logging.info(f"[{ticker}] Тикер уже в рублях — конвертация не требуется")

    # --- SAVE ---
    filepath = get_parquet_filepath(engine, market, ticker, date_str)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    events_df = load_events()
    df = enrich_with_events(df, events_df)

    df.attrs["ticker"] = ticker
    df.attrs["base_currency"] = base_currency
    df.attrs["target_currency"] = "RUB" if convert_to_rub else base_currency

    df.to_parquet(filepath, index=False)
    logging.info(
        f"[{ticker}] Saved parquet to {filepath} "
        f"(валюта: {'RUB' if convert_to_rub else base_currency})"
    )


def parse_ticker_spec(spec: str):
    """
    Преобразует строку вида 'AAPL|global|shares'
    в структуру {ticker, engine, market}
    """
    parts = spec.split("|")
    if len(parts) != 3:
        raise ValueError(
            f"Неверный формат для '{spec}'. Ожидается ticker|engine|market"
        )
    return {
        "ticker": parts[0],
        "engine": parts[1],
        "market": parts[2],
    }


def download_all(specs, start_date, end_date, currency):
    import logging

    for item in specs:
        ticker = item["ticker"]
        engine = item["engine"]
        market = item["market"]

        logging.info(f"[DOWNLOAD] {ticker} ({engine}/{market})")
        if engine == "global":
            international_data(
                engine=engine,
                market=market,
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
            )
        else:
            moex_data(
                engine=engine,
                market=market,
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
            )
