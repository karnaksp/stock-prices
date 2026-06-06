from __future__ import annotations

from datetime import date
import random

from stock_prices._internal.content_universe import (
    build_random_content_idea,
    build_weekly_content_plan,
    entries_for_category,
)
from stock_prices._internal.models import RenderSettings
from stock_prices._internal.telegram_requests import parse_telegram_video_request


def test_entries_for_category_returns_ru_niche_stories() -> None:
    tickers = {entry.ticker for entry in entries_for_category("alcohol")}

    assert {"BELU", "ABRD", "KLVZ"} <= tickers


def test_random_global_stock_request_keeps_explicit_engine_and_market() -> None:
    idea = build_random_content_idea("stocks", count=2, rng=random.Random(7), today=date(2026, 6, 1))

    assert "|global|stocks" in idea.request

    parsed = parse_telegram_video_request(
        idea.request,
        RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    assert parsed.request.ticker_specs
    assert all(spec.engine == "global" and spec.market == "stocks" for spec in parsed.request.ticker_specs)


def test_weekly_content_plan_is_stable_for_same_week() -> None:
    first = build_weekly_content_plan(date(2026, 6, 1))
    second = build_weekly_content_plan(date(2026, 6, 6))

    assert len(first) == 7
    assert [item.request for item in first] == [item.request for item in second]
    assert all(f"theme={item.theme}" in item.request and " title=" in item.request for item in first)
