from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path

import pandas as pd


def _default_events_path() -> Path:
    return Path(str(resources.files("stock_prices._internal").joinpath("events.json")))


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=["start", "end", "event", "type", "impact"])


def _resolve_events_path(json_path: str | Path | None = None) -> Path | None:
    path = Path(json_path) if json_path else Path("events.json")
    if not path.exists():
        path = _default_events_path()
    if not path.exists():
        return None
    return path.resolve()


@lru_cache(maxsize=8)
def _load_events_cached(path_key: str | None) -> pd.DataFrame:
    if path_key is None:
        return _empty_events()
    path = Path(path_key)
    events = pd.read_json(path)
    if events.empty:
        return _empty_events()
    events["start"] = pd.to_datetime(events["start"])
    events["end"] = pd.to_datetime(events["end"])
    return events


def load_events(json_path: str | Path | None = None) -> pd.DataFrame:
    path = _resolve_events_path(json_path)
    return _load_events_cached(str(path) if path is not None else None).copy(deep=True)


def add_events(data_frame: pd.DataFrame, events_df: pd.DataFrame) -> None:
    data_frame["EVENT_NAME"] = None
    data_frame["EVENT_TYPE"] = None
    data_frame["EVENT_IMPACT"] = 0
    if events_df.empty:
        return

    trade_dates = pd.to_datetime(data_frame["TRADEDATE"])
    for _, event in events_df.iterrows():
        mask = (trade_dates >= event["start"]) & (trade_dates <= event["end"])
        data_frame.loc[mask, "EVENT_NAME"] = event["event"]
        data_frame.loc[mask, "EVENT_TYPE"] = event["type"]
        data_frame.loc[mask, "EVENT_IMPACT"] = event["impact"]
