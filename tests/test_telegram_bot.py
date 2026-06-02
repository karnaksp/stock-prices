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
    assert "monthly=30000" in help_text
    assert "shorts" in help_text
    assert "draft" in help_text
    assert "/drafts" in help_text
    assert "/черновики" in help_text
    assert "все черновики" in help_text
    assert "случайный черновик" in help_text
    assert "/random_draft" in help_text
    assert "/queue" in help_text
    assert "очередь" in help_text
    assert "Статус очереди" in help_text
    assert "несколько запросов строками" in help_text
    assert "черновик металлы" in help_text
    assert "пресет металлы" in help_text
    assert "вариант 12s" in help_text
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
        assert "Текст для Пульса" in post
        assert "Не является индивидуальной инвестиционной рекомендацией." in post


def test_all_pulse_presets_have_human_button_labels() -> None:
    labels = [preset_button_label(preset) for preset in PRESETS]

    assert "Металлы" in labels
    assert "Новая экономика" in labels
    assert "Угольщики" in labels
    assert all(label and len(label) <= 24 for label in labels)
