from __future__ import annotations

import pandas as pd

from stock_prices._internal.lib.moex_data import enrich_me_data
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
