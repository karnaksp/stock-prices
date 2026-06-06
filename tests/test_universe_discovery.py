from __future__ import annotations

from datetime import date

from stock_prices._internal.market_data import universe_discovery


def test_collect_moex_share_universe_builds_metadata_without_prices(monkeypatch) -> None:
    def fake_get_board_securities(_session, **_kwargs):
        return [
            {"SECID": "SBER", "SHORTNAME": "Сбербанк", "SECNAME": "Сбербанк"},
            {"SECID": "MTLR", "SHORTNAME": "Мечел", "SECNAME": "Мечел"},
        ]

    def fake_get_market_candle_borders(_session, security, **_kwargs):
        return [
            {
                "begin": "2010-01-11 00:00:00",
                "end": "2026-06-01 00:00:00" if security == "SBER" else "2025-12-30 00:00:00",
            }
        ]

    monkeypatch.setattr(universe_discovery.apimoex, "get_board_securities", fake_get_board_securities)
    monkeypatch.setattr(universe_discovery.apimoex, "get_market_candle_borders", fake_get_market_candle_borders)

    entries = universe_discovery.collect_moex_share_universe(
        object(),
        today=date(2026, 6, 6),
        include_periods=True,
    )

    assert [entry.ticker for entry in entries] == ["SBER", "MTLR"]
    assert entries[0].available_from == date(2010, 1, 11)
    assert entries[0].available_to == date(2026, 6, 1)
    assert "banks" in entries[0].categories
    assert "commodities" in entries[1].categories
    assert entries[0].tags == ("board:TQBR",)
