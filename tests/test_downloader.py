from __future__ import annotations

import pandas as pd
import pytest

from stock_prices._internal.lib import downloader


def test_download_history_returns_in_memory_frames(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_download(*_args, **_kwargs) -> pd.DataFrame:
        return pd.DataFrame({"TRADEDATE": pd.to_datetime(["2010-01-04"]), "CLOSE": [100.0]})

    monkeypatch.setattr(downloader, "download_global_data", fake_download)

    result = downloader.download_ticker_history(
        [{"ticker": "GC=F", "engine": "global", "market": "metals"}],
        pd.Timestamp("2010-01-01"),
        pd.Timestamp("2026-05-27"),
        "RUB",
    )

    assert list(result) == [("global", "metals", "GC=F")]
    assert result[("global", "metals", "GC=F")]["CLOSE"].tolist() == [100.0]
    assert list(tmp_path.rglob("*.parquet")) == []


def test_download_history_raises_after_source_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(downloader.time, "sleep", lambda _seconds: None)

    def fail_download(*_args, **_kwargs) -> None:
        raise ValueError("temporary source failure")

    monkeypatch.setattr(downloader, "download_global_data", fail_download)

    with pytest.raises(ValueError, match="temporary source failure"):
        downloader.download_ticker_history(
            [{"ticker": "GC=F", "engine": "global", "market": "metals"}],
            pd.Timestamp("2010-01-01"),
            pd.Timestamp("2026-05-27"),
            "RUB",
        )
