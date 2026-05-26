"""Stock Price package.

Animated plots
"""

from __future__ import annotations

from stock_prices._internal.cli import get_parser, main, parse_arguments, request_from_args
from stock_prices._internal.models import RenderSettings, TickerSpec, VideoRequest, parse_ticker_spec
from stock_prices._internal.pipeline import generate_video

__all__: list[str] = [
    "RenderSettings",
    "TickerSpec",
    "VideoRequest",
    "generate_video",
    "get_parser",
    "main",
    "parse_arguments",
    "parse_ticker_spec",
    "request_from_args",
]
