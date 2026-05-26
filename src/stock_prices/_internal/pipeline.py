from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from stock_prices._internal.models import VideoRequest
from stock_prices._internal.lib.downloader import download_ticker_history
from stock_prices._internal.lib.plotting import render_charts


def generate_video(request: VideoRequest) -> Path:
    specs = [spec.as_dict() for spec in request.ticker_specs]
    start_date = pd.Timestamp(request.render.start_date).normalize()
    end_date = pd.Timestamp(request.render.end_date).normalize()

    logging.info("Processing %s instruments", len(specs))
    logging.info("Date range: %s -> %s", start_date.date(), end_date.date())
    download_ticker_history(specs, start_date, end_date, request.render.currency)
    output_path = render_charts(request.render, specs, start_date, end_date)
    logging.info("Done.")
    return Path(output_path)
