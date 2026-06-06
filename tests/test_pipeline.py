from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from stock_prices._internal import pipeline
from stock_prices._internal.models import RenderSettings, TickerSpec, VideoRequest


def test_generate_video_logs_structured_stages(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    def fake_download(_specs, _start_date, _end_date, _currency) -> dict:
        return {}

    def fake_render(_render, _specs, _start_date, _end_date, _source_data) -> Path:
        return Path("animations/LKOH.mp4")

    monkeypatch.setattr(pipeline, "download_ticker_history", fake_download)
    monkeypatch.setattr(pipeline, "render_charts", fake_render)
    request = VideoRequest(
        ticker_specs=[TickerSpec("LKOH")],
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    with caplog.at_level("INFO"):
        assert pipeline.generate_video(request, job_id="tg-1") == Path("animations/LKOH.mp4")

    events = [json.loads(record.message) for record in caplog.records if record.message.startswith("{")]
    assert ("request", "started") in {(event["event"], event["stage"]) for event in events}
    assert ("download", "completed") in {(event["event"], event["stage"]) for event in events}
    assert ("render", "completed") in {(event["event"], event["stage"]) for event in events}
    assert all(event.get("job_id") == "tg-1" for event in events)
