from __future__ import annotations

import pandas as pd
import pytest

from stock_prices._internal.lib import downloader


def test_download_history_uses_recent_cache_after_source_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(downloader.time, "sleep", lambda _seconds: None)

    cache_dir = tmp_path / "global" / "metals" / "GC=F"
    cache_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "TRADEDATE": pd.to_datetime(["2010-01-04", "2026-05-27"]),
            "CLOSE": [100.0, 200.0],
        }
    ).to_parquet(cache_dir / "20100101_20260527.parquet", index=False)

    def fail_download(*_args, **_kwargs) -> None:
        raise ValueError("temporary source failure")

    monkeypatch.setattr(downloader, "download_global_data", fail_download)

    downloader.download_ticker_history(
        [{"ticker": "GC=F", "engine": "global", "market": "metals"}],
        pd.Timestamp("2010-01-01"),
        pd.Timestamp("2026-05-27"),
        "RUB",
    )


def test_download_history_raises_without_cache_after_source_failure(monkeypatch, tmp_path) -> None:
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
