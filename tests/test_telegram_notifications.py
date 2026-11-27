from datetime import date
from threading import Event

from stock_prices._internal import telegram_bot
from stock_prices._internal.models import RenderSettings
from stock_prices._internal.telegram_notifications import TelegramNotificationQueue


def test_slow_notifications_do_not_block_rendering_or_delete_unsent_video(monkeypatch, tmp_path):
    sending = Event()
    release = Event()
    rendered = Event()
    first_sent = Event()
    videos = []
    requests = []

    class Client:
        def send_message(self, *args, **kwargs):
            if args[1].startswith("Задача поставлена в очередь"):
                sending.set()
                assert release.wait(5)

        def send_video(self, chat_id, path, caption, **kwargs):
            videos.append(path.read_bytes())
            first_sent.set()

    def generate(request, job_id=None):
        path = tmp_path / f"{job_id}.mp4"
        path.write_bytes(job_id.encode())
        requests.append(path)
        if len(requests) == 2:
            rendered.set()
        return path

    monkeypatch.setattr(telegram_bot, "generate_video", generate)
    monkeypatch.setattr(telegram_bot, "_start_render_progress_notifier", lambda *a, **kw: lambda: None)
    settings = telegram_bot.TelegramBotSettings(
        "test", RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10)),
        cleanup_retention_days=0, group_topic_ids={},
    )
    queue = telegram_bot.TelegramJobQueue(Client(), settings)
    queue.start()
    try:
        queue.enqueue(123, "SBER", 1, notify=False)
        assert first_sent.wait(5)
        queue.enqueue(123, "SBER", 2)
        assert sending.wait(5)
        assert rendered.wait(5)
        assert not release.is_set()
    finally:
        release.set()
        queue.stop()
    assert videos == [b"tg-1", b"tg-2"]
    assert all(not path.exists() for path in requests)
    assert queue.snapshot().completed_count == 2


def test_waiting_for_an_acknowledgement_does_not_delay_starting_render(monkeypatch, tmp_path):
    sending, release, rendering = Event(), Event(), Event()

    class Client:
        def send_message(self, *args, **kwargs):
            sending.set()
            assert release.wait(5)

        def send_video(self, chat_id, path, caption, **kwargs):
            assert path.exists()

    def generate(request, job_id=None):
        rendering.set()
        path = tmp_path / 'video.mp4'
        path.write_bytes(b'video')
        return path

    monkeypatch.setattr(telegram_bot, "generate_video", generate)
    monkeypatch.setattr(telegram_bot, "_start_render_progress_notifier", lambda *a, **kw: lambda: None)
    settings = telegram_bot.TelegramBotSettings(
        "test", RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10)),
        cleanup_retention_days=0, group_topic_ids={},
    )
    queue = telegram_bot.TelegramJobQueue(Client(), settings)
    queue.start()
    try:
        queue.enqueue(123, "SBER", 1)
        assert sending.wait(5)
        assert rendering.wait(5)
        assert not release.is_set()
    finally:
        release.set()
        queue.stop()


def test_stale_progress_notice_is_dropped():
    entered, release, cancelled = Event(), Event(), Event()
    messages = []

    class Client:
        def send_message(self, chat_id, text):
            messages.append(text)
            if text == "blocking":
                entered.set()
                assert release.wait(5)

    queue = TelegramNotificationQueue(Client())
    queue.start()
    try:
        queue.send_message(123, "blocking")
        assert entered.wait(5)
        queue.send_message(123, "stale render notice", cancelled=cancelled)
        cancelled.set()
    finally:
        release.set()
        queue.stop()
    assert messages == ["blocking"]


def test_failed_notification_does_not_stop_following_messages():
    messages = []

    class Client:
        def send_message(self, chat_id, text):
            if text == "fail":
                raise RuntimeError("unavailable")
            messages.append(text)

    queue = TelegramNotificationQueue(Client())
    queue.start()
    try:
        queue.send_message(123, "fail")
        queue.send_message(123, "next")
        queue.join()
    finally:
        queue.stop()
    assert messages == ["next"]


def test_failed_video_delivery_reaches_the_worker_and_preserves_output(monkeypatch, tmp_path):
    path = tmp_path / "unsent.mp4"
    path.write_bytes(b"keep this output")

    class Client:
        def send_message(self, *args, **kwargs):
            pass

        def send_video(self, *args, **kwargs):
            raise RuntimeError("upload failed")

    monkeypatch.setattr(telegram_bot, "generate_video", lambda *a, **kw: path)
    monkeypatch.setattr(telegram_bot, "_start_render_progress_notifier", lambda *a, **kw: lambda: None)
    settings = telegram_bot.TelegramBotSettings(
        "test", RenderSettings(start_date=date(2020, 1, 1), end_date=date(2020, 1, 10)),
        cleanup_retention_days=0, group_topic_ids={},
    )
    queue = telegram_bot.TelegramJobQueue(Client(), settings)
    queue.start()
    try:
        queue.enqueue(123, "SBER", 1)
        queue.join()
    finally:
        queue.stop()
    assert path.read_bytes() == b"keep this output"
    assert queue.snapshot().failed_count == 1
