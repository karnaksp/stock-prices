from __future__ import annotations

import pandas as pd

from stock_prices._internal import models
from stock_prices._internal.core import models as core_models
from stock_prices._internal.lib import dataset_builder
from stock_prices._internal.lib import validators as legacy_validators
from stock_prices._internal.market_data import validators as market_validators
from stock_prices._internal.portfolio.calculations import calculate_capital_with_reinvest
from stock_prices._internal.rendering.filenames import safe_video_stem


def test_legacy_models_reexport_core_models() -> None:
    assert models.TickerSpec is core_models.TickerSpec
    assert models.RenderSettings is core_models.RenderSettings
    assert models.VideoRequest is core_models.VideoRequest
    assert models.parse_ticker_spec is core_models.parse_ticker_spec


def test_legacy_dataset_builder_reexports_portfolio_calculation() -> None:
    assert dataset_builder.calculate_capital_with_reinvest is calculate_capital_with_reinvest


def test_legacy_validators_reexport_market_validators() -> None:
    assert legacy_validators.validate_float_value is market_validators.validate_float_value
    assert legacy_validators.validate_quote_structure is market_validators.validate_quote_structure


def test_safe_video_stem_keeps_existing_filename_behavior() -> None:
    specs = [models.TickerSpec("GC=F", "global", "metals"), models.TickerSpec("LKOH")]

    assert safe_video_stem(specs) == "GC_F_LKOH"
    assert models.safe_video_stem(specs) == "GC_F_LKOH"


def test_portfolio_calculation_preserves_monthly_investment_behavior() -> None:
    data = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-01"]),
            "CLOSE": [100.0, 100.0, 100.0],
            "DIVIDEND": [0.0, 0.0, 0.0],
        }
    )

    result = calculate_capital_with_reinvest(data, initial_investment=0, monthly_investment=30_000)

    assert result["savings"].tolist() == [0.0, 30_000.0, 60_000.0]
    assert result["CAPITAL_REINVEST"].tolist() == [0.0, 30_000.0, 60_000.0]
