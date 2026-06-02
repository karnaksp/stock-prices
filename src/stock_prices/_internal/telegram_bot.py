from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Any

import requests

from stock_prices._internal.env import get_cleanup_retention_days
from stock_prices._internal.models import RenderSettings
from stock_prices._internal.pipeline import generate_video, log_event
from stock_prices._internal.telegram_requests import parse_telegram_video_request


class TelegramApiError(RuntimeError):
    pass


def _redact_token(text: str, token: str) -> str:
    return text.replace(token, "<telegram-token>")


class TelegramClient:
    def __init__(self, token: str, timeout: int = 30) -> None:
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout = timeout

    def call(self, method: str, **data: Any) -> Any:
        try:
            response = requests.post(f"{self.base_url}/{method}", data=data, timeout=self.timeout + 10)
        except requests.RequestException as exc:
            raise TelegramApiError(f"Telegram {method} request failed: {_redact_token(str(exc), self.token)}") from None
        payload = response.json()
        if not response.ok or not payload.get("ok"):
            description = payload.get("description", response.text)
            raise TelegramApiError(f"Telegram {method} failed: {description}")
        return payload["result"]

    def get_updates(self, offset: int | None, timeout: int, limit: int = 10) -> list[dict[str, Any]]:
        data: dict[str, Any] = {"timeout": timeout, "limit": limit, "allowed_updates": '["message"]'}
        if offset is not None:
            data["offset"] = offset
        return self.call("getUpdates", **data)

    def send_message(self, chat_id: int, text: str) -> None:
        self.call("sendMessage", chat_id=chat_id, text=text)

    def send_video(self, chat_id: int, video_path: Path, caption: str) -> None:
        with video_path.open("rb") as video:
            try:
                response = requests.post(
                    f"{self.base_url}/sendVideo",
                    data={"chat_id": chat_id, "caption": caption, "supports_streaming": True},
                    files={"video": (video_path.name, video, "video/mp4")},
                    timeout=max(self.timeout + 60, 120),
                )
            except requests.RequestException as exc:
                raise TelegramApiError(f"Telegram sendVideo request failed: {_redact_token(str(exc), self.token)}") from None
        payload = response.json()
        if not response.ok or not payload.get("ok"):
            description = payload.get("description", response.text)
            raise TelegramApiError(f"Telegram sendVideo failed: {description}")


class TelegramBotSettings:
    def __init__(
        self,
        token: str,
        render: RenderSettings,
        allowed_chat_ids: set[int] | None = None,
        default_engine: str = "stock",
        default_market: str = "shares",
        poll_timeout: int = 30,
        once: bool = False,
        cleanup_retention_days: int | None = None,
    ) -> None:
        self.token = token
        self.render = render
        self.allowed_chat_ids = allowed_chat_ids or set()
        self.default_engine = default_engine
        self.default_market = default_market
        self.poll_timeout = poll_timeout
        self.once = once
        self.cleanup_retention_days = (
            get_cleanup_retention_days() if cleanup_retention_days is None else cleanup_retention_days
        )
        if self.cleanup_retention_days < 0:
            msg = "cleanup_retention_days must be a non-negative integer."
            raise ValueError(msg)


@dataclass(frozen=True)
class TelegramJob:
    job_id: str
    chat_id: int
    text: str
    queued_at: float


class TelegramJobQueue:
    def __init__(self, client: TelegramClient, settings: TelegramBotSettings) -> None:
        self.client = client
        self.settings = settings
        self._jobs: Queue[TelegramJob | None] = Queue()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._run_worker, name="telegram-job-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._jobs.put(None)
        self._thread.join()
        self._thread = None

    def join(self) -> None:
        self._jobs.join()

    def enqueue(self, chat_id: int, text: str, update_id: int) -> TelegramJob:
        job = TelegramJob(job_id=f"tg-{update_id}", chat_id=chat_id, text=text, queued_at=time.monotonic())
        queue_position = self._jobs.qsize() + 1
        log_event(
            "request",
            "queued",
            job_id=job.job_id,
            chat_id=chat_id,
            queue_position=queue_position,
            text_length=len(text),
        )
        self.client.send_message(chat_id, f"Job {job.job_id} queued. Queue position: {queue_position}.")
        self._jobs.put(job)
        return job

    def _run_worker(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                if job is None:
                    return
                self._process_job(job)
            finally:
                self._jobs.task_done()

    def _process_job(self, job: TelegramJob) -> None:
        wait_ms = int((time.monotonic() - job.queued_at) * 1000)
        log_event("request", "dequeued", job_id=job.job_id, chat_id=job.chat_id, wait_ms=wait_ms)
        try:
            handle_ticker_message(self.client, self.settings, job.chat_id, job.text, job_id=job.job_id)
        except Exception as exc:
            log_event("request", "failed", job_id=job.job_id, chat_id=job.chat_id, error=str(exc))
            logging.exception("Failed to process Telegram request %s", job.job_id)
            self.client.send_message(job.chat_id, f"Job {job.job_id} failed: {exc}")


def _extract_text_message(update: dict[str, Any]) -> tuple[int, str] | None:
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not text or chat_id is None:
        return None
    return int(chat_id), text


def _help_text(default_engine: str, default_market: str) -> str:
    return (
        "Напиши тикер, и я верну MP4-график.\n"
        f"По умолчанию: {default_engine}|{default_market}\n"
        "Примеры:\n"
        "LKOH\n"
        "LKOH SBER 2020 2024\n"
        "AAPL global USD gradient\n"
        "SBER duration=12 fps=24 close"
    )


def cleanup_old_outputs(output_dir: Path, retention_days: int, keep: set[Path] | None = None) -> list[Path]:
    if retention_days <= 0:
        return []
    keep_resolved = {path.resolve() for path in keep or set()}
    cutoff = time.time() - retention_days * 24 * 60 * 60
    removed: list[Path] = []
    if not output_dir.exists():
        return removed
    for video_path in output_dir.rglob("*.mp4"):
        try:
            if video_path.resolve() in keep_resolved:
                continue
            if video_path.stat().st_mtime < cutoff:
                video_path.unlink()
                removed.append(video_path)
        except OSError as exc:
            logging.warning("Failed to cleanup old output %s: %s", video_path, exc)
    return removed


def _is_help(text: str) -> bool:
    return text.startswith("/start") or text.startswith("/help")


def handle_ticker_message(
    client: TelegramClient,
    settings: TelegramBotSettings,
    chat_id: int,
    text: str,
    job_id: str | None = None,
) -> None:
    if settings.allowed_chat_ids and chat_id not in settings.allowed_chat_ids:
        client.send_message(chat_id, "This chat is not allowed to use this bot.")
        return
    if _is_help(text):
        client.send_message(chat_id, _help_text(settings.default_engine, settings.default_market))
        return

    parsed = parse_telegram_video_request(text, settings.render, settings.default_engine, settings.default_market)
    render = parsed.request.render
    client.send_message(
        chat_id,
        f"Генерирую видео: {parsed.display_name}\n"
        f"{render.start_date} - {render.end_date}, {render.duration}s/{render.fps}fps",
    )
    output_path = generate_video(parsed.request, job_id=job_id)
    send_started_at = time.monotonic()
    log_event("send", "started", job_id=job_id, chat_id=chat_id, output_path=str(output_path))
    client.send_video(chat_id, output_path, f"{parsed.display_name}: {render.start_date} - {render.end_date}")
    log_event("send", "completed", job_id=job_id, chat_id=chat_id, elapsed_ms=int((time.monotonic() - send_started_at) * 1000))
    removed = cleanup_old_outputs(render.output_dir, settings.cleanup_retention_days, keep={output_path})
    if removed:
        log_event("cleanup", "completed", job_id=job_id, removed_count=len(removed), retention_days=settings.cleanup_retention_days)


def run_telegram_bot(settings: TelegramBotSettings) -> None:
    client = TelegramClient(settings.token, settings.poll_timeout)
    job_queue = TelegramJobQueue(client, settings)
    job_queue.start()
    offset: int | None = None
    logging.info("Telegram bot started.")

    try:
        while True:
            try:
                updates = client.get_updates(offset=offset, timeout=settings.poll_timeout)
                for update in updates:
                    offset = int(update["update_id"]) + 1
                    extracted = _extract_text_message(update)
                    if extracted is None:
                        continue
                    chat_id, text = extracted
                    if settings.allowed_chat_ids and chat_id not in settings.allowed_chat_ids:
                        client.send_message(chat_id, "This chat is not allowed to use this bot.")
                    elif _is_help(text):
                        client.send_message(chat_id, _help_text(settings.default_engine, settings.default_market))
                    else:
                        job_queue.enqueue(chat_id, text, int(update["update_id"]))
                if settings.once:
                    job_queue.join()
                    return
            except KeyboardInterrupt:
                raise
            except Exception:
                logging.exception("Telegram polling failed")
                if settings.once:
                    raise
                time.sleep(5)
    finally:
        job_queue.stop()
