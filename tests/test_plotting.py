from __future__ import annotations

import pandas as pd

from stock_prices._internal.lib import dataset_builder
from stock_prices._internal.lib.plotting import _combine_data, _return_from_series, _series_summary


def test_series_summary_keeps_bottom_label_to_return_only() -> None:
    values = pd.Series([100.0, 150.0, 120.0])

    assert _series_summary("TEST", values) == "TEST: +20.0%"


def test_series_summary_handles_empty_values() -> None:
    assert _series_summary("TEST", pd.Series(dtype=float)) == "TEST: n/a"


def test_return_from_series_uses_invested_basis_for_zero_initial_dca() -> None:
    capital = pd.Series([0.0, 110.0, 230.0])
    invested = pd.Series([0.0, 100.0, 200.0])

    assert _return_from_series(capital, invested) == "+15.0%"


def test_return_from_series_keeps_invested_line_at_zero() -> None:
    invested = pd.Series([0.0, 100.0, 200.0])

    assert _return_from_series(invested, invested) == "0.0%"


def test_combine_data_handles_invested_series_without_dividends() -> None:
    data_list = [
        {
            "name": "GC=F",
            "color": "#FFD166",
            "data": pd.DataFrame(
                {
                    "TRADEDATE": pd.to_datetime(["2020-01-01", "2020-01-02"]),
                    "CAPITAL_REINVEST": [100.0, 101.0],
                    "DIVIDEND": [0.0, 0.5],
                    "savings": [100.0, 100.0],
                }
            ),
        },
        {
            "name": "Invested",
            "color": "#8f9aa8",
            "data": pd.DataFrame(
                {
                    "TRADEDATE": pd.to_datetime(["2020-01-01", "2020-01-02"]),
                    "CAPITAL_REINVEST": [30_000.0, 60_000.0],
                    "savings": [30_000.0, 60_000.0],
                }
            ),
        },
    ]

    combined, value_columns, dividend_columns, basis_columns = _combine_data(data_list, "CAPITAL_REINVEST")

    assert value_columns == ["GC=F", "Invested"]
    assert dividend_columns["Invested"] == "DIVIDEND_Invested"
    assert basis_columns["GC=F"] == "SAVINGS_GC=F"
    assert basis_columns["Invested"] == "SAVINGS_Invested"
    assert combined["DIVIDEND_Invested"].tolist() == [0.0, 0.0]
    assert combined["SAVINGS_Invested"].tolist() == [30_000.0, 60_000.0]


def test_generate_unique_colors_shuffles_palette(monkeypatch) -> None:
    class ReverseRandom:
        def shuffle(self, values: list[str]) -> None:
            values.reverse()

    monkeypatch.setattr(dataset_builder.random, "SystemRandom", lambda: ReverseRandom())

    assert dataset_builder.generate_unique_colors(2) == ["#A3E635", "#F72585"]
