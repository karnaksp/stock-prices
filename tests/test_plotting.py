from __future__ import annotations

import pandas as pd

from stock_prices._internal.lib import dataset_builder
from stock_prices._internal.lib.plotting import (
    _active_event_ranges,
    _active_events,
    _amount_summary,
    _animation_frame_data,
    _combine_data,
    _event_ranges,
    _prefix_y_limits,
    _return_summary,
    _visible_x_span_days,
    create_multi_line_animation,
)
from stock_prices._internal.rendering.theme import get_chart_theme, get_theme_names


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


def test_visible_x_span_uses_full_period_to_prevent_expanding_axis() -> None:
    start = pd.Timestamp("2021-12-17")

    assert _visible_x_span_days(start, start, 1627) == 1627
    assert _visible_x_span_days(start, start + pd.Timedelta(days=10), 1627) == 1627
    assert _visible_x_span_days(start, start + pd.Timedelta(days=120), 1627) == 1627
    assert _visible_x_span_days(start, start + pd.Timedelta(days=2000), 1627) == 1627


def test_animation_line_data_uses_current_frame_slice() -> None:
    combined = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2021-12-17", "2022-01-17", "2022-02-17"]),
            "SBER": [100.0, 140.0, 90.0],
        }
    )

    current_data, line_data = _animation_frame_data(combined, 0)

    assert current_data["TRADEDATE"].tolist() == [pd.Timestamp("2021-12-17")]
    assert line_data["TRADEDATE"].tolist() == [pd.Timestamp("2021-12-17")]
    assert line_data["SBER"].tolist() == [100.0]


def test_animation_line_data_uses_same_prefix_as_current_frame() -> None:
    combined = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2021-12-17", "2022-01-17", "2022-02-17"]),
            "SBER": [100.0, 140.0, 90.0],
        }
    )

    current_data, line_data = _animation_frame_data(combined, 1)

    expected_dates = [pd.Timestamp("2021-12-17"), pd.Timestamp("2022-01-17")]
    assert current_data["TRADEDATE"].tolist() == expected_dates
    assert line_data["TRADEDATE"].tolist() == expected_dates
    assert current_data["SBER"].tolist() == [100.0, 140.0]
    assert line_data["SBER"].tolist() == [100.0, 140.0]


def test_animation_draws_only_current_frame_slice_on_first_frame() -> None:
    import matplotlib.pyplot as plt

    data_frame = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2021-12-17", "2022-01-17", "2022-02-17"]),
            "CLOSE": [100.0, 140.0, 90.0],
            "DIVIDEND": [0.0, 0.0, 0.0],
        }
    )
    animation = create_multi_line_animation(
        [{"name": "SBER", "color": "#FFD166", "data": data_frame}],
        target_duration=1,
        fps=1,
        final_frame_duration=0,
    )

    try:
        animation._func(0)
        animation._draw_was_started = True
        line = animation._fig.axes[0].lines[0]
        y_bottom, y_top = animation._fig.axes[0].get_ylim()

        assert len(line.get_xdata()) == 1
        assert list(line.get_ydata()) == [100.0]
        assert y_bottom < 90.0
        assert y_top > 140.0
    finally:
        plt.close(animation._fig)


def test_animation_keeps_full_time_window_while_series_uses_current_slice() -> None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    data_frame = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2021-12-17", "2022-01-17", "2022-02-17"]),
            "CLOSE": [100.0, 140.0, 90.0],
            "DIVIDEND": [0.0, 0.0, 0.0],
        }
    )
    animation = create_multi_line_animation(
        [{"name": "SBER", "color": "#FFD166", "data": data_frame}],
        target_duration=3,
        fps=1,
        final_frame_duration=0,
        use_gradient=True,
    )

    try:
        animation._func(0)
        animation._draw_was_started = True
        first_xlim = animation._fig.axes[0].get_xlim()
        line = animation._fig.axes[0].lines[0]

        animation._func(1)
        middle_xlim = animation._fig.axes[0].get_xlim()
        gradient_collections = [
            collection
            for collection in animation._fig.axes[0].collections
            if collection.__class__.__name__ == "LineCollection"
        ]
        middle_gradient_segments = gradient_collections[-1].get_segments()

        animation._func(2)
        final_xlim = animation._fig.axes[0].get_xlim()

        start_num = mdates.date2num(data_frame["TRADEDATE"].iloc[0])
        assert list(line.get_xdata()) == []
        assert line.get_alpha() == 0.0
        assert abs(middle_gradient_segments[-1][-1][0] - mdates.date2num(data_frame["TRADEDATE"].iloc[1])) < 1e-6
        assert gradient_collections
        assert first_xlim[0] == start_num
        assert first_xlim == middle_xlim == final_xlim
    finally:
        plt.close(animation._fig)


def test_prefix_y_limits_match_visible_prefix_values_with_nans() -> None:
    values = pd.DataFrame(
        {
            "A": [None, 10.0, 7.0, None],
            "B": [None, None, 20.0, 5.0],
        }
    )

    prefix_min, prefix_max = _prefix_y_limits(values)

    assert pd.isna(prefix_min.iloc[0])
    assert pd.isna(prefix_max.iloc[0])
    assert prefix_min.iloc[1:].tolist() == [10.0, 7.0, 5.0]
    assert prefix_max.iloc[1:].tolist() == [10.0, 20.0, 20.0]


def test_animation_reuses_duplicate_final_hold_frame_artists() -> None:
    import matplotlib.pyplot as plt

    data_frame = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2021-12-17", "2022-01-17", "2022-02-17"]),
            "CLOSE": [100.0, 140.0, 90.0],
            "DIVIDEND": [0.0, 0.0, 0.0],
        }
    )
    animation = create_multi_line_animation(
        [{"name": "SBER", "color": "#FFD166", "data": data_frame}],
        target_duration=1,
        fps=1,
        final_frame_duration=2,
        use_gradient=True,
    )

    try:
        first_final_artists = animation._func(1)
        first_collection_ids = [id(collection) for collection in animation._fig.axes[0].collections]
        second_final_artists = animation._func(2)
        second_collection_ids = [id(collection) for collection in animation._fig.axes[0].collections]

        assert second_final_artists is first_final_artists
        assert second_collection_ids == first_collection_ids
    finally:
        animation._draw_was_started = True
        plt.close(animation._fig)


def test_animation_keeps_line_gradient_and_fill_on_same_frame_slice() -> None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    data_frame = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2021-12-17", "2022-01-17", "2022-02-17"]),
            "CLOSE": [100.0, 140.0, 90.0],
            "DIVIDEND": [0.0, 0.0, 0.0],
        }
    )
    animation = create_multi_line_animation(
        [{"name": "SBER", "color": "#FFD166", "data": data_frame}],
        target_duration=3,
        fps=1,
        final_frame_duration=0,
        use_gradient=True,
    )

    try:
        animation._func(1)
        animation._draw_was_started = True
        ax = animation._fig.axes[0]
        line = animation._fig.axes[0].lines[0]
        fill_collections = [
            collection
            for collection in animation._fig.axes[0].collections
            if collection.get_alpha() == 0.045
        ]
        gradient_collections = [
            collection
            for collection in animation._fig.axes[0].collections
            if collection.__class__.__name__ == "LineCollection"
        ]
        gradient_segments = gradient_collections[-1].get_segments()
        fill_right = fill_collections[-1].get_paths()[0].vertices[:, 0].max()
        price_label = next(text for text in ax.texts if text.get_text().startswith("SBER:"))
        expected_label_x = data_frame["TRADEDATE"].iloc[1] + pd.Timedelta(days=62 * 0.025)

        assert list(line.get_xdata()) == []
        assert line.get_alpha() == 0.0
        assert fill_collections
        assert gradient_collections
        assert abs(gradient_segments[-1][-1][0] - mdates.date2num(data_frame["TRADEDATE"].iloc[1])) < 1e-6
        assert abs(fill_right - mdates.date2num(data_frame["TRADEDATE"].iloc[1])) < 1e-6
        assert price_label.get_position()[1] == 140.0
        assert price_label.get_position()[0] == expected_label_x
    finally:
        plt.close(animation._fig)


def test_precomputed_event_ranges_match_active_events() -> None:
    events = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2020-01-01", "2020-01-15", "2020-02-01"]),
            "EVENT_NAME": ["OIL_DROP", "OIL_DROP", "FOMC"],
            "EVENT_IMPACT": [-2, -2, 1],
        }
    )
    frame_date = pd.Timestamp("2020-01-10")

    ranges = _event_ranges(events)

    assert _active_event_ranges(ranges, frame_date) == _active_events(events, frame_date)
    assert _active_event_ranges(ranges, frame_date) == [
        (pd.Timestamp("2020-01-01"), frame_date, "OIL DROP", -2)
    ]


def test_event_ranges_handle_missing_or_invalid_impact() -> None:
    events = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2020-01-01", "2020-01-15"]),
            "EVENT_NAME": ["FOMC", "OIL_DROP"],
            "EVENT_IMPACT": [None, "bad"],
        }
    )

    ranges = _event_ranges(events)

    assert ranges == [
        (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-01"), "FOMC", 0),
        (pd.Timestamp("2020-01-15"), pd.Timestamp("2020-01-15"), "OIL DROP", 0),
    ]


def test_event_ranges_default_to_neutral_impact_when_column_missing() -> None:
    events = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2020-01-01"]),
            "EVENT_NAME": ["FOMC"],
        }
    )

    assert _event_ranges(events) == [
        (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-01"), "FOMC", 0)
    ]


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


def test_combine_data_uses_price_basis_for_close_return_not_savings() -> None:
    data_list = [
        {
            "name": "SBER",
            "color": "#FFD166",
            "data": pd.DataFrame(
                {
                    "TRADEDATE": pd.to_datetime(["2020-01-01", "2020-01-02"]),
                    "CLOSE": [100.0, 110.0],
                    "DIVIDEND": [0.0, 0.0],
                    "savings": [10_000.0, 10_000.0],
                }
            ),
        }
    ]

    combined, _value_columns, _dividend_columns, basis_columns = _combine_data(data_list, "CLOSE")

    assert basis_columns == {}
    assert _return_summary("SBER", combined["SBER"], None) == "SBER: +10.0%"


def test_combine_data_does_not_forward_fill_flat_tail_after_ticker_history_ends() -> None:
    data_list = [
        {
            "name": "SHORT",
            "color": "#FFD166",
            "data": pd.DataFrame(
                {
                    "TRADEDATE": pd.to_datetime(["2020-01-01", "2020-01-02"]),
                    "CAPITAL_REINVEST": [100.0, 120.0],
                    "DIVIDEND": [0.0, 0.0],
                    "savings": [100.0, 100.0],
                }
            ),
        },
        {
            "name": "LONG",
            "color": "#00D1B2",
            "data": pd.DataFrame(
                {
                    "TRADEDATE": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
                    "CAPITAL_REINVEST": [100.0, 110.0, 130.0],
                    "DIVIDEND": [0.0, 0.0, 0.0],
                    "savings": [100.0, 100.0, 100.0],
                }
            ),
        },
    ]

    combined, _value_columns, _dividend_columns, basis_columns = _combine_data(data_list, "CAPITAL_REINVEST")

    assert combined["SHORT"].tolist()[:2] == [100.0, 120.0]
    assert pd.isna(combined["SHORT"].iloc[-1])
    assert pd.isna(combined[basis_columns["SHORT"]].iloc[-1])


def test_generate_unique_colors_shuffles_palette(monkeypatch) -> None:
    class ReverseRandom:
        def shuffle(self, values: list[str]) -> None:
            values.reverse()

    monkeypatch.setattr(dataset_builder.random, "SystemRandom", lambda: ReverseRandom())

    assert dataset_builder.generate_unique_colors(2) == ["#A3E635", "#F72585"]


def test_chart_themes_include_default_and_optional_presets() -> None:
    assert get_theme_names() == ("default", "aurora", "studio")
    assert get_chart_theme("default").figure_bg == "#0D0E11"
    assert get_chart_theme("aurora").name == "aurora"
    assert get_chart_theme("studio").invested_color == "#9BA3AF"


def test_generate_unique_colors_uses_theme_palette(monkeypatch) -> None:
    class IdentityRandom:
        def shuffle(self, _values: list[str]) -> None:
            return None

    monkeypatch.setattr(dataset_builder.random, "SystemRandom", lambda: IdentityRandom())

    assert dataset_builder.generate_unique_colors(2, palette=get_chart_theme("studio").palette) == ["#F4D35E", "#33C7A7"]
