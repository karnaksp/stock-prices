from __future__ import annotations

from datetime import date
import random

from stock_prices._internal.content_universe import (
    TickerUniverseEntry,
    build_random_content_idea,
    build_weekly_content_plan,
    clear_universe_cache,
    configured_universe,
    entries_for_category,
    resolve_universe_category,
    universe_category_label,
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


def test_random_request_respects_requested_count() -> None:
    idea = build_random_content_idea("drama", count=1, rng=random.Random(3), today=date(2026, 6, 1))

    parsed = parse_telegram_video_request(
        idea.request,
        RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    assert len(idea.tickers) == 1
    assert len(parsed.request.ticker_specs) == 1


def test_random_request_clamps_count_to_three() -> None:
    idea = build_random_content_idea("ru", count=99, rng=random.Random(9), today=date(2026, 6, 1))

    parsed = parse_telegram_video_request(
        idea.request,
        RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    assert len(idea.tickers) == 3
    assert len(parsed.request.ticker_specs) == 3


def test_random_mixed_request_can_use_custom_universe() -> None:
    universe = (
        TickerUniverseEntry("AAA", "stock", "shares", "AAA", date(2010, 1, 1), None, ("ru", "banks")),
        TickerUniverseEntry("BBB", "stock", "shares", "BBB", date(2010, 1, 1), None, ("ru", "retail")),
        TickerUniverseEntry("CCC", "global", "crypto", "CCC", date(2014, 1, 1), None, ("global", "crypto")),
    )

    idea = build_random_content_idea(None, count=3, rng=random.Random(1), today=date(2026, 6, 1), universe=universe)

    assert len(idea.tickers) == 3
    assert idea.category == "mixed"
    assert "|global|crypto" in idea.request


def test_universe_category_resolver_is_independent_from_presets() -> None:
    assert resolve_universe_category("stocks") == "stocks"
    assert resolve_universe_category("mixed") is None
    assert universe_category_label("crypto") == "крипто"


def test_configured_universe_loads_metadata_file(monkeypatch, tmp_path) -> None:
    universe_file = tmp_path / "universe.json"
    universe_file.write_text(
        """
[
  {
    "ticker": "TEST",
    "engine": "stock",
    "market": "shares",
    "title": "Тестовая акция",
    "available_from": "2012-01-03",
    "available_to": null,
    "categories": ["ru", "test_story"],
    "tags": ["board:TQBR"]
  }
]
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("STOCK_PRICES_UNIVERSE_FILE", str(universe_file))
    clear_universe_cache()
    try:
        tickers = {entry.ticker for entry in configured_universe()}
        idea = build_random_content_idea("test_story", count=1, rng=random.Random(1), today=date(2026, 6, 1))
    finally:
        clear_universe_cache()

    assert "TEST" in tickers
    assert idea.tickers == ("TEST",)
    assert "TEST from=2012-01-03" in idea.request


def test_weekly_content_plan_is_stable_for_same_week() -> None:
    first = build_weekly_content_plan(date(2026, 6, 1))
    second = build_weekly_content_plan(date(2026, 6, 6))

    assert len(first) == 7
    assert [item.request for item in first] == [item.request for item in second]
    assert all(f"theme={item.theme}" in item.request and " title=" in item.request for item in first)
    assert all(1 <= len(item.tickers) <= 3 for item in first)


def test_weekly_content_plan_respects_explicit_category() -> None:
    plan = build_weekly_content_plan(date(2026, 6, 1), days=5, count=1, categories=("metals",))

    assert len(plan) == 5
    assert all(item.category == "metals" for item in plan)
    assert all(len(item.tickers) == 1 for item in plan)
