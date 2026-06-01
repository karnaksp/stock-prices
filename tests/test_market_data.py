from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from stock_prices._internal.lib.moex_data import enrich_me_data, get_div_for_me
from stock_prices._internal.lib.validators import validate_quote_structure


def test_validate_moex_futures_quote() -> None:
    quote = {"TRADEDATE": "2024-01-03", "CLOSE": 92973.0, "VOLUME": 407186, "VALUE": 37707202247.0}

    assert validate_quote_structure(quote, "futures", "forts")


def test_enrich_moex_currency_without_volume_value() -> None:
    df = pd.DataFrame(
        [
            {"TRADEDATE": "2024-01-03", "CLOSE": 92.0},
            {"TRADEDATE": "2024-01-03", "CLOSE": 91.0},
            {"TRADEDATE": "2024-01-04", "CLOSE": 90.0},
        ]
    )
    df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])

    enriched = enrich_me_data(
        df,
        "USD000UTSTOM",
        pd.Timestamp("2024-01-03"),
        pd.Timestamp("2024-01-04"),
        "currency",
        "selt",
    )

    assert list(enriched["CLOSE"]) == [91.5, 90.0]
    assert list(enriched["VOLUME"]) == [0.0, 0.0]
    assert list(enriched["DIVIDEND"]) == [0.0, 0.0]


def test_get_div_for_me_handles_none_from_yfinance(monkeypatch) -> None:
    class FakeTicker:
        dividends = None

    fake_yfinance = SimpleNamespace(Ticker=lambda _ticker: FakeTicker())
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    dividends = get_div_for_me("KLVZ", pd.Timestamp("2024-02-22"), pd.Timestamp("2026-06-01"))

    assert dividends.empty
    assert list(dividends.columns) == ["TRADEDATE", "DIVIDEND"]
