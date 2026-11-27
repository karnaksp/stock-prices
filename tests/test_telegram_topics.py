from datetime import date
from types import SimpleNamespace

import pytest

from stock_prices._internal import telegram_bot
from stock_prices._internal.models import RenderSettings
from stock_prices._internal.telegram_topics import get_group_topic_ids, update_is_in_group_topic


@pytest.mark.parametrize("raw", ['[]', '{"123": 7}', '{"-123": 0}', '{"-123": true}',
                                  '{"-123": "7"}', '{"-123": 1.5}', 'invalid'])
def test_invalid_routes_fail_without_exposing_configuration(monkeypatch, raw):
    monkeypatch.setenv("STOCK_PRICES_GROUP_TOPICS", raw)
    with pytest.raises(ValueError, match="STOCK_PRICES_GROUP_TOPICS must map"):
        get_group_topic_ids()


def test_routes_are_optional_and_parse_group_ids(monkeypatch):
    monkeypatch.delenv("STOCK_PRICES_GROUP_TOPICS", raising=False)
    assert get_group_topic_ids() == {}
    monkeypatch.setenv("STOCK_PRICES_GROUP_TOPICS", '{"-123": 7}')
    assert get_group_topic_ids() == {-123: 7}


@pytest.mark.parametrize("topic, expected", [(7, True), (8, False), (None, False)])
@pytest.mark.parametrize("callback", [False, True])
def test_messages_and_buttons_stay_in_the_configured_topic(topic, expected, callback):
    message = {"chat": {"id": -123}, "message_thread_id": topic}
    update = {"callback_query": {"message": message}} if callback else {"message": message}
    assert update_is_in_group_topic(update, {-123: 7}) is expected


def test_private_chats_and_other_groups_are_unchanged():
    for chat_id in (123, -456):
        assert update_is_in_group_topic({"message": {"chat": {"id": chat_id}}}, {-123: 7})


def test_text_and_video_delivery_use_the_group_route(monkeypatch, tmp_path):
    calls = []

    def post(url, **kwargs):
        calls.append((url.rsplit("/", 1)[-1], dict(kwargs["data"])))
        return SimpleNamespace(ok=True, json=lambda: {"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(telegram_bot.requests, "post", post)
    client = telegram_bot.TelegramClient("test-token", group_topic_ids={-123: 7})
    video = tmp_path / "test.mp4"
    video.write_bytes(b"test")
    client.send_message(-123, "status")
    client.send_video(-123, video, "chart")
    client.send_message(123, "private")
    client.send_video(123, video, "private chart")
    client.get_updates(None, 1)

    assert [method for method, _ in calls] == ["sendMessage", "sendVideo", "sendMessage", "sendVideo", "getUpdates"]
    assert [data.get("message_thread_id") for _, data in calls] == [7, 7, None, None, None]


def test_polling_ignores_wrong_topic_before_running_commands(monkeypatch):
    messages = []
    callbacks = []
    updates = [
        {"update_id": 1, "message": {"chat": {"id": -123}, "text": "/menu", "message_thread_id": 8}},
        {"update_id": 2, "callback_query": {"id": "old-button", "message": {"chat": {"id": -123}}, "data": "menu:main"}},
        {"update_id": 3, "message": {"chat": {"id": -123}, "text": "/menu", "message_thread_id": 7}},
        {"update_id": 4, "message": {"chat": {"id": 123}, "text": "/menu"}},
    ]

    class Client:
        def get_updates(self, **kwargs):
            return updates

        def send_message(self, chat_id, text, **kwargs):
            messages.append(chat_id)

        def answer_callback_query(self, callback_id, text):
            callbacks.append(callback_id)

    client = Client()
    monkeypatch.setattr(telegram_bot, "TelegramClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(telegram_bot, "configure_telegram_command_menu", lambda *args: None)
    monkeypatch.setattr(telegram_bot, "configure_telegram_mini_app_menu_button", lambda *args, **kwargs: None)
    monkeypatch.setattr(telegram_bot, "TelegramJobQueue", lambda *args: SimpleNamespace(start=lambda: None, join=lambda: None, stop=lambda: None))
    settings = telegram_bot.TelegramBotSettings(
        "test-token", RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
        once=True, group_topic_ids={-123: 7},
    )
    telegram_bot.run_telegram_bot(settings)

    assert messages == [-123, 123]
    assert callbacks == ["old-button"]


def test_queue_command_accepts_bot_address():
    assert telegram_bot._is_queue_status("/queue@karnaksp_cicd_bot")
    assert not telegram_bot._is_queue_status("/queue@karnaksp_cicd_bot SBER")


def test_explicit_telegram_rate_limit_waits_before_retry(monkeypatch):
    calls, sleeps = [], []

    def post(url, **kwargs):
        calls.append(kwargs["data"])
        payload = ({"ok": False, "error_code": 429, "parameters": {"retry_after": 30}}
                   if len(calls) == 1 else {"ok": True, "result": {"message_id": 1}})
        return SimpleNamespace(ok=payload["ok"], json=lambda: payload, text="limited")

    monkeypatch.setattr(telegram_bot.requests, "post", post)
    monkeypatch.setattr(telegram_bot.time, "sleep", sleeps.append)
    client = telegram_bot.TelegramClient("test-token", group_topic_ids={-123: 7})
    client.send_message(-123, "status")
    assert sleeps == [30]
    assert len(calls) == 2
    assert all(data["message_thread_id"] == 7 for data in calls)


def test_network_error_is_not_retried_because_delivery_is_uncertain(monkeypatch):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        raise telegram_bot.requests.Timeout("timeout")

    monkeypatch.setattr(telegram_bot.requests, "post", post)
    with pytest.raises(telegram_bot.TelegramApiError, match="request failed"):
        telegram_bot.TelegramClient("test-token").send_message(-123, "status")
    assert len(calls) == 1


def test_video_retry_rewinds_the_upload_and_keeps_the_topic(monkeypatch, tmp_path):
    uploads, topics, sleeps = [], [], []

    def post(url, **kwargs):
        uploads.append(kwargs["files"]["video"][1].read())
        topics.append(kwargs["data"]["message_thread_id"])
        payload = ({"ok": False, "error_code": 429, "parameters": {"retry_after": 30}}
                   if len(uploads) == 1 else {"ok": True, "result": {"message_id": 1}})
        return SimpleNamespace(ok=payload["ok"], json=lambda: payload, text="limited")

    monkeypatch.setattr(telegram_bot.requests, "post", post)
    monkeypatch.setattr(telegram_bot.time, "sleep", sleeps.append)
    video = tmp_path / "test.mp4"
    video.write_bytes(b"complete-video")
    telegram_bot.TelegramClient("test-token", group_topic_ids={-123: 7}).send_video(-123, video, "chart")
    assert uploads == [b"complete-video", b"complete-video"]
    assert topics == [7, 7]
    assert sleeps == [30]


def test_failed_failure_notice_does_not_stop_the_render_queue(monkeypatch):
    def fail(*args, **kwargs):
        raise telegram_bot.TelegramApiError("limited")

    monkeypatch.setattr(telegram_bot, "handle_ticker_message", fail)
    settings = telegram_bot.TelegramBotSettings(
        "test-token", RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 2)),
        group_topic_ids={},
    )
    queue = telegram_bot.TelegramJobQueue(SimpleNamespace(send_message=fail), settings)
    job = telegram_bot.TelegramJob("test-job", -123, "SBER", telegram_bot.time.monotonic())
    assert queue._process_job(job) is False
