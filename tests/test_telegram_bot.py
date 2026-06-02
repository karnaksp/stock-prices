from __future__ import annotations

from datetime import date
from pathlib import Path
import time

import pytest
import requests

from stock_prices._internal import telegram_bot
from stock_prices._internal.models import RenderSettings
from stock_prices._internal.telegram_presets import PRESETS, format_pulse_post
from stock_prices._internal.telegram_requests import parse_telegram_video_request
from stock_prices._internal.telegram_bot import TelegramApiError, TelegramBotSettings, TelegramClient, cleanup_old_outputs, handle_ticker_message


class FakeClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.message_markups: list[dict | None] = []
        self.videos: list[tuple[int, Path, str]] = []
        self.callback_answers: list[tuple[str, str]] = []

    def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
        self.messages.append((chat_id, text))
        self.message_markups.append(reply_markup)

    def send_video(self, chat_id: int, video_path: Path, caption: str) -> None:
        self.videos.append((chat_id, video_path, caption))

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        self.callback_answers.append((callback_query_id, text))


def test_handle_ticker_message_generates_video(monkeypatch) -> None:
    client = FakeClient()
    seen_job_ids = []
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fake_generate(request, job_id=None):
        assert request.ticker_specs[0].ticker == "LKOH"
        seen_job_ids.append(job_id)
        return Path("animations/LKOH.mp4")

    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)
    handle_ticker_message(client, settings, 123, "lkoh", job_id="tg-1")

    assert client.messages[0][0] == 123
    assert "Генерирую видео: LKOH" in client.messages[0][1]
    assert seen_job_ids == ["tg-1"]
    assert len(client.messages) == 1
    assert client.videos == [(123, Path("animations/LKOH.mp4"), "LKOH: 2020-01-01 - 2020-01-02")]


def test_run_telegram_bot_queues_generation_once(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 42, "message": {"text": "LKOH", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(_request, job_id=None):
        assert job_id == "tg-42"
        return Path("animations/LKOH.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert any("queued" in message for _chat_id, message in client.messages)
    assert any("Генерирую видео: LKOH" in message for _chat_id, message in client.messages)
    assert client.videos == [(123, Path("animations/LKOH.mp4"), "LKOH: 2020-01-01 - 2020-01-02")]


def test_run_telegram_bot_queues_preset_from_inline_button(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 43,
                    "callback_query": {
                        "id": "callback-1",
                        "data": "preset:metals",
                        "message": {"chat": {"id": 123}},
                    },
                }
            ]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        assert job_id == "tg-43"
        assert [spec.ticker for spec in request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
        return Path("animations/metals.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-1", "Сценарий поставлен в очередь.")]
    assert any("queued" in message for _chat_id, message in client.messages)
    assert any("Текст для Пульса" in message for _chat_id, message in client.messages)
    assert client.videos == [(123, Path("animations/metals.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-05-27")]


def test_run_telegram_bot_queues_draft_preset_from_inline_button(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 44,
                    "callback_query": {
                        "id": "callback-2",
                        "data": "preset:metals:draft",
                        "message": {"chat": {"id": 123}},
                    },
                }
            ]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=True),
    )

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        assert job_id == "tg-44"
        assert [spec.ticker for spec in request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
        assert request.render.duration == 4
        assert request.render.fps == 8
        assert request.render.use_gradient is False
        return Path("animations/metals-draft.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers[0][0] == "callback-2"
    assert any("4s/8fps" in message for _chat_id, message in client.messages)
    assert client.videos == [(123, Path("animations/metals-draft.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-05-27")]


def test_cleanup_old_outputs_removes_old_mp4_but_keeps_current(tmp_path: Path) -> None:
    old_video = tmp_path / "old.mp4"
    current_video = tmp_path / "current.mp4"
    old_video.write_bytes(b"old")
    current_video.write_bytes(b"current")
    old_mtime = time.time() - 3 * 24 * 60 * 60
    old_video.touch()
    current_video.touch()
    import os

    os.utime(old_video, (old_mtime, old_mtime))

    removed = cleanup_old_outputs(tmp_path, retention_days=1, keep={current_video})

    assert removed == [old_video]
    assert not old_video.exists()
    assert current_video.exists()


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


def test_help_text_mentions_investments_and_themes() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/help")

    help_text = client.messages[0][1]
    assert "monthly=30000" in help_text
    assert "shorts" in help_text
    assert "draft" in help_text
    assert "/drafts" in help_text
    assert "/черновики" in help_text
    assert "пресет металлы" in help_text
    assert "theme=default|aurora|studio" in help_text
    assert "SiH4 futures" in help_text
    assert "preset neweconomy" in help_text


def test_handle_ticker_message_lists_pulse_presets() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/ideas")

    preset_text = client.messages[0][1]
    assert "Готовые сценарии для Пульса" in preset_text
    assert "preset metals" in preset_text
    assert "preset neweconomy" in preset_text
    assert client.message_markups[0] == {
        "inline_keyboard": [
            [{"text": "neweconomy", "callback_data": "preset:neweconomy"}, {"text": "metals", "callback_data": "preset:metals"}],
            [{"text": "vodka", "callback_data": "preset:vodka"}, {"text": "mechel", "callback_data": "preset:mechel"}],
            [{"text": "wagons", "callback_data": "preset:wagons"}, {"text": "bluechips", "callback_data": "preset:bluechips"}],
            [{"text": "techru", "callback_data": "preset:techru"}],
        ]
    }
    assert client.videos == []


def test_handle_ticker_message_lists_pulse_presets_with_russian_command() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/идеи")

    assert "preset metals" in client.messages[0][1]
    assert client.message_markups[0]["inline_keyboard"][0][1]["callback_data"] == "preset:metals"
    assert client.videos == []


def test_handle_ticker_message_lists_draft_presets() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/drafts")

    preset_text = client.messages[0][1]
    assert "draft" in preset_text
    assert "preset metals" in preset_text
    assert "preset neweconomy" in preset_text
    assert client.message_markups[0] == {
        "inline_keyboard": [
            [{"text": "neweconomy", "callback_data": "preset:neweconomy:draft"}, {"text": "metals", "callback_data": "preset:metals:draft"}],
            [{"text": "vodka", "callback_data": "preset:vodka:draft"}, {"text": "mechel", "callback_data": "preset:mechel:draft"}],
            [{"text": "wagons", "callback_data": "preset:wagons:draft"}, {"text": "bluechips", "callback_data": "preset:bluechips:draft"}],
            [{"text": "techru", "callback_data": "preset:techru:draft"}],
        ]
    }
    assert client.videos == []


def test_handle_ticker_message_lists_draft_presets_with_russian_command() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/черновики")

    assert "draft" in client.messages[0][1]
    assert client.message_markups[0]["inline_keyboard"][0][1]["callback_data"] == "preset:metals:draft"
    assert client.videos == []


def test_telegram_client_redacts_token_in_network_errors(monkeypatch) -> None:
    token = "123456:SECRET"

    def fail_post(url, **_kwargs):
        raise requests.ConnectionError(f"Cannot connect to {url}")

    monkeypatch.setattr(requests, "post", fail_post)

    with pytest.raises(TelegramApiError) as error:
        TelegramClient(token).get_updates(offset=None, timeout=1)

    assert token not in str(error.value)
    assert "<telegram-token>" in str(error.value)
    assert error.value.__cause__ is None


def test_parse_telegram_video_request_accepts_human_message() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("lkoh sber 2020 2024 gradient duration=12 fps=24 close theme=aurora", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["LKOH", "SBER"]
    assert parsed.request.render.start_date == date(2020, 1, 1)
    assert parsed.request.render.end_date == date(2024, 12, 31)
    assert parsed.request.render.duration == 12
    assert parsed.request.render.fps == 24
    assert parsed.request.render.value_col == "CLOSE"
    assert parsed.request.render.use_gradient is True
    assert parsed.request.render.theme == "aurora"


def test_parse_telegram_video_request_rejects_unknown_theme() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    with pytest.raises(ValueError, match="Unknown theme"):
        parse_telegram_video_request("lkoh theme=bad", base)


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


def test_parse_telegram_video_request_accepts_shorts_mode() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), duration=30, fps=20)

    parsed = parse_telegram_video_request("lkoh sber 2020 2024 shorts", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["LKOH", "SBER"]
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_accepts_draft_mode() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), duration=30, fps=20, use_gradient=True)

    parsed = parse_telegram_video_request("lkoh sber 2020 2024 draft", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["LKOH", "SBER"]
    assert parsed.request.render.duration == 4
    assert parsed.request.render.fps == 8
    assert parsed.request.render.use_gradient is False


def test_parse_telegram_video_request_expands_pulse_preset() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("preset metals duration=12", base)

    assert parsed.preset_name == "metals"
    assert [(spec.ticker, spec.engine, spec.market) for spec in parsed.request.ticker_specs] == [
        ("GC=F", "global", "metals"),
        ("SI=F", "global", "metals"),
        ("PA=F", "global", "metals"),
    ]
    assert parsed.request.render.start_date == date(2010, 1, 1)
    assert parsed.request.render.end_date == date(2026, 5, 27)
    assert parsed.request.render.currency == "RUB"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.initial_investment == 0
    assert parsed.request.render.monthly_investment == 30_000
    assert parsed.request.render.duration == 12
    assert parsed.request.render.fps == 24
    assert parsed.request.render.theme == "aurora"


def test_parse_telegram_video_request_accepts_russian_preset_command() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), duration=30, fps=20, use_gradient=True)

    parsed = parse_telegram_video_request("пресет металлы draft", base)

    assert parsed.preset_name == "metals"
    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
    assert parsed.request.render.duration == 4
    assert parsed.request.render.fps == 8
    assert parsed.request.render.use_gradient is False


def test_parse_telegram_video_request_accepts_multiword_russian_preset_alias() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("сценарий голубые фишки duration=12", base)

    assert parsed.preset_name == "bluechips"
    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH", "MGNT"]
    assert parsed.request.render.duration == 12


def test_handle_ticker_message_sends_pulse_copy_for_preset(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fake_generate(request, job_id=None):
        assert [spec.ticker for spec in request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
        return Path("animations/metals.mp4")

    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)
    handle_ticker_message(client, settings, 123, "preset metals", job_id="tg-1")

    assert client.videos == [(123, Path("animations/metals.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-05-27")]
    assert client.messages[-1][0] == 123
    assert "Текст для Пульса" in client.messages[-1][1]
    assert "Что было бы" in client.messages[-1][1]
    assert "#металлы" in client.messages[-1][1]


def test_parse_telegram_video_request_accepts_preset_alias() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("/preset growth theme=default", base)

    assert parsed.preset_name == "neweconomy"
    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SMLT", "SGZH", "POSI"]
    assert parsed.request.render.theme == "default"


def test_pulse_preset_defaults_to_shorts_but_allows_overrides() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), duration=30, fps=20)

    parsed = parse_telegram_video_request("preset neweconomy duration=22 fps=12", base)

    assert parsed.preset_name == "neweconomy"
    assert parsed.request.render.duration == 22
    assert parsed.request.render.fps == 12
    assert parsed.request.render.use_gradient is True


def test_pulse_preset_allows_draft_preview() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), duration=30, fps=20, use_gradient=True)

    parsed = parse_telegram_video_request("preset metals draft", base)

    assert parsed.preset_name == "metals"
    assert parsed.request.render.duration == 4
    assert parsed.request.render.fps == 8
    assert parsed.request.render.use_gradient is False


def test_all_pulse_presets_are_parseable() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    for preset in PRESETS:
        parsed = parse_telegram_video_request(f"preset {preset.name}", base)

        assert parsed.preset_name == preset.name
        assert parsed.request.ticker_specs
        assert parsed.request.render.duration == 16
        assert parsed.request.render.fps == 24
        assert parsed.request.render.use_gradient is True


def test_all_pulse_presets_have_ready_post_copy() -> None:
    for preset in PRESETS:
        post = format_pulse_post(preset)

        assert preset.hook
        assert preset.post_text
        assert preset.tags
        assert preset.music_mood
        assert "Текст для Пульса" in post
        assert "Не является индивидуальной инвестиционной рекомендацией." in post
