from __future__ import annotations

from datetime import date
from pathlib import Path
from threading import Event
import time

import pytest
import requests

from stock_prices._internal import telegram_bot
from stock_prices._internal.models import RenderSettings
from stock_prices._internal.telegram_presets import PRESETS, format_pulse_post, preset_button_label, preset_followup_keyboard
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


def _expected_preset_keyboard(mode: str = "shorts", columns: int = 2) -> dict[str, list[list[dict[str, str]]]]:
    suffix = ":draft" if mode == "draft" else ""
    buttons = [{"text": preset_button_label(preset), "callback_data": f"preset:{preset.name}{suffix}"} for preset in PRESETS]
    return {"inline_keyboard": [buttons[index : index + columns] for index in range(0, len(buttons), columns)]}


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
    assert len(client.messages) == 2
    assert "Текст для Пульса" in client.messages[1][1]
    assert "LKOH" in client.messages[1][1]
    assert "01.01.2020 - 02.01.2020" in client.messages[1][1]
    assert "#акции" in client.messages[1][1]
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

    assert any("поставлена в очередь" in message for _chat_id, message in client.messages)
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
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
    assert any("поставлена в очередь" in message for _chat_id, message in client.messages)
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
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


def test_run_telegram_bot_queues_12s_preset_from_followup_button(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 45,
                    "callback_query": {
                        "id": "callback-3",
                        "data": "preset:metals:12s",
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
        assert job_id == "tg-45"
        assert [spec.ticker for spec in request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
        assert request.render.duration == 12
        assert request.render.fps == 24
        assert request.render.use_gradient is True
        return Path("animations/metals-12s.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-3", "Сценарий поставлен в очередь.")]
    assert any("12s/24fps" in message for _chat_id, message in client.messages)
    assert client.videos == [(123, Path("animations/metals-12s.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-05-27")]


def test_run_telegram_bot_queues_theme_preset_from_followup_button(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 46,
                    "callback_query": {
                        "id": "callback-preset-studio",
                        "data": "preset:metals:studio",
                        "message": {"chat": {"id": 123}},
                    },
                }
            ]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), theme="default"),
    )

    def fake_generate(request, job_id=None):
        assert job_id == "tg-46"
        assert [spec.ticker for spec in request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
        assert request.render.theme == "studio"
        assert request.render.duration == 16
        assert request.render.fps == 24
        return Path("animations/metals-studio.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-preset-studio", "Сценарий поставлен в очередь.")]
    assert client.videos == [(123, Path("animations/metals-studio.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-05-27")]


def test_run_telegram_bot_queues_example_from_inline_button(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 52,
                    "callback_query": {
                        "id": "callback-example",
                        "data": "example:metals-dca",
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
        assert job_id == "tg-52-example-metals-dca"
        assert [spec.ticker for spec in request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
        assert request.render.with_investments is True
        assert request.render.monthly_investment == 30_000
        assert request.render.duration == 16
        assert request.render.fps == 24
        return Path("animations/metals-example.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-example", "Пример поставлен в очередь.")]
    assert any("tg-52-example-metals-dca" in message for _chat_id, message in client.messages)
    assert any("Текст для Пульса" in message for _chat_id, message in client.messages)
    assert client.videos == [(123, Path("animations/metals-example.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-12-31")]


def test_run_telegram_bot_queues_custom_followup_variant(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {"update_id": 53, "message": {"text": "LKOH 2020 2024 shorts", "chat": {"id": 123}}},
                {
                    "update_id": 54,
                    "callback_query": {
                        "id": "callback-custom-draft",
                        "data": "custom:tg-53:draft",
                        "message": {"chat": {"id": 123}},
                    },
                },
            ]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )
    generated: list[tuple[str | None, int, int, bool]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-custom-draft", "Вариант поставлен в очередь.")]
    assert generated == [
        ("tg-53", 16, 24, True),
        ("tg-54-variant-draft", 4, 8, False),
    ]
    assert telegram_bot.custom_followup_keyboard("tg-53") in client.message_markups
    assert any("Быстрые варианты для этого запроса" in message for _chat_id, message in client.messages)


def test_run_telegram_bot_queues_custom_theme_variant(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {"update_id": 55, "message": {"text": "LKOH 2020 2024 shorts theme=aurora", "chat": {"id": 123}}},
                {
                    "update_id": 56,
                    "callback_query": {
                        "id": "callback-custom-studio",
                        "data": "custom:tg-55:studio",
                        "message": {"chat": {"id": 123}},
                    },
                },
            ]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )
    generated: list[tuple[str | None, str]] = []

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-custom-studio", "Вариант поставлен в очередь.")]
    assert generated == [
        ("tg-55", "aurora"),
        ("tg-56-variant-studio", "studio"),
    ]
    assert telegram_bot.custom_followup_keyboard("tg-55") in client.message_markups


def test_run_telegram_bot_reports_missing_custom_followup(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 55,
                    "callback_query": {
                        "id": "callback-custom-missing",
                        "data": "custom:tg-404:shorts",
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

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-custom-missing", "Исходный запрос уже недоступен.")]
    assert client.messages == [(123, "Исходный запрос для кнопки уже недоступен. Отправь текст запроса еще раз.")]
    assert client.videos == []


def test_run_telegram_bot_queues_all_preset_drafts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 46, "message": {"text": "все черновики", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=True),
    )
    generated: list[tuple[str | None, int, int, bool]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.messages[0][0] == 123
    assert "Ставлю в очередь" in client.messages[0][1]
    assert "Металлы" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert len(generated) == len(PRESETS)
    assert generated[0][0] == "tg-46-draft-1-neweconomy"
    assert generated[-1][0] == f"tg-46-draft-{len(PRESETS)}-{PRESETS[-1].name}"
    assert len({job_id for job_id, *_rest in generated}) == len(PRESETS)
    assert all((duration, fps, gradient) == (4, 8, False) for _job_id, duration, fps, gradient in generated)
    assert len(client.videos) == len(PRESETS)


def test_run_telegram_bot_queues_hot_preset_drafts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 60, "message": {"text": "топ черновики", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=True),
    )
    generated: list[tuple[str | None, int, int, bool, list[str]]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append(
            (
                job_id,
                request.render.duration,
                request.render.fps,
                request.render.use_gradient,
                [spec.ticker for spec in request.ticker_specs],
            )
        )
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert "top-draft" in client.messages[0][1]
    assert "Металлы" in client.messages[0][1]
    assert "Мечел" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert [job_id for job_id, *_rest in generated] == [
        "tg-60-hot-draft-1-metals",
        "tg-60-hot-draft-2-neweconomy",
        "tg-60-hot-draft-3-vodka",
        "tg-60-hot-draft-4-mechel",
    ]
    assert all((duration, fps, gradient) == (4, 8, False) for _job_id, duration, fps, gradient, _tickers in generated)
    assert generated[0][4] == ["GC=F", "SI=F", "PA=F"]
    assert generated[-1][4] == ["MTLR", "MTLRP"]
    assert len(client.videos) == 4


def test_run_telegram_bot_queues_hot_preset_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 62, "message": {"text": "топ шортсы", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=False),
    )
    generated: list[tuple[str | None, int, int, bool, list[str]]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append(
            (
                job_id,
                request.render.duration,
                request.render.fps,
                request.render.use_gradient,
                [spec.ticker for spec in request.ticker_specs],
            )
        )
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert "top-shorts" in client.messages[0][1]
    assert "Металлы" in client.messages[0][1]
    assert "Мечел" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert [job_id for job_id, *_rest in generated] == [
        "tg-62-hot-shorts-1-metals",
        "tg-62-hot-shorts-2-neweconomy",
        "tg-62-hot-shorts-3-vodka",
        "tg-62-hot-shorts-4-mechel",
    ]
    assert all((duration, fps, gradient) == (16, 24, True) for _job_id, duration, fps, gradient, _tickers in generated)
    assert generated[0][4] == ["GC=F", "SI=F", "PA=F"]
    assert generated[-1][4] == ["MTLR", "MTLRP"]
    assert len(client.videos) == 4


def test_run_telegram_bot_queues_random_preset_draft(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 47, "message": {"text": "случайный черновик", "chat": {"id": 123}}}]

    client = FakePollingClient()
    selected = PRESETS[1]
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=True),
    )
    generated: list[tuple[str | None, int, int, bool, list[str]]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append(
            (
                job_id,
                request.render.duration,
                request.render.fps,
                request.render.use_gradient,
                [spec.ticker for spec in request.ticker_specs],
            )
        )
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot.random, "choice", lambda presets: selected)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.messages[0][0] == 123
    assert preset_button_label(selected) in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated == [("tg-47-random-draft-metals", 4, 8, False, ["GC=F", "SI=F", "PA=F"])]
    assert client.videos == [(123, Path("animations/tg-47-random-draft-metals.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-05-27")]


def test_run_telegram_bot_queues_all_example_drafts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 56, "message": {"text": "черновики примеров", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2026, 12, 31), use_gradient=True),
    )
    generated: list[tuple[str | None, int, int, bool]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert len(generated) == 6
    assert generated[0] == ("tg-56-example-draft-1-metals-dca", 4, 8, False)
    assert generated[-1] == ("tg-56-example-draft-6-currency", 4, 8, False)
    assert any("draft-примеров" in message for _chat_id, message in client.messages)
    assert telegram_bot.queue_status_keyboard() in client.message_markups


def test_run_telegram_bot_queues_random_example_draft(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 57, "message": {"text": "случайный пример", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=True),
    )
    generated: list[tuple[str | None, int, int, bool, list[str]]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append(
            (
                job_id,
                request.render.duration,
                request.render.fps,
                request.render.use_gradient,
                [spec.ticker for spec in request.ticker_specs],
            )
        )
        return Path(f"animations/{job_id}.mp4")

    selected = telegram_bot._TELEGRAM_EXAMPLES[0]
    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)
    monkeypatch.setattr(telegram_bot.random, "choice", lambda examples: selected)

    telegram_bot.run_telegram_bot(settings)

    assert generated == [("tg-57-random-example-metals-dca", 4, 8, False, ["GC=F", "SI=F", "PA=F"])]
    assert any("Случайный пример" in message for _chat_id, message in client.messages)
    assert client.videos == [(123, Path("animations/tg-57-random-example-metals-dca.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-12-31")]


def test_run_telegram_bot_menu_callback_opens_examples(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 58,
                    "callback_query": {
                        "id": "callback-menu-examples",
                        "data": "menu:examples",
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

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-examples", "Меню обновлено.")]
    assert "Проверенные примеры запросов" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.example_inline_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_help(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 64,
                    "callback_query": {
                        "id": "callback-menu-help",
                        "data": "menu:help",
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

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-help", "Помощь открыта.")]
    assert "Напиши тикер или несколько тикеров" in client.messages[0][1]
    assert "monthly=30000" in client.messages[0][1]
    assert client.message_markups == [None]
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_music_references(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 65,
                    "callback_query": {
                        "id": "callback-menu-music",
                        "data": "menu:music",
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

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-music", "Музыка открыта.")]
    assert "Музыкальные референсы для Пульса" in client.messages[0][1]
    assert "Kavinsky - Nightcall" in client.messages[0][1]
    assert "права на треки нужно проверять отдельно" in client.messages[0][1]
    assert client.message_markups == [None]
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_cover_texts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 66,
                    "callback_query": {
                        "id": "callback-menu-covers",
                        "data": "menu:covers",
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

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-covers", "Обложки открыты.")]
    assert "Тексты для обложек Пульса" in client.messages[0][1]
    assert "IPO-эйфория vs реальность" in client.messages[0][1]
    assert "вертикального ролика" in client.messages[0][1]
    assert client.message_markups == [None]
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_pulse_posts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 69,
                    "callback_query": {
                        "id": "callback-menu-posts",
                        "data": "menu:posts",
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

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-posts", "Посты открыты.")]
    assert "Текстовые пакеты для Пульса" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.post_inline_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_opens_preset_post_from_inline_button(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 70,
                    "callback_query": {
                        "id": "callback-post-metals",
                        "data": "post:metals",
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

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("post callback must not render video")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-post-metals", "Пост открыт.")]
    assert "Текст для Пульса" in client.messages[0][1]
    assert "Металлы часто воспринимают как защиту" in client.messages[0][1]
    assert "Текст на обложку" in client.messages[0][1]
    assert client.message_markups == [None]
    assert client.videos == []


def test_run_telegram_bot_opens_preset_post_without_queue(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 67, "message": {"text": "post metals", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)

    telegram_bot.run_telegram_bot(settings)

    assert "Текст для Пульса" in client.messages[0][1]
    assert "Металлы часто воспринимают как защиту" in client.messages[0][1]
    assert "Текст на обложку" in client.messages[0][1]
    assert client.message_markups == [None]
    assert client.videos == []


def test_run_telegram_bot_opens_custom_post_without_queue(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 68, "message": {"text": "post LKOH SBER 2020 2024", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2019, 1, 1), end_date=date(2026, 1, 1)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("post command must not render video")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.videos == []
    assert client.message_markups == [None]
    assert "Текст для Пульса" in client.messages[0][1]
    assert "Заголовок: LKOH / SBER" in client.messages[0][1]
    assert "Период: 01.01.2020 - 31.12.2024" in client.messages[0][1]
    assert "Текст на обложку" in client.messages[0][1]


def test_handle_ticker_message_opens_custom_post_without_render(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2019, 1, 1), end_date=date(2026, 1, 1)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("post command must not render video")

    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    handle_ticker_message(client, settings, 123, "текст SBER LKOH за год шортс")

    assert client.videos == []
    assert "Текст для Пульса" in client.messages[0][1]
    assert "SBER / LKOH" in client.messages[0][1]


def test_run_telegram_bot_menu_callback_queues_hot_preset_drafts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 61,
                    "callback_query": {
                        "id": "callback-menu-hot-drafts",
                        "data": "menu:hot_drafts",
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
    generated: list[str | None] = []

    def fake_generate(_request, job_id=None):
        generated.append(job_id)
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-hot-drafts", "Top-draft поставлены в очередь.")]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated == [
        "tg-61-hot-draft-1-metals",
        "tg-61-hot-draft-2-neweconomy",
        "tg-61-hot-draft-3-vodka",
        "tg-61-hot-draft-4-mechel",
    ]
    assert len(client.videos) == 4


def test_run_telegram_bot_menu_callback_queues_hot_preset_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 63,
                    "callback_query": {
                        "id": "callback-menu-hot-shorts",
                        "data": "menu:hot_shorts",
                        "message": {"chat": {"id": 123}},
                    },
                }
            ]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=False),
    )
    generated: list[tuple[str | None, int, int, bool]] = []

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-hot-shorts", "Top-shorts поставлены в очередь.")]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated == [
        ("tg-63-hot-shorts-1-metals", 16, 24, True),
        ("tg-63-hot-shorts-2-neweconomy", 16, 24, True),
        ("tg-63-hot-shorts-3-vodka", 16, 24, True),
        ("tg-63-hot-shorts-4-mechel", 16, 24, True),
    ]
    assert len(client.videos) == 4


def test_run_telegram_bot_menu_callback_queues_random_example(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 59,
                    "callback_query": {
                        "id": "callback-menu-random-example",
                        "data": "menu:random_example",
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
    generated: list[tuple[str | None, int, int, bool, list[str]]] = []
    selected = telegram_bot._TELEGRAM_EXAMPLES[0]

    def fake_generate(request, job_id=None):
        generated.append(
            (
                job_id,
                request.render.duration,
                request.render.fps,
                request.render.use_gradient,
                [spec.ticker for spec in request.ticker_specs],
            )
        )
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)
    monkeypatch.setattr(telegram_bot.random, "choice", lambda examples: selected)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-random-example", "Случайный пример поставлен в очередь.")]
    assert telegram_bot.queue_status_keyboard() in client.message_markups
    assert generated == [("tg-59-random-example-metals-dca", 4, 8, False, ["GC=F", "SI=F", "PA=F"])]
    assert client.videos == [(123, Path("animations/tg-59-random-example-metals-dca.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-12-31")]


def test_run_telegram_bot_queues_multiline_batch(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 52,
                    "message": {
                        "text": "LKOH\nSBER 2020 2024\npreset metals draft",
                        "chat": {"id": 123},
                    },
                }
            ]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=True),
    )
    generated: list[tuple[str | None, list[str], int, int, bool]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append(
            (
                job_id,
                [spec.ticker for spec in request.ticker_specs],
                request.render.duration,
                request.render.fps,
                request.render.use_gradient,
            )
        )
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert ("tg-52-batch-1", ["LKOH"], 30, 20, True) in generated
    assert ("tg-52-batch-2", ["SBER"], 30, 20, True) in generated
    assert ("tg-52-batch-3", ["GC=F", "SI=F", "PA=F"], 4, 8, False) in generated
    assert len(generated) == 3
    assert any("Поставил в очередь 3 задачи" in message for _chat_id, message in client.messages)
    assert telegram_bot.queue_status_keyboard() in client.message_markups
    assert len(client.videos) == 3


def test_handle_ticker_message_mentions_queue_mode_for_multiline_batch() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "LKOH\nSBER")

    assert client.messages == [(123, "Несколько запросов одним сообщением работают в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_mentions_queue_mode_for_example_drafts() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "черновики примеров")

    assert client.messages == [(123, "Команда пакетных draft-примеров работает в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_mentions_queue_mode_for_hot_drafts() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "top drafts")

    assert client.messages == [(123, "Команда top-draft черновиков работает в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_mentions_queue_mode_for_hot_shorts() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "top shorts")

    assert client.messages == [(123, "Команда top-shorts роликов работает в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_mentions_queue_mode_for_random_example() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "случайный пример")

    assert client.messages == [(123, "Команда случайного draft-примера работает в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_sends_generic_pulse_copy_for_investment_request(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=True),
    )

    def fake_generate(request, job_id=None):
        assert [spec.ticker for spec in request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
        assert request.render.with_investments is True
        return Path("animations/metals-custom.mp4")

    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)
    handle_ticker_message(
        client,
        settings,
        123,
        "gold silver palladium 2010-2026 RUB capital invest initial=0 monthly=30000 shorts",
        job_id="tg-2",
    )

    pulse_text = client.messages[-1][1]
    assert "Текст для Пульса" in pulse_text
    assert "Заголовок: GC=F / SI=F / PA=F - ежемесячные покупки против разных активов" in pulse_text
    assert "Хук: Если каждый месяц откладывать 30 000 RUB" in pulse_text
    assert "Текст на обложку: 30 000 RUB/мес: кто выиграл?" in pulse_text
    assert "Вопрос для обсуждения: вы бы выдержали такую регулярную стратегию" in pulse_text
    assert "Музыка/монтаж: плотный драматичный бит" in pulse_text
    assert "GC=F / SI=F / PA=F" in pulse_text
    assert "ежемесячно 30 000 RUB" in pulse_text
    assert "#сырье" in pulse_text
    assert "Не инвестиционная рекомендация" in pulse_text


def test_format_generic_pulse_post_uses_single_asset_hook() -> None:
    base = RenderSettings(start_date=date(2020, 1, 1), end_date=date(2024, 12, 31))
    parsed = parse_telegram_video_request("LKOH 2020 2024 close", base)

    pulse_text = telegram_bot.format_generic_pulse_post(parsed)

    assert "Заголовок: LKOH - один актив на истории" in pulse_text
    assert "Хук: Один график, который быстро показывает характер LKOH" in pulse_text
    assert "Текст на обложку: LKOH: график без лишних слов" in pulse_text
    assert "Вопрос для обсуждения: это больше похоже на возможность" in pulse_text
    assert "Музыка/монтаж: минималистичный бит" in pulse_text
    assert "#акции" in pulse_text


def test_telegram_job_queue_status_tracks_pending_and_finished(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )
    queue = telegram_bot.TelegramJobQueue(client, settings)

    queue.enqueue(123, "LKOH", 48, notify=False)
    queue.enqueue(123, "SBER", 49, notify=False)
    pending_status = queue.status_text()

    assert "Очередь Telegram" in pending_status
    assert "Сейчас: нет активного рендера" in pending_status
    assert "Ждет: 2" in pending_status
    assert "tg-48 - LKOH" in pending_status
    assert "tg-49 - SBER" in pending_status

    started = Event()
    release = Event()

    def fake_generate(_request, job_id=None):
        started.set()
        assert release.wait(timeout=5)
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    queue.start()
    try:
        assert started.wait(timeout=5)
        active_status = queue.status_text()
        assert "Сейчас: tg-48 - LKOH" in active_status
        assert "Ждет: 1" in active_status
        assert "tg-49 - SBER" in active_status

        release.set()
        queue.join()
        finished_status = queue.status_text()
    finally:
        release.set()
        queue.stop()

    assert "Сейчас: нет активного рендера" in finished_status
    assert "Ждет: 0" in finished_status
    assert "Готово: 2, ошибок: 0" in finished_status


def test_telegram_job_queue_status_truncates_long_request_preview() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )
    queue = telegram_bot.TelegramJobQueue(client, settings)

    queue.enqueue(
        123,
        "SBER LKOH GAZP NVTK YDEX OZON VKCO from=2010-01-01 to=2026-06-01 RUB capital invest monthly=30000 shorts theme=studio",
        53,
        notify=False,
    )

    status = queue.status_text()

    assert "tg-53 - SBER LKOH GAZP NVTK YDEX OZON VKCO from=2010-01-01 to=2..." in status
    assert "monthly=30000" not in status


def test_run_telegram_bot_reports_queue_status(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 50, "message": {"text": "/queue", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fake_client_factory(*_args, **_kwargs):
        return client

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)

    telegram_bot.run_telegram_bot(settings)

    assert client.messages == [(123, "Очередь Telegram\nСейчас: нет активного рендера\nЖдет: 0\nГотово: 0, ошибок: 0")]
    assert client.message_markups == [telegram_bot.queue_status_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_reports_queue_status_from_button(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 51,
                    "callback_query": {
                        "id": "callback-status",
                        "data": "queue:status",
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

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-status", "Статус очереди обновлен.")]
    assert client.messages == [(123, "Очередь Telegram\nСейчас: нет активного рендера\nЖдет: 0\nГотово: 0, ошибок: 0")]
    assert client.message_markups == [telegram_bot.queue_status_keyboard()]
    assert client.videos == []


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
    assert "/menu" in help_text
    assert "/меню" in help_text
    assert "monthly=30000" in help_text
    assert "30к" in help_text
    assert "shorts" in help_text
    assert "draft" in help_text
    assert "/drafts" in help_text
    assert "/черновики" in help_text
    assert "top drafts" in help_text
    assert "топ черновики" in help_text
    assert "top shorts" in help_text
    assert "топ шортсы" in help_text
    assert "все черновики" in help_text
    assert "случайный черновик" in help_text
    assert "/random_draft" in help_text
    assert "/examples" in help_text
    assert "/примеры" in help_text
    assert "/posts" in help_text
    assert "посты" in help_text
    assert "/music" in help_text
    assert "музыка" in help_text
    assert "/covers" in help_text
    assert "обложки" in help_text
    assert "post metals" in help_text
    assert "пост металлы" in help_text
    assert "черновики примеров" in help_text
    assert "случайный пример" in help_text
    assert "/queue" in help_text
    assert "очередь" in help_text
    assert "Статус очереди" in help_text
    assert "После custom-видео" in help_text
    assert "несколько запросов строками" in help_text
    assert "сделай шортс про SBER" in help_text
    assert "за полгода" in help_text
    assert "сравни SBER с LKOH за год" in help_text
    assert "черновик металлы" in help_text
    assert "пресет металлы" in help_text
    assert "вариант 12s" in help_text
    assert "theme=default|aurora|studio" in help_text
    assert "SiH4 futures" in help_text
    assert "preset neweconomy" in help_text


def test_handle_ticker_message_shows_main_menu() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/menu")

    assert "Меню Telegram" in client.messages[0][1]
    assert "топовые shorts-сценарии" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.main_menu_keyboard()
    keyboard = client.message_markups[0]["inline_keyboard"]
    assert keyboard[0][0]["callback_data"] == "menu:ideas"
    assert keyboard[0][1]["callback_data"] == "menu:examples"
    assert keyboard[1][0] == {"text": "Металлы", "callback_data": "preset:metals"}
    assert keyboard[1][1] == {"text": "Новая экономика", "callback_data": "preset:neweconomy"}
    assert keyboard[2][0] == {"text": "Алкоголь", "callback_data": "preset:vodka"}
    assert keyboard[2][1] == {"text": "Мечел", "callback_data": "preset:mechel"}
    assert keyboard[3][0] == {"text": "Топ черновики", "callback_data": "menu:hot_drafts"}
    assert keyboard[3][1] == {"text": "Топ шортсы", "callback_data": "menu:hot_shorts"}
    assert keyboard[4][0] == {"text": "Черновики", "callback_data": "menu:drafts"}
    assert keyboard[4][1] == {"text": "Черновики примеров", "callback_data": "menu:example_drafts"}
    assert keyboard[5][0] == {"text": "Случайный сценарий", "callback_data": "menu:random_draft"}
    assert keyboard[6][0] == {"text": "Посты", "callback_data": "menu:posts"}
    assert keyboard[6][1] == {"text": "Обложки", "callback_data": "menu:covers"}
    assert keyboard[7][0] == {"text": "Музыка", "callback_data": "menu:music"}
    assert keyboard[7][1] == {"text": "Очередь", "callback_data": "menu:queue"}
    assert keyboard[-1][0]["callback_data"] == "menu:help"
    assert client.videos == []


def test_handle_ticker_message_shows_main_menu_with_russian_command() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/меню")

    assert "Меню Telegram" in client.messages[0][1]
    assert client.message_markups[0]["inline_keyboard"][5][1]["callback_data"] == "menu:random_example"
    assert client.videos == []


def test_handle_ticker_message_shows_music_references() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "музыка")

    music_text = client.messages[0][1]
    assert "Музыкальные референсы для Пульса" in music_text
    assert "Новая экономика 2021-2026" in music_text
    assert "Kavinsky - Nightcall" in music_text
    assert "права на треки нужно проверять отдельно" in music_text
    assert client.message_markups == [None]
    assert client.videos == []


def test_handle_ticker_message_shows_cover_texts() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "обложки")

    cover_text = client.messages[0][1]
    assert "Тексты для обложек Пульса" in cover_text
    assert "IPO-эйфория vs реальность" in cover_text
    assert "30 000 ₽/мес в металлы" in cover_text
    assert "вертикального ролика" in cover_text
    assert client.message_markups == [None]
    assert client.videos == []


def test_handle_ticker_message_lists_pulse_posts() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/posts")

    posts_text = client.messages[0][1]
    assert "Текстовые пакеты для Пульса" in posts_text
    assert "post metals" in posts_text
    assert "готовый текст" in posts_text
    assert "без рендера" in posts_text
    assert client.message_markups[0] == telegram_bot.post_inline_keyboard()
    assert client.message_markups[0]["inline_keyboard"][0][0]["callback_data"] == "post:neweconomy"
    assert client.videos == []


def test_handle_ticker_message_lists_pulse_posts_with_russian_command() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "посты")

    assert "Текстовые пакеты для Пульса" in client.messages[0][1]
    assert client.message_markups[0]["inline_keyboard"][0][1]["callback_data"] == "post:metals"
    assert client.videos == []


def test_handle_ticker_message_shows_preset_post_without_rendering() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "пост металлы")

    post_text = client.messages[0][1]
    assert "Текст для Пульса" in post_text
    assert "Что было бы, если 16 лет подряд" in post_text
    assert "Текст на обложку" in post_text
    assert "Треки-референсы" in post_text
    assert client.message_markups == [None]
    assert client.videos == []


def test_handle_ticker_message_asks_for_preset_name_for_empty_post_command() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/post")

    assert client.messages == [(123, "Напиши название сценария или запрос, например: пост металлы")]
    assert client.message_markups == [None]
    assert client.videos == []


def test_handle_ticker_message_lists_checked_examples() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/examples")

    examples_text = client.messages[0][1]
    assert "Проверенные примеры запросов" in examples_text
    assert "Металлы DCA" in examples_text
    assert "gold silver palladium" in examples_text
    assert "AAPL MSFT NVDA" in examples_text
    assert "SiH4 futures" in examples_text
    assert client.message_markups[0] == telegram_bot.example_inline_keyboard()
    assert client.message_markups[0]["inline_keyboard"][0][0]["callback_data"] == "example:metals-dca"
    assert client.videos == []


def test_handle_ticker_message_lists_checked_examples_with_russian_command() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/примеры")

    assert "Проверенные примеры запросов" in client.messages[0][1]
    assert client.message_markups[0]["inline_keyboard"][0][0]["text"] == "Металлы DCA"
    assert client.videos == []


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
    assert "preset exporters" in preset_text
    assert "preset coalminers" in preset_text
    assert "/queue" in preset_text
    assert "вариант 12s" in preset_text
    assert client.message_markups[0] == _expected_preset_keyboard()
    assert client.videos == []


def test_handle_ticker_message_lists_pulse_presets_with_russian_command() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/идеи")

    assert "preset metals" in client.messages[0][1]
    assert client.message_markups[0]["inline_keyboard"][0][1]["text"] == "Металлы"
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
    assert "preset stateowned" in preset_text
    assert "/queue" in preset_text
    assert client.message_markups[0] == _expected_preset_keyboard("draft")
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


def test_parse_telegram_video_request_accepts_relative_year_period() -> None:
    base = RenderSettings(start_date=date(2010, 1, 1), end_date=date(2026, 6, 3))

    parsed = parse_telegram_video_request("SBER LKOH за 10 лет shorts", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.start_date == date(2016, 6, 3)
    assert parsed.request.render.end_date == date(2026, 6, 3)
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_accepts_english_relative_year_period() -> None:
    base = RenderSettings(start_date=date(2010, 1, 1), end_date=date(2024, 2, 29))

    parsed = parse_telegram_video_request("AAPL MSFT global USD last 3 years", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["AAPL", "MSFT"]
    assert parsed.request.render.start_date == date(2021, 2, 28)
    assert parsed.request.render.end_date == date(2024, 2, 29)
    assert parsed.request.render.currency == "USD"


def test_parse_telegram_video_request_accepts_relative_month_period() -> None:
    base = RenderSettings(start_date=date(2010, 1, 1), end_date=date(2026, 6, 3))

    parsed = parse_telegram_video_request("SBER LKOH за 6 месяцев shorts", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.start_date == date(2025, 12, 3)
    assert parsed.request.render.end_date == date(2026, 6, 3)
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_accepts_short_relative_year_period() -> None:
    base = RenderSettings(start_date=date(2010, 1, 1), end_date=date(2026, 6, 3))

    parsed = parse_telegram_video_request("сравни SBER с LKOH за год шортс", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.start_date == date(2025, 6, 3)
    assert parsed.request.render.end_date == date(2026, 6, 3)
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_accepts_half_year_period() -> None:
    base = RenderSettings(start_date=date(2010, 1, 1), end_date=date(2026, 6, 3))

    parsed = parse_telegram_video_request("YDEX OZON за полгода shorts", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["YDEX", "OZON"]
    assert parsed.request.render.start_date == date(2025, 12, 3)
    assert parsed.request.render.end_date == date(2026, 6, 3)
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_accepts_natural_russian_phrase() -> None:
    base = RenderSettings(start_date=date(2010, 1, 1), end_date=date(2026, 6, 3))

    parsed = parse_telegram_video_request("сделай шортс про SBER и LKOH за 6 месяцев для Пульса", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.start_date == date(2025, 12, 3)
    assert parsed.request.render.end_date == date(2026, 6, 3)
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_accepts_compare_with_preposition() -> None:
    base = RenderSettings(start_date=date(2010, 1, 1), end_date=date(2026, 6, 3))

    parsed = parse_telegram_video_request("сравни SBER с LKOH за 6 месяцев шортс", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.start_date == date(2025, 12, 3)
    assert parsed.request.render.end_date == date(2026, 6, 3)
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_keeps_russian_from_date() -> None:
    base = RenderSettings(start_date=date(2010, 1, 1), end_date=date(2026, 6, 3))

    parsed = parse_telegram_video_request("сравни SBER с LKOH с 2020 по 2024 шортс", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.start_date == date(2020, 1, 1)
    assert parsed.request.render.end_date == date(2024, 12, 31)
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_accepts_english_relative_month_period() -> None:
    base = RenderSettings(start_date=date(2010, 1, 1), end_date=date(2026, 3, 31))

    parsed = parse_telegram_video_request("AAPL MSFT global USD last 1 month", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["AAPL", "MSFT"]
    assert parsed.request.render.start_date == date(2026, 2, 28)
    assert parsed.request.render.end_date == date(2026, 3, 31)
    assert parsed.request.render.currency == "USD"


def test_parse_telegram_video_request_accepts_english_short_relative_month_period() -> None:
    base = RenderSettings(start_date=date(2010, 1, 1), end_date=date(2026, 3, 31))

    parsed = parse_telegram_video_request("AAPL MSFT global USD last month shorts", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["AAPL", "MSFT"]
    assert parsed.request.render.start_date == date(2026, 2, 28)
    assert parsed.request.render.end_date == date(2026, 3, 31)
    assert parsed.request.render.currency == "USD"
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24


def test_parse_telegram_video_request_ignores_english_filler_words() -> None:
    base = RenderSettings(start_date=date(2010, 1, 1), end_date=date(2026, 3, 31))

    parsed = parse_telegram_video_request("make a shorts video about AAPL and MSFT global USD last 1 month", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["AAPL", "MSFT"]
    assert parsed.request.render.start_date == date(2026, 2, 28)
    assert parsed.request.render.end_date == date(2026, 3, 31)
    assert parsed.request.render.currency == "USD"
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24


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


def test_parse_telegram_video_request_accepts_natural_russian_investment_phrase() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request(
        "золото серебро палладий с 2010 по 2026 в рублях капитал инвестируя каждый месяц 30000 градиент шортс",
        base,
    )

    assert [(spec.ticker, spec.engine, spec.market) for spec in parsed.request.ticker_specs] == [
        ("GC=F", "global", "metals"),
        ("SI=F", "global", "metals"),
        ("PA=F", "global", "metals"),
    ]
    assert parsed.request.render.start_date == date(2010, 1, 1)
    assert parsed.request.render.end_date == date(2026, 12, 31)
    assert parsed.request.render.currency == "RUB"
    assert parsed.request.render.value_col == "CAPITAL_REINVEST"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.monthly_investment == 30_000
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_accepts_split_russian_amount() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request(
        "SBER LKOH с 2020 до 2024 капитал вкладывать по 30 000 рублей в месяц",
        base,
    )

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.start_date == date(2020, 1, 1)
    assert parsed.request.render.end_date == date(2024, 12, 31)
    assert parsed.request.render.currency == "RUB"
    assert parsed.request.render.value_col == "CAPITAL_REINVEST"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.monthly_investment == 30_000


def test_parse_telegram_video_request_accepts_russian_k_amount() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request(
        "сделай шортс про золото серебро палладий в рублях капитал инвестируя каждый месяц 30к рублей",
        base,
    )

    assert [(spec.ticker, spec.engine, spec.market) for spec in parsed.request.ticker_specs] == [
        ("GC=F", "global", "metals"),
        ("SI=F", "global", "metals"),
        ("PA=F", "global", "metals"),
    ]
    assert parsed.request.render.currency == "RUB"
    assert parsed.request.render.value_col == "CAPITAL_REINVEST"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.monthly_investment == 30_000
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24


def test_parse_telegram_video_request_accepts_compact_ruble_symbol_amount() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request(
        "сделай шортс про золото серебро палладий капитал инвестируя каждый месяц 30к₽",
        base,
    )

    assert [(spec.ticker, spec.engine, spec.market) for spec in parsed.request.ticker_specs] == [
        ("GC=F", "global", "metals"),
        ("SI=F", "global", "metals"),
        ("PA=F", "global", "metals"),
    ]
    assert parsed.request.render.currency == "RUB"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.monthly_investment == 30_000


def test_parse_telegram_video_request_accepts_russian_thousand_word_amount() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("SBER LKOH капитал вкладывать по 30 тыс рублей в месяц", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.currency == "RUB"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.monthly_investment == 30_000


def test_parse_telegram_video_request_accepts_split_amount_with_compact_currency() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("SBER LKOH капитал вкладывать по 30 000₽ в месяц", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.currency == "RUB"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.monthly_investment == 30_000


def test_parse_telegram_video_request_accepts_period_before_amount() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("SBER LKOH капитал инвестировать в месяц по 30к₽", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.currency == "RUB"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.monthly_investment == 30_000


def test_parse_telegram_video_request_accepts_key_value_short_amount() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("SBER LKOH capital monthly=30к₽", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.currency == "RUB"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.monthly_investment == 30_000


def test_parse_telegram_video_request_accepts_english_k_amount() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("AAPL MSFT global USD capital invest monthly 30k", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["AAPL", "MSFT"]
    assert parsed.request.render.currency == "USD"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.monthly_investment == 30_000


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


def test_parse_telegram_video_request_accepts_direct_russian_preset_shortcut() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("металлы", base)

    assert parsed.preset_name == "metals"
    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
    assert parsed.request.render.duration == 16
    assert parsed.request.render.fps == 24
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_accepts_direct_draft_preset_shortcut() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), duration=30, fps=20, use_gradient=True)

    parsed = parse_telegram_video_request("черновик металлы", base)

    assert parsed.preset_name == "metals"
    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
    assert parsed.request.render.duration == 4
    assert parsed.request.render.fps == 8
    assert parsed.request.render.use_gradient is False


def test_parse_telegram_video_request_direct_shortcut_allows_multiword_alias_and_overrides() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("голубые фишки duration=12", base)

    assert parsed.preset_name == "bluechips"
    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH", "MGNT"]
    assert parsed.request.render.duration == 12


def test_parse_telegram_video_request_accepts_stateowned_direct_shortcut() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("госы", base)

    assert parsed.preset_name == "stateowned"
    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["GAZP", "AFLT", "SNGS"]
    assert parsed.request.render.start_date == date(2010, 1, 1)
    assert parsed.request.render.monthly_investment == 30_000


def test_parse_telegram_video_request_accepts_exporters_direct_shortcut() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("экспортёры duration=12", base)

    assert parsed.preset_name == "exporters"
    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["LKOH", "PHOR", "NLMK"]
    assert parsed.request.render.duration == 12
    assert parsed.request.render.theme == "aurora"


def test_parse_telegram_video_request_accepts_coalminers_draft_shortcut() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), duration=30, fps=20, use_gradient=True)

    parsed = parse_telegram_video_request("черновик угольщики", base)

    assert parsed.preset_name == "coalminers"
    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["MTLR", "RASP"]
    assert parsed.request.render.duration == 4
    assert parsed.request.render.fps == 8
    assert parsed.request.render.use_gradient is False


def test_parse_telegram_video_request_keeps_gold_as_single_asset() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("gold", base)

    assert parsed.preset_name is None
    assert [(spec.ticker, spec.engine, spec.market) for spec in parsed.request.ticker_specs] == [
        ("GC=F", "global", "metals")
    ]


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
    assert client.messages[-2][0] == 123
    assert "Текст для Пульса" in client.messages[-2][1]
    assert "Что было бы" in client.messages[-2][1]
    assert "#металлы" in client.messages[-2][1]
    assert client.messages[-1] == (123, "Быстрые варианты для этого сценария:")
    assert client.message_markups[-1] == preset_followup_keyboard("metals")


def test_handle_ticker_message_sends_pulse_copy_for_direct_preset(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fake_generate(request, job_id=None):
        assert [spec.ticker for spec in request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
        assert request.render.duration == 4
        assert request.render.fps == 8
        return Path("animations/metals-draft.mp4")

    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)
    handle_ticker_message(client, settings, 123, "черновик металлы", job_id="tg-1")

    assert client.videos == [(123, Path("animations/metals-draft.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-05-27")]
    assert "Текст для Пульса" in client.messages[-2][1]
    assert client.message_markups[-1] == preset_followup_keyboard("metals")


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
        assert preset.music_tracks
        assert preset.cover_texts
        assert "Текст для Пульса" in post
        assert "Текст на обложку" in post
        assert "Треки-референсы" in post
        assert "права проверять отдельно" in post
        assert "Не является индивидуальной инвестиционной рекомендацией." in post


def test_all_pulse_presets_have_human_button_labels() -> None:
    labels = [preset_button_label(preset) for preset in PRESETS]

    assert "Металлы" in labels
    assert "Новая экономика" in labels
    assert "Угольщики" in labels
    assert all(label and len(label) <= 24 for label in labels)
