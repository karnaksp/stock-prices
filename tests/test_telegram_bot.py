from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from threading import Event
import time

import pytest
import requests

from stock_prices._internal import telegram_bot
from stock_prices._internal.models import RenderSettings
from stock_prices._internal.telegram_presets import (
    PRESET_CATEGORIES,
    PRESETS,
    format_pulse_post,
    get_preset,
    get_preset_category,
    preset_button_label,
    preset_followup_keyboard,
    presets_for_category,
)
from stock_prices._internal.telegram_requests import parse_telegram_video_request
from stock_prices._internal.telegram_bot import TelegramApiError, TelegramBotSettings, TelegramClient, cleanup_old_outputs, handle_ticker_message


class FakeClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.message_markups: list[dict | None] = []
        self.videos: list[tuple[int, Path, str]] = []
        self.callback_answers: list[tuple[str, str]] = []
        self.command_menus: list[list[dict[str, str]]] = []

    def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
        self.messages.append((chat_id, text))
        self.message_markups.append(reply_markup)

    def send_video(self, chat_id: int, video_path: Path, caption: str) -> None:
        self.videos.append((chat_id, video_path, caption))

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        self.callback_answers.append((callback_query_id, text))

    def set_my_commands(self, commands: list[dict[str, str]]) -> None:
        self.command_menus.append(commands)


def _expected_preset_keyboard(mode: str = "shorts", columns: int = 2) -> dict[str, list[list[dict[str, str]]]]:
    suffix = ":draft" if mode == "draft" else ""
    buttons = [{"text": preset_button_label(preset), "callback_data": f"preset:{preset.name}{suffix}"} for preset in PRESETS]
    return {"inline_keyboard": [buttons[index : index + columns] for index in range(0, len(buttons), columns)]}


def test_telegram_bot_command_menu_is_compact() -> None:
    commands = telegram_bot.telegram_bot_command_menu()

    assert [item["command"] for item in commands] == [
        "menu",
        "shoot",
        "shorts",
        "queue",
        "help",
    ]
    assert len(commands) <= 5
    assert all(1 <= len(item["description"]) <= 256 for item in commands)
    assert all("/" not in item["command"] for item in commands)
    assert all(item["command"].replace("_", "").isalnum() and item["command"].islower() for item in commands)
    assert commands[2] == {"command": "shorts", "description": "истории или свой запрос"}


def test_preset_followup_keyboard_keeps_post_render_actions() -> None:
    keyboard = preset_followup_keyboard("metals")

    assert keyboard["inline_keyboard"][1] == [
        {"text": "12s", "callback_data": "preset:metals:12s"},
    ]
    assert keyboard["inline_keyboard"][2] == [
        {"text": "Aurora 16s", "callback_data": "preset:metals:aurora"},
        {"text": "Studio 16s", "callback_data": "preset:metals:studio"},
    ]
    assert keyboard["inline_keyboard"][3] == [
        {"text": "Все темы x3", "callback_data": "preset:metals:themes"},
    ]
    assert keyboard["inline_keyboard"][-2] == [
        {"text": "Пост", "callback_data": "post:metals"},
        {"text": "Очередь", "callback_data": telegram_bot.QUEUE_STATUS_CALLBACK_DATA},
    ]
    assert keyboard["inline_keyboard"][-1] == [{"text": "Меню", "callback_data": "menu:main_menu"}]


def test_custom_followup_keyboard_keeps_post_render_actions() -> None:
    keyboard = telegram_bot.custom_followup_keyboard("tg-53")

    assert keyboard["inline_keyboard"][1] == [
        {"text": "12s", "callback_data": "custom:tg-53:12s"},
    ]
    assert keyboard["inline_keyboard"][2] == [
        {"text": "Aurora 16s", "callback_data": "custom:tg-53:aurora"},
        {"text": "Studio 16s", "callback_data": "custom:tg-53:studio"},
    ]
    assert keyboard["inline_keyboard"][-1] == [
        {"text": "Очередь", "callback_data": telegram_bot.QUEUE_STATUS_CALLBACK_DATA},
        {"text": "Меню", "callback_data": "menu:main_menu"},
    ]


def test_render_progress_notifier_sends_status_and_stops() -> None:
    client = FakeClient()

    stop = telegram_bot._start_render_progress_notifier(
        client,
        123,
        "tg-1",
        "SBER / LKOH",
        first_notice_seconds=0.01,
        repeat_seconds=0.02,
    )
    deadline = time.monotonic() + 1.0
    while not client.messages and time.monotonic() < deadline:
        time.sleep(0.01)
    stop()
    message_count = len(client.messages)
    time.sleep(0.05)

    assert message_count >= 1
    assert len(client.messages) == message_count
    assert "Рендер еще идет: SBER / LKOH" in client.messages[0][1]
    assert "Job tg-1" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()


def test_telegram_client_sets_my_commands(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        ok = True
        text = '{"ok": true, "result": true}'

        def json(self):
            return {"ok": True, "result": True}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    TelegramClient("123456:SECRET").set_my_commands(telegram_bot.telegram_bot_command_menu())

    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "https://api.telegram.org/bot123456:SECRET/setMyCommands"
    commands = json.loads(kwargs["data"]["commands"])
    assert commands[0] == {"command": "menu", "description": "главный пульт"}
    assert commands[-1]["command"] == "help"


def test_configure_telegram_command_menu_logs_and_continues(caplog) -> None:
    class FailingClient(FakeClient):
        def set_my_commands(self, commands: list[dict[str, str]]) -> None:
            raise TelegramApiError("temporary api failure")

    telegram_bot.configure_telegram_command_menu(FailingClient())

    assert "Failed to update Telegram bot command menu." in caplog.text


def test_run_telegram_bot_configures_command_menu(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()
            self.calls: list[str] = []

        def set_my_commands(self, commands: list[dict[str, str]]) -> None:
            self.calls.append("set_my_commands")
            super().set_my_commands(commands)

        def get_updates(self, *_args, **_kwargs):
            self.calls.append("get_updates")
            return []

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)

    telegram_bot.run_telegram_bot(settings)

    assert client.command_menus == [telegram_bot.telegram_bot_command_menu()]
    assert client.calls == ["set_my_commands", "get_updates"]


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
    assert "Тема: default" in client.messages[0][1]
    assert "Метрика: капитал с реинвестированием" in client.messages[0][1]
    assert "Градиент: нет" in client.messages[0][1]
    assert seen_job_ids == ["tg-1"]
    assert len(client.messages) == 2
    assert "Пост для Пульса (можно копировать)" in client.messages[1][1]
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


def test_run_telegram_bot_queues_shorts_slash_command(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 421, "message": {"text": "/shorts LKOH SBER 2020 2024", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), duration=30, fps=20),
    )
    generated: list[tuple[str | None, int, int, bool, list[str]]] = []

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
        return Path("animations/LKOH-SBER-shorts.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert generated == [("tg-421", 16, 24, True, ["LKOH", "SBER"])]
    assert any("16s/24fps" in message for _chat_id, message in client.messages)
    assert client.videos == [(123, Path("animations/LKOH-SBER-shorts.mp4"), "LKOH / SBER: 2020-01-01 - 2024-12-31")]


def test_run_telegram_bot_queues_draft_slash_command_for_preset(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 422, "message": {"text": "/draft metals", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), duration=30, fps=20, use_gradient=True),
    )
    generated: list[tuple[str | None, int, int, bool, list[str]]] = []

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
        return Path("animations/metals-draft.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert generated == [("tg-422", 4, 8, False, ["GC=F", "SI=F", "PA=F"])]
    assert client.videos == [(123, Path("animations/metals-draft.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-05-27")]


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
    assert any("Пост для Пульса (можно копировать)" in message for _chat_id, message in client.messages)
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
    assert any("Тема: studio" in message for _chat_id, message in client.messages)
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
    assert any("Пост для Пульса (можно копировать)" in message for _chat_id, message in client.messages)
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


def test_run_telegram_bot_queues_all_preset_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 64, "message": {"text": "все шортсы", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=False),
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
    assert "shorts-роликов" in client.messages[0][1]
    assert "Металлы" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert len(generated) == len(PRESETS)
    assert generated[0][0] == "tg-64-shorts-1-neweconomy"
    assert generated[-1][0] == f"tg-64-shorts-{len(PRESETS)}-{PRESETS[-1].name}"
    assert len({job_id for job_id, *_rest in generated}) == len(PRESETS)
    assert all((duration, fps, gradient) == (16, 24, True) for _job_id, duration, fps, gradient in generated)
    assert len(client.videos) == len(PRESETS)


def test_run_telegram_bot_queues_content_plan_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 104, "message": {"text": "снять план", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=False),
    )
    generated: list[tuple[str | None, int, int, bool, str]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert "shorts-роликов контент-плана" in client.messages[0][1]
    assert "Д1" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert len(generated) == len(telegram_bot.CONTENT_PLAN_PRESETS)
    assert generated[0] == ("tg-104-plan-shorts-1-neweconomy", 16, 24, True, "studio")
    assert generated[1] == ("tg-104-plan-shorts-2-metals", 16, 24, True, "aurora")
    assert generated[-1][0] == f"tg-104-plan-shorts-{len(telegram_bot.CONTENT_PLAN_PRESETS)}-{telegram_bot.CONTENT_PLAN_PRESETS[-1]}"
    assert len({job_id for job_id, *_rest in generated}) == len(telegram_bot.CONTENT_PLAN_PRESETS)
    assert len(client.videos) == len(telegram_bot.CONTENT_PLAN_PRESETS)


def test_format_weekly_publication_pack_lists_publication_assets() -> None:
    pack_text = telegram_bot.format_weekly_publication_pack()

    assert "Недельный выпуск для Пульса" in pack_text
    assert "Ставлю 7 shorts" in pack_text
    assert "Д1: Новая экономика 2021-2026" in pack_text
    assert "Шортс: preset neweconomy" in pack_text
    assert "Пост: post neweconomy" in pack_text
    assert "Д4: Связь и дивиденды" in pack_text
    assert "Пост: post telecoms" in pack_text
    assert "Д5: Ритейл после перестройки рынка" in pack_text
    assert "Пост: post retailers" in pack_text
    assert "Д6: Электроэнергетика: скучная инфраструктура" in pack_text
    assert "Пост: post utilities" in pack_text
    assert "Д7: Голубые фишки: скучно или эффективно" in pack_text
    assert "Пост: post bluechips" in pack_text
    assert "Статус рендера: /queue" in pack_text
    assert telegram_bot.weekly_publication_pack_keyboard()["inline_keyboard"][0][0]["callback_data"] == telegram_bot.QUEUE_STATUS_CALLBACK_DATA


def test_format_weekly_posts_lists_full_publication_texts() -> None:
    intro = telegram_bot.format_weekly_post_intro()
    first_post = telegram_bot.format_weekly_post(1, "neweconomy")
    keyboard = telegram_bot.weekly_posts_keyboard()

    assert "Посты недели для Пульса" in intro
    assert "7 готовых текстов" in intro
    assert "Пост недели: Д1 Новая экономика 2021-2026" in first_post
    assert "Пост для Пульса (можно копировать)" in first_post
    assert "IPO-эйфория" in first_post
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "menu:content_plan"
    assert keyboard["inline_keyboard"][0][1]["callback_data"] == "menu:publication_week"
    assert keyboard["inline_keyboard"][1][0]["callback_data"] == telegram_bot.QUEUE_STATUS_CALLBACK_DATA


def test_run_telegram_bot_queues_weekly_publication_pack(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 110, "message": {"text": "/publish_week", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=False),
    )
    generated: list[tuple[str | None, int, int, bool, str]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert "Недельный выпуск" in client.messages[0][1]
    assert "shorts-роликов контент-плана" in client.messages[0][1]
    assert "Недельный выпуск для Пульса" in client.messages[1][1]
    assert "Д1: Новая экономика 2021-2026" in client.messages[1][1]
    assert "Пост: post neweconomy" in client.messages[1][1]
    assert "Д4: Связь и дивиденды" in client.messages[1][1]
    assert "Пост: post telecoms" in client.messages[1][1]
    assert "Д5: Ритейл после перестройки рынка" in client.messages[1][1]
    assert "Пост: post retailers" in client.messages[1][1]
    assert "Д6: Электроэнергетика: скучная инфраструктура" in client.messages[1][1]
    assert "Пост: post utilities" in client.messages[1][1]
    assert "Д7: Голубые фишки: скучно или эффективно" in client.messages[1][1]
    assert "Пост: post bluechips" in client.messages[1][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert client.message_markups[1] == telegram_bot.weekly_publication_pack_keyboard()
    assert len(generated) == len(telegram_bot.CONTENT_PLAN_PRESETS)
    assert generated[0] == ("tg-110-publication-week-1-neweconomy", 16, 24, True, "studio")
    assert generated[1] == ("tg-110-publication-week-2-metals", 16, 24, True, "aurora")
    assert generated[-1][0] == f"tg-110-publication-week-{len(telegram_bot.CONTENT_PLAN_PRESETS)}-{telegram_bot.CONTENT_PLAN_PRESETS[-1]}"
    assert len({job_id for job_id, *_rest in generated}) == len(telegram_bot.CONTENT_PLAN_PRESETS)
    assert len(client.videos) == len(telegram_bot.CONTENT_PLAN_PRESETS)


def test_run_telegram_bot_opens_weekly_posts_without_render(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 114, "message": {"text": "/week_posts", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("weekly posts command must not render video")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    assert len(client.messages) == len(telegram_bot.CONTENT_PLAN_PRESETS) + 1
    assert "Посты недели для Пульса" in client.messages[0][1]
    assert "Пост недели: Д1 Новая экономика 2021-2026" in client.messages[1][1]
    assert "Пост для Пульса (можно копировать)" in client.messages[1][1]
    assert f"Пост недели: Д{len(telegram_bot.CONTENT_PLAN_PRESETS)} Голубые фишки" in client.messages[-1][1]
    assert client.message_markups[0] == telegram_bot.weekly_posts_keyboard()
    assert all(markup is None for markup in client.message_markups[1:])
    assert client.videos == []


def test_daily_content_plan_preset_uses_weekday() -> None:
    monday_index, monday_preset = telegram_bot._daily_content_plan_preset(date(2026, 6, 1))
    thursday_index, thursday_preset = telegram_bot._daily_content_plan_preset(date(2026, 6, 4))
    friday_index, friday_preset = telegram_bot._daily_content_plan_preset(date(2026, 6, 5))
    saturday_index, saturday_preset = telegram_bot._daily_content_plan_preset(date(2026, 6, 6))
    sunday_index, sunday_preset = telegram_bot._daily_content_plan_preset(date(2026, 6, 7))

    assert (monday_index, monday_preset.name) == (1, "neweconomy")
    assert (thursday_index, thursday_preset.name) == (4, "telecoms")
    assert (friday_index, friday_preset.name) == (5, "retailers")
    assert (saturday_index, saturday_preset.name) == (6, "utilities")
    assert (sunday_index, sunday_preset.name) == (7, "bluechips")


def test_format_daily_content_kit_uses_weekday() -> None:
    kit_text = telegram_bot.format_daily_content_kit(date(2026, 6, 3))

    assert "Пакет дня: Д3" in kit_text
    assert "Пакет сценария" in kit_text
    assert "Шортс: preset banks" in kit_text
    assert "Пост без рендера: post banks" in kit_text
    assert telegram_bot.daily_content_kit_keyboard(date(2026, 6, 3)) == telegram_bot.preset_kit_keyboard("banks")


def test_format_daily_post_uses_weekday() -> None:
    post_text = telegram_bot.format_daily_post(date(2026, 6, 3))
    keyboard = telegram_bot.daily_post_keyboard(date(2026, 6, 3))

    assert "Пост дня: Д3" in post_text
    assert "Сценарий взят из недельного контент-плана" in post_text
    assert "Пост для Пульса (можно копировать)" in post_text
    assert "#сбер" in post_text
    assert "#втб" in post_text
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "menu:daily_short"
    assert keyboard["inline_keyboard"][0][1]["callback_data"] == "menu:daily_kit"
    assert keyboard["inline_keyboard"][1][0]["callback_data"] == "preset:banks:shorts"
    assert keyboard["inline_keyboard"][1][1]["callback_data"] == telegram_bot.QUEUE_STATUS_CALLBACK_DATA


def test_run_telegram_bot_opens_daily_content_kit_without_render(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 106, "message": {"text": "пакет дня", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("daily content kit must not render video")

    monkeypatch.setattr(telegram_bot, "_today", lambda: date(2026, 6, 3))
    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    kit_text = client.messages[0][1]
    assert "Пакет дня: Д3" in kit_text
    assert "Шортс: preset banks" in kit_text
    assert "Пост без рендера: post banks" in kit_text
    assert client.message_markups == [telegram_bot.preset_kit_keyboard("banks")]
    assert client.videos == []


def test_run_telegram_bot_opens_daily_post_without_render(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 112, "message": {"text": "пост дня", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("daily post command must not render video")

    monkeypatch.setattr(telegram_bot, "_today", lambda: date(2026, 6, 3))
    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    post_text = client.messages[0][1]
    assert "Пост дня: Д3" in post_text
    assert "Пост для Пульса (можно копировать)" in post_text
    assert "#сбер" in post_text
    assert "#втб" in post_text
    assert client.message_markups == [telegram_bot.daily_post_keyboard(date(2026, 6, 3))]
    assert client.videos == []


def test_run_telegram_bot_queues_daily_content_plan_short(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 105, "message": {"text": "шортс дня", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=False),
    )
    generated: list[tuple[str | None, int, int, bool, str]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "_today", lambda: date(2026, 6, 3))
    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert "Шортс дня" in client.messages[0][1]
    assert "Д3" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated == [("tg-105-daily-short-3-banks", 16, 24, True, "default")]
    assert len(client.videos) == 1


def test_run_telegram_bot_queues_daily_publication_day(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 108, "message": {"text": "/publish_day", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )
    generated: list[tuple[str | None, int, int, bool, str]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "_today", lambda: date(2026, 6, 3))
    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert "Публикационный день: Д3 Банки" in client.messages[0][1]
    assert "Пакет дня: Д3" in client.messages[1][1]
    assert "Пост без рендера: post banks" in client.messages[1][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert client.message_markups[1] == telegram_bot.preset_kit_keyboard("banks")
    assert generated == [("tg-108-publication-day-3-banks", 16, 24, True, "default")]
    assert len(client.videos) == 1


def test_run_telegram_bot_queues_styled_all_preset_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 66, "message": {"text": "все шортсы студио", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), theme="default"),
    )
    generated: list[tuple[str | None, int, int, bool, str]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert "в теме studio" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert len(generated) == len(PRESETS)
    assert generated[0] == ("tg-66-shorts-studio-1-neweconomy", 16, 24, True, "studio")
    assert generated[-1][0] == f"tg-66-shorts-studio-{len(PRESETS)}-{PRESETS[-1].name}"
    assert all(theme == "studio" for *_rest, theme in generated)
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


def test_run_telegram_bot_queues_styled_hot_preset_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 72, "message": {"text": "top shorts studio", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), theme="default"),
    )
    generated: list[tuple[str | None, int, int, bool, str]] = []

    def fake_client_factory(*_args, **_kwargs):
        return client

    def fake_generate(request, job_id=None):
        generated.append(
            (job_id, request.render.duration, request.render.fps, request.render.use_gradient, request.render.theme)
        )
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", fake_client_factory)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert "top-shorts в теме studio" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated == [
        ("tg-72-hot-shorts-studio-1-metals", 16, 24, True, "studio"),
        ("tg-72-hot-shorts-studio-2-neweconomy", 16, 24, True, "studio"),
        ("tg-72-hot-shorts-studio-3-vodka", 16, 24, True, "studio"),
        ("tg-72-hot-shorts-studio-4-mechel", 16, 24, True, "studio"),
    ]
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


def test_run_telegram_bot_queues_random_preset_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 48, "message": {"text": "случайный шортс", "chat": {"id": 123}}}]

    client = FakePollingClient()
    selected = PRESETS[1]
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=False),
    )
    generated: list[tuple[str | None, int, int, bool, list[str]]] = []

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
    monkeypatch.setattr(telegram_bot.random, "choice", lambda presets: selected)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.messages[0][0] == 123
    assert preset_button_label(selected) in client.messages[0][1]
    assert "shorts-ролик" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated == [("tg-48-random-shorts-metals", 16, 24, True, ["GC=F", "SI=F", "PA=F"])]
    assert client.videos == [(123, Path("animations/tg-48-random-shorts-metals.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-05-27")]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("шортс тихие", ("batch", "shorts", "quiet", None)),
        ("тихий шортс", ("batch", "shorts", "quiet", None)),
        ("top quiet studio", ("batch", "shorts", "quiet", "studio")),
        ("черновик тихие", ("batch", "draft", "quiet", None)),
        ("random drama", ("random", "shorts", "drama", None)),
        ("random draft quiet", ("random", "draft", "quiet", None)),
        ("category random drama", ("random", "shorts", "drama", None)),
        ("category drama", None),
    ],
)
def test_category_preset_action_parses_expected_aliases(text: str, expected: tuple[str, str, str, str | None] | None) -> None:
    action = telegram_bot._category_preset_action(text)

    if expected is None:
        assert action is None
    else:
        assert action is not None
        assert (action.kind, action.mode, action.category_name, action.theme) == expected


def test_run_telegram_bot_queues_category_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 81, "message": {"text": "top quiet studio", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), theme="default"),
    )
    generated: list[tuple[str | None, int, int, bool, str]] = []

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    presets = presets_for_category("quiet")
    assert "категории Тихие российские истории в теме studio" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert [job_id for job_id, *_rest in generated] == [
        f"tg-81-quiet-shorts-studio-{index}-{preset.name}" for index, preset in enumerate(presets, start=1)
    ]
    assert all((duration, fps, gradient, theme) == (16, 24, True, "studio") for _job_id, duration, fps, gradient, theme in generated)
    assert len(client.videos) == len(presets)


def test_run_telegram_bot_queues_category_drafts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 82, "message": {"text": "черновик тихие", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=True),
    )
    generated: list[tuple[str | None, int, int, bool]] = []

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    presets = presets_for_category("quiet")
    assert "draft-черновиков категории Тихие российские истории" in client.messages[0][1]
    assert [job_id for job_id, *_rest in generated] == [
        f"tg-82-quiet-draft-{index}-{preset.name}" for index, preset in enumerate(presets, start=1)
    ]
    assert all((duration, fps, gradient) == (4, 8, False) for _job_id, duration, fps, gradient in generated)
    assert len(client.videos) == len(presets)


def test_run_telegram_bot_queues_random_category_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 83, "message": {"text": "random drama", "chat": {"id": 123}}}]

    client = FakePollingClient()
    selected = get_preset("builders")
    seen_choices: list[tuple[str, ...]] = []
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), use_gradient=False),
    )
    generated: list[tuple[str | None, int, int, bool, list[str]]] = []

    def fake_choice(presets):
        seen_choices.append(tuple(preset.name for preset in presets))
        return selected

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
    monkeypatch.setattr(telegram_bot.random, "choice", fake_choice)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert seen_choices == [tuple(preset.name for preset in presets_for_category("drama"))]
    assert "Случайный шортс категории Драмы и просадки" in client.messages[0][1]
    assert generated == [("tg-83-random-drama-shorts-builders", 16, 24, True, ["PIKK", "LSRG", "SMLT"])]
    assert len(client.videos) == 1


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


def test_example_keyboard_exposes_batch_actions() -> None:
    keyboard = telegram_bot.example_inline_keyboard()

    assert keyboard["inline_keyboard"][-2] == [
        {"text": "🎲 Случайный draft", "callback_data": "menu:random_example"},
        {"text": "🧪 Все draft", "callback_data": "menu:example_drafts"},
    ]
    assert keyboard["inline_keyboard"][-1] == [
        {"text": "⏳ Очередь", "callback_data": telegram_bot.QUEUE_STATUS_CALLBACK_DATA},
        {"text": "🏠 Меню", "callback_data": "menu:main_menu"},
    ]


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
    assert "Как попросить ролик" in client.messages[0][1]
    assert "ежемесячно 30к₽" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.help_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_reference(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 65,
                    "callback_query": {
                        "id": "callback-menu-reference",
                        "data": "menu:reference",
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

    assert client.callback_answers == [("callback-menu-reference", "Справочник открыт.")]
    assert "Справочник" in client.messages[0][1]
    assert "музыка" in client.messages[0][1]
    assert client.message_markups[0]["inline_keyboard"][0][0] == {"text": "📚 Истории", "callback_data": "menu:preset_categories"}
    assert client.message_markups == [telegram_bot.reference_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_preset_categories(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 66,
                    "callback_query": {
                        "id": "callback-menu-preset-categories",
                        "data": "menu:preset_categories",
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

    assert client.callback_answers == [("callback-menu-preset-categories", "Истории открыты.")]
    assert "Истории для Пульса" in client.messages[0][1]
    assert "Выберите категорию кнопкой ниже" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.preset_category_inline_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_preset_category_callback_opens_category(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 67,
                    "callback_query": {
                        "id": "callback-category-quiet",
                        "data": "category:quiet",
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

    assert client.callback_answers == [("callback-category-quiet", "Категория открыта.")]
    assert "Категория: Тихие российские истории" in client.messages[0][1]
    assert "Голубые фишки" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.preset_category_keyboard("quiet")]
    assert client.videos == []


def test_run_telegram_bot_preset_category_callback_opens_draft_category(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 68,
                    "callback_query": {
                        "id": "callback-category-quiet-draft",
                        "data": "category:quiet:draft",
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

    assert client.callback_answers == [("callback-category-quiet-draft", "Категория открыта.")]
    assert "draft 4s" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.preset_category_keyboard("quiet", mode="draft")]
    assert client.message_markups[0]["inline_keyboard"][0][0]["callback_data"].endswith(":draft")
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_quick_launch(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 115,
                    "callback_query": {
                        "id": "callback-menu-quick-launch",
                        "data": "menu:quick_launch",
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

    assert client.callback_answers == [("callback-menu-quick-launch", "Быстрый запуск открыт.")]
    assert "Быстрый запуск" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.quick_launch_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_opens_quick_launch_without_render(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 117, "message": {"text": "/quick", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("quick launch command must not render video")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    assert "Быстрый запуск" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.quick_launch_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_opens_quick_launch_with_shoot_alias(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 118, "message": {"text": "/shoot", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("shoot alias must not render video")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    assert "Быстрый запуск" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.quick_launch_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_main_menu(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 116,
                    "callback_query": {
                        "id": "callback-menu-main-menu",
                        "data": "menu:main_menu",
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

    assert client.callback_answers == [("callback-menu-main-menu", "Меню открыто.")]
    assert "Меню для Пульса" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.main_menu_keyboard()]
    assert client.videos == []


def test_handle_ticker_message_shows_production_guide_without_render(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("production guide must not render video")

    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    handle_ticker_message(client, settings, 123, "шпаргалка")

    guide_text = client.messages[0][1]
    assert "Шпаргалка производства шортсов для Пульса" in guide_text
    assert "/publish_day" in guide_text
    assert "/publish_week" in guide_text
    assert "снять неделю" in guide_text
    assert "/today_post" in guide_text
    assert "пост дня" in guide_text
    assert "/week_posts" in guide_text
    assert "/today_kit" in guide_text
    assert "top drafts" in guide_text
    assert "post metals" in guide_text
    assert client.message_markups == [telegram_bot.production_guide_keyboard()]
    assert client.message_markups[0]["inline_keyboard"] == [
        [
            {"text": "📅 День", "callback_data": "menu:publication_day"},
            {"text": "🗓 Неделя", "callback_data": "menu:publication_week"},
        ],
        [
            {"text": "📝 Пост дня", "callback_data": "menu:daily_post"},
            {"text": "📦 Пакет дня", "callback_data": "menu:daily_kit"},
        ],
        [
            {"text": "📊 План", "callback_data": "menu:content_plan"},
            {"text": "🎵 Музыка", "callback_data": "menu:music"},
        ],
        [
            {"text": "⏳ Очередь", "callback_data": "menu:queue"},
            {"text": "🏠 Меню", "callback_data": "menu:main_menu"},
        ],
    ]
    assert client.videos == []


def test_handle_ticker_message_shows_quick_launch_without_render(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("quick launch must not render video")

    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    handle_ticker_message(client, settings, 123, "снять")

    quick_text = client.messages[0][1]
    assert "Быстрый запуск" in quick_text
    assert "Свой ролик" in quick_text
    assert "/help" in quick_text
    assert "Top Studio" in quick_text
    assert client.message_markups == [telegram_bot.quick_launch_keyboard()]
    keyboard = client.message_markups[0]["inline_keyboard"]
    assert keyboard == telegram_bot.main_menu_keyboard()["inline_keyboard"]
    assert client.videos == []


def test_run_telegram_bot_opens_production_guide_without_render(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 63, "message": {"text": "/guide", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("production guide command must not render video")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    assert "Шпаргалка производства шортсов для Пульса" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.production_guide_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_production_guide(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 68,
                    "callback_query": {
                        "id": "callback-menu-guide",
                        "data": "menu:guide",
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

    assert client.callback_answers == [("callback-menu-guide", "Шпаргалка открыта.")]
    assert "Быстрый дневной процесс" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.production_guide_keyboard()]
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


def test_run_telegram_bot_menu_callback_opens_pulse_pack(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 71,
                    "callback_query": {
                        "id": "callback-menu-pack",
                        "data": "menu:pack",
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

    assert client.callback_answers == [("callback-menu-pack", "Пакет открыт.")]
    assert "Пакеты для Пульса" in client.messages[0][1]
    assert "preset metals" not in client.messages[0][1]
    assert "post mechel" not in client.messages[0][1]
    assert client.message_markups == [telegram_bot.pulse_pack_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_content_plan(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 73,
                    "callback_query": {
                        "id": "callback-menu-content-plan",
                        "data": "menu:content_plan",
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

    assert client.callback_answers == [("callback-menu-content-plan", "Контент-план открыт.")]
    assert "Контент-план для Пульса" in client.messages[0][1]
    assert "День 1" in client.messages[0][1]
    assert "preset neweconomy" in client.messages[0][1]
    assert "post metals" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.content_plan_keyboard()]
    assert client.message_markups[0]["inline_keyboard"][0][0]["callback_data"] == "menu:content_plan_shorts"
    assert client.message_markups[0]["inline_keyboard"][1][0]["callback_data"] == "preset:neweconomy:shorts"
    assert client.videos == []


def test_run_telegram_bot_menu_callback_queues_content_plan_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 74,
                    "callback_query": {
                        "id": "callback-menu-content-plan-shorts",
                        "data": "menu:content_plan_shorts",
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
    generated: list[tuple[str | None, int, int, bool]] = []

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-content-plan-shorts", "Контент-план поставлен в очередь.")]
    assert "shorts-роликов контент-плана" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert len(generated) == len(telegram_bot.CONTENT_PLAN_PRESETS)
    assert generated[0] == ("tg-74-plan-shorts-1-neweconomy", 16, 24, True)
    assert generated[-1][0] == f"tg-74-plan-shorts-{len(telegram_bot.CONTENT_PLAN_PRESETS)}-{telegram_bot.CONTENT_PLAN_PRESETS[-1]}"
    assert len(client.videos) == len(telegram_bot.CONTENT_PLAN_PRESETS)


def test_run_telegram_bot_menu_callback_queues_weekly_publication_pack(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 111,
                    "callback_query": {
                        "id": "callback-menu-publication-week",
                        "data": "menu:publication_week",
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
    generated: list[tuple[str | None, int, int, bool, str]] = []

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-publication-week", "Недельный выпуск поставлен в очередь.")]
    assert "Недельный выпуск" in client.messages[0][1]
    assert "Недельный выпуск для Пульса" in client.messages[1][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert client.message_markups[1] == telegram_bot.weekly_publication_pack_keyboard()
    assert len(generated) == len(telegram_bot.CONTENT_PLAN_PRESETS)
    assert generated[0] == ("tg-111-publication-week-1-neweconomy", 16, 24, True, "studio")
    assert generated[-1][0] == f"tg-111-publication-week-{len(telegram_bot.CONTENT_PLAN_PRESETS)}-{telegram_bot.CONTENT_PLAN_PRESETS[-1]}"
    assert len(client.videos) == len(telegram_bot.CONTENT_PLAN_PRESETS)


def test_run_telegram_bot_menu_callback_opens_weekly_posts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 115,
                    "callback_query": {
                        "id": "callback-menu-weekly-posts",
                        "data": "menu:weekly_posts",
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
        raise AssertionError("weekly posts callback must not render video")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-weekly-posts", "Посты недели открыты.")]
    assert len(client.messages) == len(telegram_bot.CONTENT_PLAN_PRESETS) + 1
    assert "Посты недели для Пульса" in client.messages[0][1]
    assert "Пост недели: Д1 Новая экономика 2021-2026" in client.messages[1][1]
    assert "Пост недели: Д7 Голубые фишки" in client.messages[-1][1]
    assert client.message_markups[0] == telegram_bot.weekly_posts_keyboard()
    assert client.videos == []


def test_run_telegram_bot_menu_callback_queues_daily_content_plan_short(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 75,
                    "callback_query": {
                        "id": "callback-menu-daily-short",
                        "data": "menu:daily_short",
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
    generated: list[tuple[str | None, int, int, bool, str]] = []

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "_today", lambda: date(2026, 6, 3))
    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-daily-short", "Шортс дня поставлен в очередь.")]
    assert "Шортс дня" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated == [("tg-75-daily-short-3-banks", 16, 24, True, "default")]
    assert len(client.videos) == 1


def test_run_telegram_bot_menu_callback_queues_daily_publication_day(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 109,
                    "callback_query": {
                        "id": "callback-menu-publication-day",
                        "data": "menu:publication_day",
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
    generated: list[tuple[str | None, int, int, bool, str]] = []

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.duration, request.render.fps, request.render.use_gradient, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "_today", lambda: date(2026, 6, 3))
    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-publication-day", "Публикационный день поставлен в очередь.")]
    assert "Публикационный день: Д3 Банки" in client.messages[0][1]
    assert "Пакет дня: Д3" in client.messages[1][1]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert client.message_markups[1] == telegram_bot.preset_kit_keyboard("banks")
    assert generated == [("tg-109-publication-day-3-banks", 16, 24, True, "default")]
    assert len(client.videos) == 1


def test_run_telegram_bot_menu_callback_opens_daily_post(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 113,
                    "callback_query": {
                        "id": "callback-menu-daily-post",
                        "data": "menu:daily_post",
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
        raise AssertionError("daily post callback must not render video")

    monkeypatch.setattr(telegram_bot, "_today", lambda: date(2026, 6, 3))
    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-daily-post", "Пост дня открыт.")]
    post_text = client.messages[0][1]
    assert "Пост дня: Д3" in post_text
    assert "Пост для Пульса (можно копировать)" in post_text
    assert client.message_markups == [telegram_bot.daily_post_keyboard(date(2026, 6, 3))]
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_daily_content_kit(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 107,
                    "callback_query": {
                        "id": "callback-menu-daily-kit",
                        "data": "menu:daily_kit",
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
        raise AssertionError("daily kit callback must not render video")

    monkeypatch.setattr(telegram_bot, "_today", lambda: date(2026, 6, 3))
    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-daily-kit", "Пакет дня открыт.")]
    kit_text = client.messages[0][1]
    assert "Пакет дня: Д3" in kit_text
    assert "Шортс: preset banks" in kit_text
    assert client.message_markups == [telegram_bot.preset_kit_keyboard("banks")]
    assert client.videos == []


def test_run_telegram_bot_menu_callback_opens_preset_kits(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 72,
                    "callback_query": {
                        "id": "callback-menu-kits",
                        "data": "menu:kits",
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
        raise AssertionError("preset kits menu must not render video")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-kits", "Пакеты открыты.")]
    assert "Публикационные пакеты сценариев" in client.messages[0][1]
    assert "kit metals" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.preset_kit_inline_keyboard()]
    assert client.videos == []


def test_run_telegram_bot_opens_preset_kit_without_render(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 76, "message": {"text": "kit metals", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("kit command must not render video")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    kit_text = client.messages[0][1]
    assert "Пакет сценария" in kit_text
    assert "Шортс: preset metals" in kit_text
    assert "Варианты тем: variants metals" in kit_text
    assert "Пост без рендера: post metals" in kit_text
    assert "Готовые команды:" in kit_text
    assert "- preset metals" in kit_text
    assert "- gold studio" in kit_text
    assert "- черновик gold" in kit_text
    assert "Треки-референсы" in kit_text
    assert client.message_markups == [telegram_bot.preset_kit_keyboard("metals")]
    assert client.videos == []


def test_run_telegram_bot_opens_preset_kit_from_inline_button(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 77,
                    "callback_query": {
                        "id": "callback-kit-metals",
                        "data": "kit:metals",
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
        raise AssertionError("kit callback must not render video")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-kit-metals", "Пакет открыт.")]
    kit_text = client.messages[0][1]
    assert "Пакет сценария" in kit_text
    assert "Шортс: preset metals" in kit_text
    assert client.message_markups == [telegram_bot.preset_kit_keyboard("metals")]
    assert client.videos == []


def test_handle_ticker_message_opens_preset_kit_without_render(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("kit command must not render video")

    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    handle_ticker_message(client, settings, 123, "пакет металлы")

    assert "Пакет сценария" in client.messages[0][1]
    assert "Шортс: preset metals" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.preset_kit_keyboard("metals")]
    assert client.videos == []


def test_handle_ticker_message_lists_preset_kits_without_render(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("kits command must not render video")

    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    handle_ticker_message(client, settings, 123, "/kits")

    assert "Публикационные пакеты сценариев" in client.messages[0][1]
    assert "kit metals" in client.messages[0][1]
    assert client.message_markups == [telegram_bot.preset_kit_inline_keyboard()]
    assert client.videos == []


def test_preset_kit_keyboard_points_to_existing_actions() -> None:
    keyboard = telegram_bot.preset_kit_keyboard("metals")["inline_keyboard"]

    assert keyboard[0][0] == {"text": "Шортс 16s", "callback_data": "preset:metals:shorts"}
    assert keyboard[0][1] == {"text": "Черновик 4s", "callback_data": "preset:metals:draft"}
    assert keyboard[1][0] == {"text": "Все темы x3", "callback_data": "preset:metals:themes"}
    assert keyboard[1][1] == {"text": "12s", "callback_data": "preset:metals:12s"}
    assert keyboard[2][0] == {"text": "Пост", "callback_data": "post:metals"}
    assert keyboard[2][1] == {"text": "Очередь", "callback_data": "queue:status"}


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
    assert "Пост для Пульса (можно копировать)" in client.messages[0][1]
    assert "Металлы часто воспринимают как защиту" in client.messages[0][1]
    assert "Обложка:" in client.messages[0][1]
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

    assert "Пост для Пульса (можно копировать)" in client.messages[0][1]
    assert "Металлы часто воспринимают как защиту" in client.messages[0][1]
    assert "Обложка:" in client.messages[0][1]
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
    assert "Пост для Пульса (можно копировать)" in client.messages[0][1]
    assert "Заголовок:" not in client.messages[0][1]
    assert "Хук:" not in client.messages[0][1]
    assert "На видео сравнение активов на одной шкале: LKOH / SBER." in client.messages[0][1]
    assert "Параметры: 01.01.2020 - 31.12.2024, RUB, капитал с реинвестированием." in client.messages[0][1]
    assert "Обложка:" in client.messages[0][1]


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
    assert "Пост для Пульса (можно копировать)" in client.messages[0][1]
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


def test_run_telegram_bot_menu_callback_queues_all_preset_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 65,
                    "callback_query": {
                        "id": "callback-menu-all-shorts",
                        "data": "menu:all_shorts",
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

    assert client.callback_answers == [("callback-menu-all-shorts", "Все shorts поставлены в очередь.")]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated[0] == ("tg-65-shorts-1-neweconomy", 16, 24, True)
    assert generated[-1][0] == f"tg-65-shorts-{len(PRESETS)}-{PRESETS[-1].name}"
    assert len(generated) == len(PRESETS)
    assert len(client.videos) == len(PRESETS)


def test_run_telegram_bot_menu_callback_queues_styled_all_preset_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 67,
                    "callback_query": {
                        "id": "callback-menu-all-shorts-aurora",
                        "data": "menu:all_shorts_aurora",
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
    generated: list[tuple[str | None, str]] = []

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-all-shorts-aurora", "Все shorts Aurora поставлены в очередь.")]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated[0] == ("tg-67-shorts-aurora-1-neweconomy", "aurora")
    assert generated[-1][0] == f"tg-67-shorts-aurora-{len(PRESETS)}-{PRESETS[-1].name}"
    assert len(generated) == len(PRESETS)
    assert all(theme == "aurora" for _job_id, theme in generated)
    assert len(client.videos) == len(PRESETS)


def test_run_telegram_bot_menu_callback_queues_styled_hot_preset_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 73,
                    "callback_query": {
                        "id": "callback-menu-hot-shorts-aurora",
                        "data": "menu:hot_shorts_aurora",
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
    generated: list[tuple[str | None, str]] = []

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [
        ("callback-menu-hot-shorts-aurora", "Top-shorts Aurora поставлены в очередь.")
    ]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated == [
        ("tg-73-hot-shorts-aurora-1-metals", "aurora"),
        ("tg-73-hot-shorts-aurora-2-neweconomy", "aurora"),
        ("tg-73-hot-shorts-aurora-3-vodka", "aurora"),
        ("tg-73-hot-shorts-aurora-4-mechel", "aurora"),
    ]
    assert len(client.videos) == 4


def test_run_telegram_bot_queues_preset_theme_variants_from_text(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [{"update_id": 74, "message": {"text": "variants metals", "chat": {"id": 123}}}]

    client = FakePollingClient()
    settings = TelegramBotSettings(
        token="token",
        once=True,
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2), theme="default"),
    )
    generated: list[tuple[str | None, str, int, int, bool]] = []

    def fake_generate(request, job_id=None):
        generated.append(
            (job_id, request.render.theme, request.render.duration, request.render.fps, request.render.use_gradient)
        )
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated == [
        ("tg-74-theme-1-default-metals", "default", 16, 24, True),
        ("tg-74-theme-2-aurora-metals", "aurora", 16, 24, True),
        ("tg-74-theme-3-studio-metals", "studio", 16, 24, True),
    ]
    assert len(client.videos) == 3


def test_run_telegram_bot_queues_preset_theme_variants_from_followup_button(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 75,
                    "callback_query": {
                        "id": "callback-preset-theme-variants",
                        "data": "preset:metals:themes",
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
    generated: list[tuple[str | None, str]] = []

    def fake_generate(request, job_id=None):
        generated.append((job_id, request.render.theme))
        return Path(f"animations/{job_id}.mp4")

    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(telegram_bot, "generate_video", fake_generate)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [
        ("callback-preset-theme-variants", "Варианты по темам поставлены в очередь.")
    ]
    assert client.message_markups[0] == telegram_bot.queue_status_keyboard()
    assert generated == [
        ("tg-75-theme-1-default-metals", "default"),
        ("tg-75-theme-2-aurora-metals", "aurora"),
        ("tg-75-theme-3-studio-metals", "studio"),
    ]
    assert len(client.videos) == 3


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


def test_run_telegram_bot_menu_callback_queues_random_preset_shorts(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 60,
                    "callback_query": {
                        "id": "callback-menu-random-shorts",
                        "data": "menu:random_shorts",
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
    generated: list[tuple[str | None, int, int, bool, list[str]]] = []
    selected = PRESETS[1]

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
    monkeypatch.setattr(telegram_bot.random, "choice", lambda presets: selected)

    telegram_bot.run_telegram_bot(settings)

    assert client.callback_answers == [("callback-menu-random-shorts", "Случайный шортс поставлен в очередь.")]
    assert telegram_bot.queue_status_keyboard() in client.message_markups
    assert generated == [("tg-60-random-shorts-metals", 16, 24, True, ["GC=F", "SI=F", "PA=F"])]
    assert client.videos == [(123, Path("animations/tg-60-random-shorts-metals.mp4"), "GC=F / SI=F / PA=F: 2010-01-01 - 2026-05-27")]


def test_run_telegram_bot_queues_multiline_batch(monkeypatch) -> None:
    class FakePollingClient(FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__()

        def get_updates(self, *_args, **_kwargs):
            return [
                {
                    "update_id": 52,
                    "message": {
                        "text": "- LKOH\n1. SBER 2020 2024\n• preset metals draft",
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
    assert any("1. LKOH" in message for _chat_id, message in client.messages)
    assert any("2. SBER 2020 2024" in message for _chat_id, message in client.messages)
    assert any("3. preset metals draft" in message for _chat_id, message in client.messages)
    assert telegram_bot.queue_status_keyboard() in client.message_markups
    assert len(client.videos) == 3


def test_batch_request_lines_accept_common_list_markers() -> None:
    assert telegram_bot._batch_request_lines("- LKOH\n1) SBER 2020 2024\n• preset metals draft\n\n* AAPL global USD") == [
        "LKOH",
        "SBER 2020 2024",
        "preset metals draft",
        "AAPL global USD",
    ]


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


def test_handle_ticker_message_mentions_queue_mode_for_all_shorts() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/all_shorts")

    assert client.messages == [(123, "Команда полного пакета shorts-роликов работает в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_mentions_queue_mode_for_styled_all_shorts() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/all_shorts aurora")

    assert client.messages == [(123, "Команда полного пакета shorts-роликов в теме aurora работает в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_mentions_queue_mode_for_styled_hot_shorts() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "топ шортсы студио")

    assert client.messages == [(123, "Команда top-shorts роликов в теме studio работает в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_mentions_queue_mode_for_random_shorts() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "случайный шортс")

    assert client.messages == [(123, "Команда случайного shorts-ролика работает в режиме Telegram-очереди.")]
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
    assert pulse_text.startswith("Пост для Пульса (можно копировать):")
    assert "Заголовок:" not in pulse_text
    assert "Хук:" not in pulse_text
    assert "Если каждый месяц откладывать 30 000 RUB" in pulse_text
    assert "На видео ежемесячные покупки против разных активов: GC=F / SI=F / PA=F." in pulse_text
    assert "Обложка:\n- 30 000 RUB/мес: кто выиграл?" in pulse_text
    assert "Вопрос для обсуждения: вы бы выдержали такую регулярную стратегию" in pulse_text
    assert "Монтаж:\n- Настроение: плотный драматичный бит" in pulse_text
    assert "GC=F / SI=F / PA=F" in pulse_text
    assert "ежемесячно 30 000 RUB" in pulse_text
    assert "#сырье" in pulse_text
    assert "Не инвестиционная рекомендация" in pulse_text
    assert "Инвестиции: ежемесячно 30 000 RUB" in client.messages[0][1]
    assert "Тема: default" in client.messages[0][1]


def test_format_generic_pulse_post_uses_single_asset_hook() -> None:
    base = RenderSettings(start_date=date(2020, 1, 1), end_date=date(2024, 12, 31))
    parsed = parse_telegram_video_request("LKOH 2020 2024 close", base)

    pulse_text = telegram_bot.format_generic_pulse_post(parsed)

    assert pulse_text.startswith("Пост для Пульса (можно копировать):")
    assert "Заголовок:" not in pulse_text
    assert "Хук:" not in pulse_text
    assert "Один график, который быстро показывает характер LKOH" in pulse_text
    assert "На видео один актив на истории: LKOH." in pulse_text
    assert "Обложка:\n- LKOH: график без лишних слов" in pulse_text
    assert "Вопрос для обсуждения: это больше похоже на возможность" in pulse_text
    assert "Монтаж:\n- Настроение: минималистичный бит" in pulse_text
    assert "Параметры: 01.01.2020 - 31.12.2024, RUB, цена закрытия." in pulse_text
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
    assert "В работе: нет активного рендера" in pending_status
    assert "Ожидают: 2" in pending_status
    assert "ID tg-48 - LKOH" in pending_status
    assert "ID tg-49 - SBER" in pending_status

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
        assert "В работе: ID tg-48 - LKOH" in active_status
        assert "Ожидают: 1" in active_status
        assert "ID tg-49 - SBER" in active_status

        release.set()
        queue.join()
        finished_status = queue.status_text()
    finally:
        release.set()
        queue.stop()

    assert "В работе: нет активного рендера" in finished_status
    assert "Ожидают: 0" in finished_status
    assert "Завершено: 2, ошибки: 0" in finished_status


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


def test_telegram_job_queue_status_shows_wait_and_runtime(monkeypatch) -> None:
    current_time = 1_000.0

    def fake_monotonic() -> float:
        return current_time

    monkeypatch.setattr(telegram_bot.time, "monotonic", fake_monotonic)

    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )
    queue = telegram_bot.TelegramJobQueue(client, settings)

    job = queue.enqueue(123, "LKOH SBER shorts", 54, notify=False)
    current_time = 1_125.0
    pending_status = queue.status_text()

    assert "ID tg-54 - LKOH SBER shorts (ждет 2м 05с)" in pending_status

    queue._mark_started(job)
    current_time = 1_251.0
    active_status = queue.status_text()

    assert "В работе: ID tg-54 - LKOH SBER shorts" in active_status
    assert "Идет: 2м 06с" in active_status
    assert "Ждал перед стартом: 2м 05с" in active_status


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

    assert client.messages == [(123, "Очередь Telegram\nВ работе: нет активного рендера\nОжидают: 0\nЗавершено: 0, ошибки: 0")]
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
    assert client.messages == [(123, "Очередь Telegram\nВ работе: нет активного рендера\nОжидают: 0\nЗавершено: 0, ошибки: 0")]
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


def test_help_text_is_compact_and_actionable() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/help")

    help_text = client.messages[0][1]
    assert "Как попросить ролик" in help_text
    assert len(help_text) < 700
    assert len(help_text.splitlines()) <= 14
    assert client.message_markups == [telegram_bot.help_keyboard()]
    assert "/queue" in help_text
    assert "/shorts без текста" in help_text
    assert "/shorts SBER LKOH за год" in help_text
    assert "Долгий рендер" in help_text
    assert "статус" in help_text
    assert "/guide" in help_text
    assert "Истории" in help_text
    assert "Случайный" in help_text
    assert "Справочник" not in help_text
    assert "/draft metals" not in help_text
    assert "top quiet" not in help_text
    assert "AAPL global USD shorts" not in help_text
    assert "золото серебро палладий 2010-2026 RUB капитал с нуля ежемесячно 30к₽ gradient" in help_text
    assert "monthly=30000" not in help_text
    assert "top shorts studio" not in help_text
    assert "случайный шортс" not in help_text
    assert "/week_posts" not in help_text
    assert "/today_post" not in help_text
    assert "/posts" not in help_text
    assert "post metals" not in help_text
    assert "theme=default|aurora|studio" not in help_text
    assert "top shorts aurora" not in help_text
    assert "/random_draft" not in help_text
    assert "all shorts aurora" not in help_text
    assert "SiH4 futures" not in help_text


def test_help_keyboard_points_to_guidance_actions() -> None:
    keyboard = telegram_bot.help_keyboard()

    callbacks = [
        [button["callback_data"] for button in row]
        for row in keyboard["inline_keyboard"]
    ]

    assert callbacks == [
        ["menu:publication_day", "menu:publication_week"],
        ["menu:preset_categories", "menu:examples"],
        ["menu:content_plan", "menu:guide"],
        [telegram_bot.QUEUE_STATUS_CALLBACK_DATA, "menu:main_menu"],
    ]
    assert keyboard != telegram_bot.main_menu_keyboard()


def test_handle_ticker_message_shows_main_menu() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/menu")

    assert "Меню для Пульса" in client.messages[0][1]
    assert "Шесть частых действий" in client.messages[0][1]
    assert "Свой запрос" in client.messages[0][1]
    assert "топовые shorts-сценарии" not in client.messages[0][1]
    assert "полный пакет shorts" not in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.main_menu_keyboard()
    keyboard = client.message_markups[0]["inline_keyboard"]
    assert keyboard == [
        [
            {"text": "📅 День", "callback_data": "menu:publication_day"},
            {"text": "🗓 Неделя", "callback_data": "menu:publication_week"},
        ],
        [
            {"text": "✨ Top Studio", "callback_data": "menu:hot_shorts_studio"},
            {"text": "🎲 Случайный", "callback_data": "menu:random_shorts"},
        ],
        [
            {"text": "📚 Истории", "callback_data": "menu:preset_categories"},
            {"text": "⏳ Очередь", "callback_data": "menu:queue"},
        ],
    ]
    assert client.videos == []


def test_handle_ticker_message_start_shows_main_menu() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/start")

    assert "Меню для Пульса" in client.messages[0][1]
    assert client.message_markups[0] == telegram_bot.main_menu_keyboard()
    assert client.videos == []


def test_handle_ticker_message_shorts_slash_without_payload_shows_presets(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("empty /shorts command must not render video")

    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    handle_ticker_message(client, settings, 123, "/shorts")

    assert "Истории для Пульса" in client.messages[0][1]
    assert "Тихие российские истории" in client.messages[0][1]
    assert "Выберите категорию кнопкой ниже" in client.messages[0][1]
    assert "shorts 16s" in client.messages[0][1]
    assert "/shorts SBER LKOH за год" in client.messages[0][1]
    assert "preset metals" not in client.messages[0][1]
    assert "category drama" not in client.messages[0][1]
    assert client.message_markups == [telegram_bot.preset_category_inline_keyboard(mode="shorts")]
    assert client.videos == []


def test_handle_ticker_message_draft_slash_without_payload_shows_draft_presets(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("empty /draft command must not render video")

    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    handle_ticker_message(client, settings, 123, "/draft")

    assert "Черновики по категориям" in client.messages[0][1]
    assert "draft 4s" in client.messages[0][1]
    assert "preset metals" not in client.messages[0][1]
    assert client.message_markups == [telegram_bot.preset_category_inline_keyboard(mode="draft")]
    assert client.message_markups[0]["inline_keyboard"][-1][0] == {
        "text": "Полный список",
        "callback_data": "menu:draft_presets",
    }
    assert client.videos == []


def test_handle_ticker_message_shows_main_menu_with_russian_command() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/меню")

    assert "Меню для Пульса" in client.messages[0][1]
    assert client.message_markups[0]["inline_keyboard"][0][0]["callback_data"] == "menu:publication_day"
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


def test_handle_ticker_message_shows_pulse_pack() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/pack")

    pack_text = client.messages[0][1]
    assert "Пакеты для Пульса" in pack_text
    assert "готовые production-действия" in pack_text
    assert "Справочнике" in pack_text
    assert "preset metals" not in pack_text
    assert "post metals" not in pack_text
    assert "top shorts aurora" not in pack_text
    assert "без LLM" in pack_text
    assert client.message_markups[0] == telegram_bot.pulse_pack_keyboard()
    assert client.message_markups[0]["inline_keyboard"][0][0]["callback_data"] == "menu:hot_shorts_studio"
    assert client.message_markups[0]["inline_keyboard"][0][1]["callback_data"] == "menu:random_shorts"
    assert client.message_markups[0]["inline_keyboard"][1][0]["callback_data"] == "menu:hot_shorts"
    assert client.message_markups[0]["inline_keyboard"][1][1]["callback_data"] == "menu:hot_drafts"
    assert client.message_markups[0]["inline_keyboard"][2][0]["callback_data"] == "menu:all_shorts"
    assert client.message_markups[0]["inline_keyboard"][2][1]["callback_data"] == "menu:all_shorts_studio"
    assert client.message_markups[0]["inline_keyboard"][3][0]["callback_data"] == "menu:reference"
    assert client.message_markups[0]["inline_keyboard"][3][1]["callback_data"] == "menu:queue"
    assert client.videos == []


def test_handle_ticker_message_shows_pulse_pack_with_russian_command() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "пакет пульса")

    assert "Пакеты для Пульса" in client.messages[0][1]
    assert "post mechel" not in client.messages[0][1]
    assert client.message_markups[0]["inline_keyboard"][1][1]["callback_data"] == "menu:hot_drafts"
    assert client.videos == []


def test_handle_ticker_message_shows_content_plan() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "план пульса")

    plan_text = client.messages[0][1]
    assert "Контент-план для Пульса" in plan_text
    assert "7 выпусков без LLM" in plan_text
    assert "День 1" in plan_text
    assert "preset neweconomy" in plan_text
    assert "post metals" in plan_text
    assert "Первая кнопка ставит все 7 shorts" in plan_text
    assert client.message_markups[0] == telegram_bot.content_plan_keyboard()
    keyboard = client.message_markups[0]["inline_keyboard"]
    assert keyboard[0][0]["callback_data"] == "menu:content_plan_shorts"
    assert keyboard[0][1]["callback_data"] == "menu:weekly_posts"
    assert keyboard[1][0]["callback_data"] == "preset:neweconomy:shorts"
    assert keyboard[1][1]["callback_data"] == "preset:metals:shorts"
    assert keyboard[2][1]["callback_data"] == "preset:telecoms:shorts"
    assert keyboard[3][0]["callback_data"] == "preset:retailers:shorts"
    assert keyboard[3][1]["callback_data"] == "preset:utilities:shorts"
    assert keyboard[-1][1]["callback_data"] == telegram_bot.QUEUE_STATUS_CALLBACK_DATA
    assert client.videos == []


def test_handle_ticker_message_shows_daily_content_kit(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("daily content kit must not render video")

    monkeypatch.setattr(telegram_bot, "_today", lambda: date(2026, 6, 3))
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    handle_ticker_message(client, settings, 123, "пакет дня")

    kit_text = client.messages[0][1]
    assert "Пакет дня: Д3" in kit_text
    assert "Шортс: preset banks" in kit_text
    assert "Пост без рендера: post banks" in kit_text
    assert client.message_markups == [telegram_bot.preset_kit_keyboard("banks")]
    assert client.videos == []


def test_handle_ticker_message_shows_daily_post(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("daily post must not render video")

    monkeypatch.setattr(telegram_bot, "_today", lambda: date(2026, 6, 3))
    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    handle_ticker_message(client, settings, 123, "/today_post")

    post_text = client.messages[0][1]
    assert "Пост дня: Д3" in post_text
    assert "Пост для Пульса (можно копировать)" in post_text
    assert "#сбер" in post_text
    assert "#втб" in post_text
    assert client.message_markups == [telegram_bot.daily_post_keyboard(date(2026, 6, 3))]
    assert client.videos == []


def test_handle_ticker_message_mentions_queue_mode_for_content_plan_shorts() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "снять план")

    assert client.messages == [(123, "Команда запуска контент-плана работает в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_mentions_queue_mode_for_weekly_publication_pack() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "снять неделю")

    assert client.messages == [(123, "Команда недельного выпуска работает в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_shows_weekly_posts_without_render(monkeypatch) -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("weekly posts must not render video")

    monkeypatch.setattr(telegram_bot, "generate_video", fail_generate)

    handle_ticker_message(client, settings, 123, "посты недели")

    assert len(client.messages) == len(telegram_bot.CONTENT_PLAN_PRESETS) + 1
    assert "Посты недели для Пульса" in client.messages[0][1]
    assert "Пост недели: Д1 Новая экономика 2021-2026" in client.messages[1][1]
    assert "Пост недели: Д7 Голубые фишки" in client.messages[-1][1]
    assert client.message_markups[0] == telegram_bot.weekly_posts_keyboard()
    assert client.videos == []


def test_handle_ticker_message_mentions_queue_mode_for_daily_short() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "шортс дня")

    assert client.messages == [(123, "Команда шортса дня работает в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_mentions_queue_mode_for_publication_day() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "снять день")

    assert client.messages == [(123, "Команда публикационного дня работает в режиме Telegram-очереди.")]
    assert client.videos == []


def test_handle_ticker_message_shows_preset_post_without_rendering() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "пост металлы")

    post_text = client.messages[0][1]
    assert "Пост для Пульса (можно копировать)" in post_text
    assert "Что было бы, если 16 лет подряд" in post_text
    assert "Обложка:" in post_text
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
    assert "preset banks" in preset_text
    assert "preset dividends" in preset_text
    assert "preset builders" in preset_text
    assert "/queue" in preset_text
    assert "все шортсы" in preset_text
    assert "12s" in preset_text
    assert "Aurora 16s" in preset_text
    assert "Studio 16s" in preset_text
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


def test_all_pulse_presets_have_valid_categories() -> None:
    category_names = {category.name for category in PRESET_CATEGORIES}
    preset_names = {preset.name for preset in PRESETS}
    category_to_presets = {category.name: set(category.preset_names) for category in PRESET_CATEGORIES}

    assert category_names == {"quiet", "drama", "commodities", "growth", "weekly"}
    for preset in PRESETS:
        assert preset.categories
        assert set(preset.categories) <= category_names
        for category_name in preset.categories:
            assert preset.name in category_to_presets[category_name]

    for category in PRESET_CATEGORIES:
        assert category.preset_names
        assert set(category.preset_names) <= preset_names
        for preset_name in category.preset_names:
            assert category.name in get_preset(preset_name).categories


def test_weekly_category_matches_production_plan() -> None:
    assert telegram_bot.CONTENT_PLAN_PRESETS == get_preset_category("weekly").preset_names


def test_handle_ticker_message_lists_preset_categories() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "категории")

    category_text = client.messages[0][1]
    assert "Истории для Пульса" in category_text
    assert "Тихие российские истории" in category_text
    assert "Драмы и просадки" in category_text
    assert "Выберите категорию кнопкой ниже" in category_text
    assert "category drama" not in category_text
    assert client.message_markups[0] == telegram_bot.preset_category_inline_keyboard()
    assert client.message_markups[0]["inline_keyboard"][0][0]["callback_data"] == "category:quiet"
    assert client.videos == []


def test_handle_ticker_message_opens_preset_category() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "category drama")

    category_text = client.messages[0][1]
    assert "Категория: Драмы и просадки" in category_text
    assert "Новая экономика" in category_text
    assert "Кнопки ниже запускают shorts 16s" in category_text
    assert "Команды:" not in category_text
    assert "черновик new" not in category_text
    assert client.message_markups[0] == telegram_bot.preset_category_keyboard("drama")
    assert client.message_markups[0]["inline_keyboard"][0][0]["callback_data"] == "preset:neweconomy:shorts"
    assert client.videos == []


def test_handle_ticker_message_lists_draft_presets() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/drafts")

    preset_text = client.messages[0][1]
    assert "Черновики по категориям" in preset_text
    assert "draft 4s" in preset_text
    assert "preset metals" not in preset_text
    assert client.message_markups[0] == telegram_bot.preset_category_inline_keyboard(mode="draft")
    assert client.videos == []


def test_handle_ticker_message_lists_draft_presets_with_russian_command() -> None:
    client = FakeClient()
    settings = TelegramBotSettings(
        token="token",
        render=RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
    )

    handle_ticker_message(client, settings, 123, "/черновики")

    assert "Черновики по категориям" in client.messages[0][1]
    assert client.message_markups[0]["inline_keyboard"][0][0]["callback_data"] == "category:quiet:draft"
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


def test_parse_telegram_video_request_accepts_zero_initial_phrase() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("SBER LKOH капитал с нуля ежемесячно 30к рублей", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.currency == "RUB"
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.initial_investment == 0
    assert parsed.request.render.monthly_investment == 30_000


def test_parse_telegram_video_request_accepts_without_initial_contribution_phrase() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request(
        "SBER LKOH капитал без первоначального взноса по 30к ежемесячно",
        base,
    )

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH"]
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.initial_investment == 0
    assert parsed.request.render.monthly_investment == 30_000


def test_parse_telegram_video_request_accepts_zero_word_initial_amount() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("SBER LKOH капитал старт ноль каждый месяц 30к", base)

    assert parsed.request.render.with_investments is True
    assert parsed.request.render.initial_investment == 0
    assert parsed.request.render.monthly_investment == 30_000


def test_parse_telegram_video_request_accepts_periodic_adverb_after_amount() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request("SBER LKOH капитал по 120к ежегодно", base)

    assert parsed.request.render.with_investments is True
    assert parsed.request.render.yearly_investment == 120_000


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


def test_parse_telegram_video_request_accepts_duration_shortcut() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), duration=30, fps=20)

    parsed = parse_telegram_video_request("lkoh sber 2020 2024 12s", base)

    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["LKOH", "SBER"]
    assert parsed.request.render.duration == 12
    assert parsed.request.render.fps == 20


def test_parse_telegram_video_request_accepts_russian_duration_shortcut() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), duration=30, fps=20)

    parsed = parse_telegram_video_request("lkoh sber 2020 2024 7сек", base)

    assert parsed.request.render.duration == 7
    assert parsed.request.render.fps == 20


def test_parse_telegram_video_request_duration_shortcut_overrides_shorts_duration() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), duration=30, fps=20)

    parsed = parse_telegram_video_request("lkoh sber 2020 2024 shorts 12s", base)

    assert parsed.request.render.duration == 12
    assert parsed.request.render.fps == 24
    assert parsed.request.render.use_gradient is True


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


@pytest.mark.parametrize(
    ("text", "preset_name", "tickers"),
    [
        ("телеком", "telecoms", ["MTSS", "RTKM", "RTKMP"]),
        ("ритейл studio", "retailers", ["MGNT", "FIVE", "FIXP"]),
        ("энергетика", "utilities", ["IRAO", "FEES", "HYDR"]),
    ],
)
def test_parse_telegram_video_request_accepts_new_quiet_preset_shortcuts(
    text: str, preset_name: str, tickers: list[str]
) -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request(text, base)

    assert parsed.preset_name == preset_name
    assert [spec.ticker for spec in parsed.request.ticker_specs] == tickers
    assert parsed.request.render.with_investments is True
    assert parsed.request.render.monthly_investment == 30_000


def test_parse_telegram_video_request_accepts_direct_preset_theme_suffix() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), theme="default")

    parsed = parse_telegram_video_request("металлы студио", base)

    assert parsed.preset_name == "metals"
    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["GC=F", "SI=F", "PA=F"]
    assert parsed.request.render.theme == "studio"
    assert parsed.request.render.duration == 16
    assert parsed.request.render.use_gradient is True


def test_parse_telegram_video_request_accepts_direct_preset_theme_prefix() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), theme="default")

    parsed = parse_telegram_video_request("aurora голубые фишки", base)

    assert parsed.preset_name == "bluechips"
    assert [spec.ticker for spec in parsed.request.ticker_specs] == ["SBER", "LKOH", "MGNT"]
    assert parsed.request.render.theme == "aurora"


def test_parse_telegram_video_request_accepts_direct_draft_preset_theme_prefix() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), theme="default")

    parsed = parse_telegram_video_request("студио черновик металлы", base)

    assert parsed.preset_name == "metals"
    assert parsed.request.render.theme == "studio"
    assert parsed.request.render.duration == 4
    assert parsed.request.render.fps == 8
    assert parsed.request.render.use_gradient is False


def test_parse_telegram_video_request_accepts_direct_preset_theme_before_options() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), theme="default")

    parsed = parse_telegram_video_request("металлы студио duration=12", base)

    assert parsed.preset_name == "metals"
    assert parsed.request.render.theme == "studio"
    assert parsed.request.render.duration == 12


def test_parse_telegram_video_request_accepts_direct_preset_duration_shortcut() -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1), theme="default")

    parsed = parse_telegram_video_request("металлы студио 12с", base)

    assert parsed.preset_name == "metals"
    assert parsed.request.render.theme == "studio"
    assert parsed.request.render.duration == 12
    assert parsed.request.render.fps == 24


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


@pytest.mark.parametrize(
    ("text", "preset_name", "tickers"),
    [
        ("банки", "banks", ["SBER", "SBERP", "VTBR"]),
        ("дивиденды duration=12", "dividends", ["SNGSP", "TRNFP", "CHMF"]),
        ("стройка студио", "builders", ["PIKK", "LSRG", "SMLT"]),
    ],
)
def test_parse_telegram_video_request_accepts_new_russian_story_shortcuts(
    text: str, preset_name: str, tickers: list[str]
) -> None:
    base = RenderSettings(start_date=date(2015, 1, 1), end_date=date(2020, 1, 1))

    parsed = parse_telegram_video_request(text, base)

    assert parsed.preset_name == preset_name
    assert [spec.ticker for spec in parsed.request.ticker_specs] == tickers
    assert parsed.request.render.monthly_investment == 30_000
    assert parsed.request.render.use_gradient is True


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
    assert "Пост для Пульса (можно копировать)" in client.messages[-2][1]
    assert "Что было бы" in client.messages[-2][1]
    assert "Обложка:" in client.messages[-2][1]
    assert "Монтаж:" in client.messages[-2][1]
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
    assert "Пост для Пульса (можно копировать)" in client.messages[-2][1]
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
        assert post.startswith("Пост для Пульса (можно копировать):")
        assert "Обложка:" in post
        assert "Монтаж:" in post
        assert "Треки-референсы" in post
        assert "права проверять отдельно" in post
        assert "Не является индивидуальной инвестиционной рекомендацией." in post
        assert post.index("Обложка:") > post.index("Не является индивидуальной инвестиционной рекомендацией.")


def test_all_pulse_presets_have_human_button_labels() -> None:
    labels = [preset_button_label(preset) for preset in PRESETS]

    assert "Металлы" in labels
    assert "Новая экономика" in labels
    assert "Угольщики" in labels
    assert "Банки" in labels
    assert "Дивиденды" in labels
    assert "Строители" in labels
    assert "Связь" in labels
    assert "Ритейл" in labels
    assert "Энергетика" in labels
    assert all(label and len(label) <= 24 for label in labels)
