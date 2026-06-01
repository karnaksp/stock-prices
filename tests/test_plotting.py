from __future__ import annotations

import pandas as pd

from stock_prices._internal.lib import dataset_builder
from stock_prices._internal.lib.plotting import _amount_summary, _combine_data, _return_summary, _visible_x_span_days


def test_amount_summary_shows_latest_amount() -> None:
    values = pd.Series([100.0, 150.0, 120.0])

    assert _amount_summary("TEST", values) == "TEST: 120"


def test_amount_summary_handles_empty_values() -> None:
    assert _amount_summary("TEST", pd.Series(dtype=float)) == "TEST: n/a"


def test_amount_summary_shows_invested_actual_amount() -> None:
    invested = pd.Series([0.0, 30_000.0, 60_000.0])

    assert _amount_summary("Invested", invested) == "Invested: 60.0K"


def test_return_summary_uses_invested_basis_for_zero_initial_dca() -> None:
    capital = pd.Series([0.0, 110.0, 230.0])
    invested = pd.Series([0.0, 100.0, 200.0])

    assert _return_summary("TEST", capital, invested) == "TEST: +15.0%"


def test_return_summary_shows_invested_actual_amount() -> None:
    invested = pd.Series([0.0, 30_000.0, 60_000.0])

    assert _return_summary("Invested", invested, invested) == "Invested: 60.0K"


def test_visible_x_span_starts_with_readable_window() -> None:
    start = pd.Timestamp("2021-12-17")

    assert _visible_x_span_days(start, start, 1627) == 45
    assert _visible_x_span_days(start, start + pd.Timedelta(days=10), 1627) == 45
    assert _visible_x_span_days(start, start + pd.Timedelta(days=120), 1627) == 120


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
