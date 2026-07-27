from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd

from stock_prices._internal.models import VideoRequest
from stock_prices._internal.lib.downloader import download_ticker_history
from stock_prices._internal.lib.events import add_events, timeline_events_frame
from stock_prices._internal.lib.plotting import render_charts


def log_event(event: str, stage: str, **fields: Any) -> None:
    payload = {"event": event, "stage": stage}
    payload.update({key: value for key, value in fields.items() if value is not None})
    logging.info(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def generate_video(request: VideoRequest, job_id: str | None = None) -> Path:
    specs = [spec.as_dict() for spec in request.ticker_specs]
    start_date = pd.Timestamp(request.render.start_date).normalize()
    end_date = pd.Timestamp(request.render.end_date).normalize()

    log_event(
        "request",
        "started",
        job_id=job_id,
        ticker_count=len(specs),
        start_date=start_date.date(),
        end_date=end_date.date(),
        currency=request.render.currency,
    )
    logging.info("Processing %s instruments", len(specs))
    logging.info("Date range: %s -> %s", start_date.date(), end_date.date())

    download_started_at = time.monotonic()
    log_event("download", "started", job_id=job_id, ticker_count=len(specs), currency=request.render.currency)
    try:
        source_data = download_ticker_history(specs, start_date, end_date, request.render.currency)
    except Exception as exc:
        log_event("download", "failed", job_id=job_id, elapsed_ms=_elapsed_ms(download_started_at), error=str(exc))
        log_event("request", "failed", job_id=job_id, error=str(exc))
        raise
    log_event("download", "completed", job_id=job_id, elapsed_ms=_elapsed_ms(download_started_at))
    request_events = timeline_events_frame(request.render.timeline_events)
    for data_frame in source_data.values():
        add_events(data_frame, request_events)
    log_event("events", "prepared", job_id=job_id, event_count=len(request.render.timeline_events))

    render_started_at = time.monotonic()
    log_event("render", "started", job_id=job_id, output_dir=str(request.render.output_dir))
    try:
        output_path = render_charts(request.render, specs, start_date, end_date, source_data)
    except Exception as exc:
        log_event("render", "failed", job_id=job_id, elapsed_ms=_elapsed_ms(render_started_at), error=str(exc))
        log_event("request", "failed", job_id=job_id, error=str(exc))
        raise
    log_event("render", "completed", job_id=job_id, elapsed_ms=_elapsed_ms(render_started_at), output_path=str(output_path))
    log_event("request", "completed", job_id=job_id, output_path=str(output_path))
    logging.info("Done.")
    return Path(output_path)
