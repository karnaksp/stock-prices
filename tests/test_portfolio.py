from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from stock_prices._internal.portfolio import InvestmentPlan, calculate_capital_with_reinvest


def test_investment_plan_reads_render_args_and_currency() -> None:
    args = SimpleNamespace(
        initial_investment=0,
        monthly_investment=30_000,
        yearly_investment=120_000,
        currency="rub",
    )

    plan = InvestmentPlan.from_args(args)

    assert plan.initial == 0
    assert plan.monthly == 30_000
    assert plan.yearly == 120_000
    assert plan.currency == "RUB"
    assert plan.has_recurring_investments


def test_monthly_investment_tracks_actual_contributions() -> None:
    data = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-01"]),
            "CLOSE": [100.0, 100.0, 100.0],
            "DIVIDEND": [0.0, 0.0, 0.0],
        }
    )

    result = calculate_capital_with_reinvest(
        data,
        investment_plan=InvestmentPlan(initial=0, monthly=30_000, currency="RUB"),
    )

    assert result["savings"].tolist() == [0.0, 30_000.0, 60_000.0]
    assert result["CAPITAL_REINVEST"].tolist() == [0.0, 30_000.0, 60_000.0]
    assert result["investment_currency"].tolist() == ["RUB", "RUB", "RUB"]


def test_rub_plan_for_converted_foreign_asset_uses_rub_contribution_basis() -> None:
    converted_prices = pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-01"]),
            "CLOSE": [9_000.0, 12_000.0, 15_000.0],
            "DIVIDEND": [0.0, 0.0, 0.0],
        }
    )

    result = calculate_capital_with_reinvest(
        converted_prices,
        investment_plan=InvestmentPlan(initial=0, monthly=30_000, currency="RUB"),
    )

    assert result["savings"].tolist() == [0.0, 30_000.0, 60_000.0]
    assert result["investment_currency"].iloc[-1] == "RUB"
    assert round(float(result["shares"].iloc[-1]), 4) == 4.5
