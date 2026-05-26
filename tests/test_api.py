from __future__ import annotations

from datetime import date

import pytest

import stock_prices
from stock_prices import RenderSettings, TickerSpec, VideoRequest, parse_ticker_spec


def test_public_api_exports_core_entrypoints() -> None:
    assert "main" in stock_prices.__all__
    assert "generate_video" in stock_prices.__all__
    assert "VideoRequest" in stock_prices.__all__


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("LKOH", TickerSpec("LKOH", "stock", "shares")),
        ("aapl|global|shares", TickerSpec("AAPL", "global", "shares")),
        ("SBER stock shares", TickerSpec("SBER", "stock", "shares")),
    ],
)
def test_parse_ticker_spec(raw: str, expected: TickerSpec) -> None:
    assert parse_ticker_spec(raw) == expected


def test_video_request_requires_tickers() -> None:
    settings = RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2))
    with pytest.raises(ValueError, match="At least one ticker"):
        VideoRequest([], settings)


def test_video_request_rejects_invalid_dates() -> None:
    settings = RenderSettings(start_date=date(2020, 1, 2), end_date=date(2020, 1, 1))
    with pytest.raises(ValueError, match="end_date"):
        VideoRequest([TickerSpec("LKOH")], settings)
