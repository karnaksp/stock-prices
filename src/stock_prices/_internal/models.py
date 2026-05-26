from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class TickerSpec:
    ticker: str
    engine: str = "stock"
    market: str = "shares"

    def __post_init__(self) -> None:
        ticker = self.ticker.strip().upper()
        engine = self.engine.strip().lower()
        market = self.market.strip().lower()
        if not ticker:
            msg = "Ticker must not be empty."
            raise ValueError(msg)
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "engine", engine)
        object.__setattr__(self, "market", market)

    def as_dict(self) -> dict[str, str]:
        return {"ticker": self.ticker, "engine": self.engine, "market": self.market}


@dataclass(frozen=True)
class RenderSettings:
    start_date: date
    end_date: date
    value_col: str = "CAPITAL_REINVEST"
    duration: int = 30
    fps: int = 20
    currency: str = "RUB"
    title: str = ""
    under_title: str = ""
    use_gradient: bool = False
    show_legend: bool = True
    initial_investment: int = 10000
    monthly_investment: int = 0
    yearly_investment: int = 0
    with_investments: bool = False
    output_dir: Path = Path("animations")

    @property
    def no_legend(self) -> bool:
        return not self.show_legend


@dataclass(frozen=True)
class VideoRequest:
    ticker_specs: list[TickerSpec]
    render: RenderSettings

    def __post_init__(self) -> None:
        if not self.ticker_specs:
            msg = "At least one ticker is required."
            raise ValueError(msg)
        if self.render.end_date < self.render.start_date:
            msg = "end_date must be greater than or equal to start_date."
            raise ValueError(msg)


def parse_ticker_spec(
    spec: str,
    default_engine: str = "stock",
    default_market: str = "shares",
) -> TickerSpec:
    parts = [part.strip() for part in re.split(r"[|,\s]+", spec.strip()) if part.strip()]
    if len(parts) == 1:
        return TickerSpec(parts[0], default_engine, default_market)
    if len(parts) == 3:
        return TickerSpec(parts[0], parts[1], parts[2])

    msg = f"Invalid ticker spec '{spec}'. Use TICKER or TICKER|ENGINE|MARKET."
    raise ValueError(msg)


def safe_video_stem(specs: list[TickerSpec]) -> str:
    stem = "_".join(re.sub(r"[^A-Z0-9._-]+", "_", spec.ticker.upper()) for spec in specs)
    return stem or "stock_prices"
