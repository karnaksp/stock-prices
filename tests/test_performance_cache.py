from __future__ import annotations

import pandas as pd

from stock_prices._internal.lib import events, global_data


def test_load_events_uses_cache_but_returns_independent_frames(tmp_path, monkeypatch) -> None:
    events_file = tmp_path / "events.json"
    events_file.write_text(
        '[{"start":"2020-01-01","end":"2020-01-02","event":"A","type":"macro","impact":1}]',
        encoding="utf-8",
    )
    calls = {"count": 0}
    real_read_json = pd.read_json

    def counted_read_json(*args, **kwargs):
        calls["count"] += 1
        return real_read_json(*args, **kwargs)

    events._load_events_cached.cache_clear()
    monkeypatch.setattr(pd, "read_json", counted_read_json)

    first = events.load_events(events_file)
    first.loc[0, "event"] = "changed"
    second = events.load_events(events_file)

    assert calls["count"] == 1
    assert second.loc[0, "event"] == "A"


def test_cached_rub_rate_reuses_currency_converter(monkeypatch) -> None:
    class FakeConverter:
        def __init__(self) -> None:
            self.calls = 0

        def convert(self, _amount, _base, _target, date):
            self.calls += 1
            assert str(date) == "2024-01-02"
            return 91.5

    converter = FakeConverter()
    global_data._cached_rub_rate.cache_clear()
    monkeypatch.setattr(global_data, "_currency_converter", lambda: converter)

    assert global_data._cached_rub_rate("USD", "2024-01-02") == 91.5
    assert global_data._cached_rub_rate("USD", "2024-01-02") == 91.5
    assert converter.calls == 1
