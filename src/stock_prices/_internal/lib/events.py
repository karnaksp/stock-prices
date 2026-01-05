"""
Модуль для работы с событиями
"""

import pandas as pd


def load_events(json_path: str = "events.json") -> pd.DataFrame:
    """
    Загрузка данных о событиях из JSON файла

    Args:
        json_path: Путь к файлу с событиями

    Returns:
        DataFrame с событиями и датами
    """
    events = pd.read_json(json_path)
    events["start"] = pd.to_datetime(events["start"])
    events["end"] = pd.to_datetime(events["end"])
    return events


def add_events(data_frame: pd.DataFrame, events_df: pd.DataFrame) -> None:
    """
    Добавление столбцов событий к существующему DataFrame

    Args:
        data_frame: Существующий DataFrame, к которому нужно добавить столбцы
        events_df: DataFrame с событиями
    """
    data_frame["EVENT_NAME"] = None
    data_frame["EVENT_TYPE"] = None
    data_frame["EVENT_IMPACT"] = 0

    for _, event in events_df.iterrows():
        mask = (data_frame["TRADEDATE"] >= event["start"]) & (
            data_frame["TRADEDATE"] <= event["end"]
        )
        data_frame.loc[mask, "EVENT_NAME"] = event["event"]
        data_frame.loc[mask, "EVENT_TYPE"] = event["type"]
        data_frame.loc[mask, "EVENT_IMPACT"] = event["impact"]