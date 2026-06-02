from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from threading import Lock, Thread
from typing import Any

import requests

from stock_prices._internal.env import get_cleanup_retention_days
from stock_prices._internal.models import RenderSettings
from stock_prices._internal.pipeline import generate_video, log_event
from stock_prices._internal.telegram_presets import (
    PRESETS,
    format_preset_list,
    format_pulse_post,
    get_preset,
    preset_button_label,
    preset_followup_keyboard,
    preset_inline_keyboard,
)
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
        data: dict[str, Any] = {
            "timeout": timeout,
            "limit": limit,
            "allowed_updates": json.dumps(["message", "callback_query"]),
        }
        if offset is not None:
            data["offset"] = offset
        return self.call("getUpdates", **data)

    def send_message(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        data: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        self.call("sendMessage", **data)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        data: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            data["text"] = text
        self.call("answerCallbackQuery", **data)

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


@dataclass(frozen=True)
class TelegramQueueSnapshot:
    active_job_id: str | None
    pending_job_ids: tuple[str, ...]
    completed_count: int
    failed_count: int


@dataclass(frozen=True)
class TelegramPresetCallback:
    callback_query_id: str
    chat_id: int
    text: str


class TelegramJobQueue:
    def __init__(self, client: TelegramClient, settings: TelegramBotSettings) -> None:
        self.client = client
        self.settings = settings
        self._jobs: Queue[TelegramJob | None] = Queue()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._pending_jobs: list[TelegramJob] = []
        self._active_job: TelegramJob | None = None
        self._completed_count = 0
        self._failed_count = 0

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

    def enqueue(self, chat_id: int, text: str, update_id: int, job_suffix: str = "", notify: bool = True) -> TelegramJob:
        suffix = f"-{job_suffix}" if job_suffix else ""
        job = TelegramJob(job_id=f"tg-{update_id}{suffix}", chat_id=chat_id, text=text, queued_at=time.monotonic())
        with self._lock:
            queue_position = len(self._pending_jobs) + 1
        log_event(
            "request",
            "queued",
            job_id=job.job_id,
            chat_id=chat_id,
            queue_position=queue_position,
            text_length=len(text),
        )
        if notify:
            self.client.send_message(chat_id, f"Job {job.job_id} queued. Queue position: {queue_position}.")
        with self._lock:
            self._pending_jobs.append(job)
        self._jobs.put(job)
        return job

    def enqueue_preset_drafts(self, chat_id: int, update_id: int) -> list[TelegramJob]:
        labels = ", ".join(preset_button_label(preset) for preset in PRESETS)
        self.client.send_message(
            chat_id,
            f"Ставлю в очередь {len(PRESETS)} черновиков: {labels}.",
        )
        jobs: list[TelegramJob] = []
        for index, preset in enumerate(PRESETS, start=1):
            jobs.append(
                self.enqueue(
                    chat_id,
                    f"preset {preset.name} draft",
                    update_id,
                    job_suffix=f"draft-{index}-{preset.name}",
                    notify=False,
                )
            )
        return jobs

    def enqueue_random_preset_draft(self, chat_id: int, update_id: int) -> TelegramJob:
        preset = random.choice(PRESETS)
        self.client.send_message(
            chat_id,
            f"Случайный черновик: {preset_button_label(preset)}. Ставлю короткий draft в очередь.",
        )
        return self.enqueue(
            chat_id,
            f"preset {preset.name} draft",
            update_id,
            job_suffix=f"random-draft-{preset.name}",
            notify=False,
        )

    def snapshot(self) -> TelegramQueueSnapshot:
        with self._lock:
            return TelegramQueueSnapshot(
                active_job_id=self._active_job.job_id if self._active_job else None,
                pending_job_ids=tuple(job.job_id for job in self._pending_jobs),
                completed_count=self._completed_count,
                failed_count=self._failed_count,
            )

    def status_text(self) -> str:
        snapshot = self.snapshot()
        lines = ["Очередь Telegram"]
        if snapshot.active_job_id:
            lines.append(f"Сейчас: {snapshot.active_job_id}")
        else:
            lines.append("Сейчас: нет активного рендера")

        pending_count = len(snapshot.pending_job_ids)
        lines.append(f"Ждет: {pending_count}")
        for index, job_id in enumerate(snapshot.pending_job_ids[:8], start=1):
            lines.append(f"{index}. {job_id}")
        if pending_count > 8:
            lines.append(f"... еще {pending_count - 8}")
        lines.append(f"Готово: {snapshot.completed_count}, ошибок: {snapshot.failed_count}")
        return "\n".join(lines)

    def _mark_started(self, job: TelegramJob) -> None:
        with self._lock:
            self._pending_jobs = [pending_job for pending_job in self._pending_jobs if pending_job.job_id != job.job_id]
            self._active_job = job

    def _mark_finished(self, job: TelegramJob, success: bool) -> None:
        with self._lock:
            if self._active_job and self._active_job.job_id == job.job_id:
                self._active_job = None
            if success:
                self._completed_count += 1
            else:
                self._failed_count += 1

    def _run_worker(self) -> None:
        while True:
            job = self._jobs.get()
            success = False
            try:
                if job is None:
                    return
                self._mark_started(job)
                success = self._process_job(job)
            finally:
                if job is not None:
                    self._mark_finished(job, success)
                self._jobs.task_done()

    def _process_job(self, job: TelegramJob) -> bool:
        wait_ms = int((time.monotonic() - job.queued_at) * 1000)
        log_event("request", "dequeued", job_id=job.job_id, chat_id=job.chat_id, wait_ms=wait_ms)
        try:
            handle_ticker_message(self.client, self.settings, job.chat_id, job.text, job_id=job.job_id)
        except Exception as exc:
            log_event("request", "failed", job_id=job.job_id, chat_id=job.chat_id, error=str(exc))
            logging.exception("Failed to process Telegram request %s", job.job_id)
            self.client.send_message(job.chat_id, f"Job {job.job_id} failed: {exc}")
            return False
        return True


def _extract_text_message(update: dict[str, Any]) -> tuple[int, str] | None:
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not text or chat_id is None:
        return None
    return int(chat_id), text


def _extract_preset_callback(update: dict[str, Any]) -> TelegramPresetCallback | None:
    callback_query = update.get("callback_query") or {}
    callback_query_id = callback_query.get("id")
    data = (callback_query.get("data") or "").strip()
    if not callback_query_id or not data.startswith("preset:"):
        return None
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    parts = [part.strip() for part in data.split(":")]
    if len(parts) not in {2, 3}:
        return None
    preset_name = parts[1]
    if not preset_name:
        return None
    mode = parts[2].lower() if len(parts) == 3 else ""
    if mode not in {"", "draft", "shorts", "12s"}:
        return None
    text = f"preset {preset_name}"
    if mode == "draft":
        text = f"{text} draft"
    elif mode == "shorts":
        text = f"{text} shorts"
    elif mode == "12s":
        text = f"{text} duration=12"
    return TelegramPresetCallback(str(callback_query_id), int(chat_id), text)


def _help_text(default_engine: str, default_market: str) -> str:
    return (
        "Напиши тикер или несколько тикеров, и я поставлю задачу в очередь и верну MP4-график.\n"
        f"По умолчанию: {default_engine}|{default_market}\n"
        "Готовые сценарии: /ideas, /идеи, /drafts, /черновики, все черновики, случайный черновик, /queue, металлы, черновик металлы\n"
        "После preset-видео будут кнопки: черновик 4s, шортс 16s, вариант 12s.\n"
        "Примеры:\n"
        "LKOH\n"
        "LKOH SBER 2020 2024\n"
        "металлы\n"
        "черновик металлы\n"
        "preset neweconomy duration=12\n"
        "пресет металлы draft\n"
        "/drafts\n"
        "/черновики\n"
        "все черновики\n"
        "случайный черновик\n"
        "/random_draft\n"
        "/queue\n"
        "очередь\n"
        "AAPL global USD gradient theme=studio\n"
        "gold silver palladium 2010-2026 RUB capital invest initial=0 monthly=30000 gradient\n"
        "SiH4 futures 2024 close\n"
        "USD000UTSTOM selt 2024 close\n"
        "Параметры: from=YYYY-MM-DD to=YYYY-MM-DD shorts draft close capital invest initial=0 monthly=30000 "
        "duration=12 fps=24 theme=default|aurora|studio"
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
    normalized = text.strip().lower()
    return (
        normalized.startswith("/start")
        or normalized.startswith("/help")
        or normalized.startswith("/старт")
        or normalized in {"/помощь", "помощь", "help"}
    )


def _preset_list_mode(text: str) -> str | None:
    normalized = text.strip().lower()
    if normalized in {
        "/ideas",
        "/presets",
        "/stories",
        "/идеи",
        "/сценарии",
        "/истории",
        "ideas",
        "presets",
        "stories",
        "идеи",
        "сценарии",
        "истории",
    }:
        return "shorts"
    if normalized in {
        "/drafts",
        "/previews",
        "/черновики",
        "/превью",
        "drafts",
        "previews",
        "черновики",
        "превью",
    }:
        return "draft"
    return None


def _is_draft_batch(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "/drafts_all",
        "/all_drafts",
        "/черновики_все",
        "drafts all",
        "all drafts",
        "draft batch",
        "batch drafts",
        "черновики все",
        "все черновики",
        "пакет черновиков",
    }


def _is_random_draft(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "/random",
        "/random_draft",
        "/случайный",
        "/случайный_черновик",
        "random",
        "random draft",
        "draft random",
        "случайный",
        "случайный черновик",
        "черновик случайный",
    }


def _is_queue_status(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "/queue",
        "/status",
        "/очередь",
        "/статус",
        "queue",
        "status",
        "очередь",
        "статус",
    }


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
    if _is_draft_batch(text):
        client.send_message(chat_id, "Команда пакетных черновиков работает в режиме Telegram-очереди.")
        return
    if _is_random_draft(text):
        client.send_message(chat_id, "Команда случайного черновика работает в режиме Telegram-очереди.")
        return
    if _is_queue_status(text):
        client.send_message(chat_id, "Статус очереди доступен в режиме Telegram-бота.")
        return
    preset_list_mode = _preset_list_mode(text)
    if preset_list_mode is not None:
        client.send_message(
            chat_id,
            format_preset_list(preset_list_mode),
            reply_markup=preset_inline_keyboard(mode=preset_list_mode),
        )
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
    if parsed.preset_name:
        preset = get_preset(parsed.preset_name)
        client.send_message(chat_id, format_pulse_post(preset))
        client.send_message(
            chat_id,
            "Быстрые варианты для этого сценария:",
            reply_markup=preset_followup_keyboard(preset.name),
        )
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
                    if extracted is not None:
                        chat_id, text = extracted
                        if settings.allowed_chat_ids and chat_id not in settings.allowed_chat_ids:
                            client.send_message(chat_id, "This chat is not allowed to use this bot.")
                        elif _is_help(text):
                            client.send_message(chat_id, _help_text(settings.default_engine, settings.default_market))
                        elif _is_draft_batch(text):
                            job_queue.enqueue_preset_drafts(chat_id, int(update["update_id"]))
                        elif _is_random_draft(text):
                            job_queue.enqueue_random_preset_draft(chat_id, int(update["update_id"]))
                        elif _is_queue_status(text):
                            client.send_message(chat_id, job_queue.status_text())
                        else:
                            preset_list_mode = _preset_list_mode(text)
                            if preset_list_mode is not None:
                                client.send_message(
                                    chat_id,
                                    format_preset_list(preset_list_mode),
                                    reply_markup=preset_inline_keyboard(mode=preset_list_mode),
                                )
                            else:
                                job_queue.enqueue(chat_id, text, int(update["update_id"]))
                        continue
                    callback = _extract_preset_callback(update)
                    if callback is None:
                        continue
                    if settings.allowed_chat_ids and callback.chat_id not in settings.allowed_chat_ids:
                        client.answer_callback_query(callback.callback_query_id, "This chat is not allowed.")
                        client.send_message(callback.chat_id, "This chat is not allowed to use this bot.")
                    else:
                        client.answer_callback_query(callback.callback_query_id, "Сценарий поставлен в очередь.")
                        job_queue.enqueue(callback.chat_id, callback.text, int(update["update_id"]))
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
