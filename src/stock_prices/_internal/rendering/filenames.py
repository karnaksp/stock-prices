from __future__ import annotations

import re

from stock_prices._internal.core.models import TickerSpec


def safe_video_stem(specs: list[TickerSpec]) -> str:
    stem = "_".join(re.sub(r"[^A-Z0-9._-]+", "_", spec.ticker.upper()) for spec in specs)
    return stem or "stock_prices"
