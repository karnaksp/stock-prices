from __future__ import annotations

from importlib import resources
from pathlib import Path

import pandas as pd


def _default_events_path() -> Path:
    return Path(str(resources.files("stock_prices._internal").joinpath("events.json")))


def load_events(json_path: str | Path | None = None) -> pd.DataFrame:
    path = Path(json_path) if json_path else Path("events.json")
    if not path.exists():
        path = _default_events_path()
    if not path.exists():
        return pd.DataFrame(columns=["start", "end", "event", "type", "impact"])

    events = pd.read_json(path)
    if events.empty:
        return pd.DataFrame(columns=["start", "end", "event", "type", "impact"])
    events["start"] = pd.to_datetime(events["start"])
    events["end"] = pd.to_datetime(events["end"])
    return events


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
