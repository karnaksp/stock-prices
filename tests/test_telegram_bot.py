from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_prices._internal import telegram_bot
from stock_prices._internal.models import RenderSettings
from stock_prices._internal.telegram_requests import parse_telegram_video_request
from stock_prices._internal.telegram_bot import TelegramBotSettings, handle_ticker_message


class FakeClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.videos: list[tuple[int, Path, str]] = []

    def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))

    def send_video(self, chat_id: int, video_path: Path, caption: str) -> None:
        self.videos.append((chat_id, video_path, caption))


def test_handle_ticker_message_generates_video(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fake_generate(request):
        assert request.ticker_specs[0].ticker == "LKOH"
        return Path("animations/LKOH.mp4")

    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)
    handle_ticker_message(client, settings, 123, "lkoh")

    assert client.messages[0][0] == 123
    assert "Генерирую видео: LKOH" in client.messages[0][1]
    assert client.videos == [(123, Path("animations/LKOH.mp4"), "LKOH: 2020-01-01 - 2020-01-02")]


def test_handle_ticker_message_respects_allowed_chat_ids() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        allowed_chat_ids={1},
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 2, "LKOH")

    assert client.messages == [(2, "This chat is not allowed to use this bot.")]
    assert client.videos == []


def test_parse_telegram_video_request_accepts_human_message() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("lkoh sber 2020 2024 gradient duration=12 fps=24 close", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["LKOH", "SBER"]
    assert parsed.request.render.start_date == date(2020, 1, 1)
    assert parsed.request.render.end_date == date(2024, 12, 31)
    assert parsed.request.render.duration == 12
    assert parsed.request.render.fps == 24
    assert parsed.request.render.value_col == "CLOSE"
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_accepts_global_currency_shortcuts() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("aapl global usd", base)

    assert parsed.request.ticker_specs[0].ticker == "AAPL"
    assert parsed.request.ticker_specs[0].engine == "global"
    assert parsed.request.render.currency == "USD"


def test_parse_telegram_video_request_infers_yfinance_assets() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("gold btc eurusd GC=F золото", base)

    assert [(spec.ticker, spec.engine, spec.market) for spec in parsed.request.ticker_specs] == [
        ("GC=F", "global", "metals"),
        ("BTC-USD", "global", "crypto"),
        ("EURUSD=X", "global", "currency"),
        ("GC=F", "global", "futures"),
        ("GC=F", "global", "metals"),
    ]


def test_parse_telegram_video_request_understands_moex_futures() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("SiH4 futures", base)

    assert parsed.request.ticker_specs[0].ticker == "SIH4"
    assert parsed.request.ticker_specs[0].engine == "futures"
    assert parsed.request.ticker_specs[0].market == "forts"


def test_parse_telegram_video_request_accepts_investment_amounts_for_metals() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request(
        "gold silver palladium 2018-2026 RUB capital invest initial=0 monthly=30000 gradient",
        base,
    )

    assert [(spec.ticker, spec.engine, spec.market) for spec in parsed.request.ticker_specs] == [
        ("GC=F", "global", "metals"),
        ("SI=F", "global", "metals"),
        ("PA=F", "global", "metals"),
    ]
    assert parsed.request.render.start_date == date(2018, 1, 1)
    assert parsed.request.render.end_date == date(2026, 12, 31)
    assert parsed.request.render.currency == "RUB"
    assert parsed.request.render.value_col == "CAPITAL_REINVEST"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.initial_investment == 0
    assert parsed.request.render.monthly_investment == 30_000
    assert parsed.request.render.use_gradient is True
