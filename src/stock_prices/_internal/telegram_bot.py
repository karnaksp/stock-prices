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
from stock_prices._internal.telegram_requests import ParsedTelegramRequest, parse_telegram_video_request


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
    active_preview: str
    pending_jobs: tuple[tuple[str, str], ...]
    completed_count: int
    failed_count: int


QUEUE_STATUS_CALLBACK_DATA = "queue:status"
CUSTOM_FOLLOWUP_MODES = {
    "draft": "draft",
    "shorts": "shorts",
    "12s": "duration=12 fps=24 gradient",
}


def queue_status_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {"inline_keyboard": [[{"text": "Статус очереди", "callback_data": QUEUE_STATUS_CALLBACK_DATA}]]}


def custom_followup_keyboard(request_key: str) -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "Черновик 4s", "callback_data": f"custom:{request_key}:draft"},
                {"text": "Шортс 16s", "callback_data": f"custom:{request_key}:shorts"},
            ],
            [
                {"text": "Вариант 12s", "callback_data": f"custom:{request_key}:12s"},
            ],
        ]
    }


def _ru_plural(count: int, one: str, few: str, many: str) -> str:
    if count % 100 in {11, 12, 13, 14}:
        return many
    if count % 10 == 1:
        return one
    if count % 10 in {2, 3, 4}:
        return few
    return many


def _job_preview(text: str, limit: int = 56) -> str:
    preview = " ".join(text.split())
    if len(preview) <= limit:
        return preview
    return f"{preview[: limit - 1]}..."


@dataclass(frozen=True)
class TelegramExample:
    name: str
    button_label: str
    request: str
    description: str


_TELEGRAM_EXAMPLES = (
    TelegramExample(
        name="metals-dca",
        button_label="Металлы DCA",
        request="gold silver palladium 2010-2026 RUB capital invest initial=0 monthly=30000 shorts theme=aurora",
        description="золото / серебро / палладий, ежемесячные 30 000 RUB",
    ),
    TelegramExample(
        name="new-economy",
        button_label="Новая экономика",
        request="SMLT SGZH POSI from=2021-12-17 to=2026-06-01 RUB capital invest initial=0 monthly=30000 shorts theme=studio",
        description="SMLT / SGZH / POSI после хайпа 2021",
    ),
    TelegramExample(
        name="global-tech",
        button_label="US Tech",
        request="AAPL MSFT NVDA global USD capital shorts theme=studio",
        description="AAPL / MSFT / NVDA в USD",
    ),
    TelegramExample(
        name="crypto",
        button_label="Крипта",
        request="btc eth 2020-2026 USD close shorts theme=studio",
        description="BTC / ETH на одной шкале",
    ),
    TelegramExample(
        name="moex-futures",
        button_label="Фьючерс Si",
        request="SiH4 futures 2024 close shorts",
        description="пример MOEX futures / FORTS",
    ),
    TelegramExample(
        name="currency",
        button_label="Валюта",
        request="USD000UTSTOM selt 2024 close shorts",
        description="пример MOEX currency / SELT",
    ),
)


def _get_telegram_example(name: str) -> TelegramExample | None:
    for example in _TELEGRAM_EXAMPLES:
        if example.name == name:
            return example
    return None


def format_example_list() -> str:
    lines = [
        "Проверенные примеры запросов:",
        "",
    ]
    for example in _TELEGRAM_EXAMPLES:
        lines.append(f"{example.button_label}: {example.description}")
        lines.append(example.request)
        lines.append("")
    lines.append("Нажмите кнопку ниже, чтобы сразу поставить пример в очередь.")
    lines.append("Это фиксированные рецепты без LLM и автопридумывания идей.")
    return "\n".join(lines).strip()


def example_inline_keyboard(columns: int = 2) -> dict[str, list[list[dict[str, str]]]]:
    buttons = [
        {"text": example.button_label, "callback_data": f"example:{example.name}"}
        for example in _TELEGRAM_EXAMPLES
    ]
    rows = [buttons[index : index + columns] for index in range(0, len(buttons), columns)]
    return {"inline_keyboard": rows}


@dataclass(frozen=True)
class TelegramPresetCallback:
    callback_query_id: str
    chat_id: int
    text: str


@dataclass(frozen=True)
class TelegramExampleCallback:
    callback_query_id: str
    chat_id: int
    text: str
    name: str


@dataclass(frozen=True)
class TelegramCustomFollowupCallback:
    callback_query_id: str
    chat_id: int
    request_key: str
    mode: str


@dataclass(frozen=True)
class TelegramQueueStatusCallback:
    callback_query_id: str
    chat_id: int


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
        self._followup_texts: dict[str, str] = {}

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
            self.client.send_message(
                chat_id,
                f"Задача {job.job_id} поставлена в очередь.\nПозиция: {queue_position}.",
                reply_markup=queue_status_keyboard(),
            )
        with self._lock:
            self._followup_texts[job.job_id] = text
            if len(self._followup_texts) > 100:
                oldest_key = next(iter(self._followup_texts))
                self._followup_texts.pop(oldest_key, None)
            self._pending_jobs.append(job)
        self._jobs.put(job)
        return job

    def build_custom_followup_text(self, request_key: str, mode: str) -> str | None:
        mode_suffix = CUSTOM_FOLLOWUP_MODES.get(mode)
        if mode_suffix is None:
            return None
        with self._lock:
            text = self._followup_texts.get(request_key)
        if text is None:
            return None
        return f"{text} {mode_suffix}"

    def enqueue_preset_drafts(self, chat_id: int, update_id: int) -> list[TelegramJob]:
        labels = ", ".join(preset_button_label(preset) for preset in PRESETS)
        self.client.send_message(
            chat_id,
            f"Ставлю в очередь {len(PRESETS)} черновиков: {labels}.",
            reply_markup=queue_status_keyboard(),
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
            reply_markup=queue_status_keyboard(),
        )
        return self.enqueue(
            chat_id,
            f"preset {preset.name} draft",
            update_id,
            job_suffix=f"random-draft-{preset.name}",
            notify=False,
        )

    def enqueue_example_drafts(self, chat_id: int, update_id: int) -> list[TelegramJob]:
        labels = ", ".join(example.button_label for example in _TELEGRAM_EXAMPLES)
        self.client.send_message(
            chat_id,
            f"Ставлю в очередь {len(_TELEGRAM_EXAMPLES)} draft-примеров: {labels}.",
            reply_markup=queue_status_keyboard(),
        )
        jobs: list[TelegramJob] = []
        for index, example in enumerate(_TELEGRAM_EXAMPLES, start=1):
            jobs.append(
                self.enqueue(
                    chat_id,
                    f"{example.request} draft",
                    update_id,
                    job_suffix=f"example-draft-{index}-{example.name}",
                    notify=False,
                )
            )
        return jobs

    def enqueue_random_example_draft(self, chat_id: int, update_id: int) -> TelegramJob:
        example = random.choice(_TELEGRAM_EXAMPLES)
        self.client.send_message(
            chat_id,
            f"Случайный пример: {example.button_label}. Ставлю короткий draft в очередь.",
            reply_markup=queue_status_keyboard(),
        )
        return self.enqueue(
            chat_id,
            f"{example.request} draft",
            update_id,
            job_suffix=f"random-example-{example.name}",
            notify=False,
        )

    def enqueue_batch(self, chat_id: int, texts: list[str], update_id: int) -> list[TelegramJob]:
        jobs: list[TelegramJob] = []
        for index, text in enumerate(texts, start=1):
            jobs.append(self.enqueue(chat_id, text, update_id, job_suffix=f"batch-{index}", notify=False))
        task_word = _ru_plural(len(jobs), "задачу", "задачи", "задач")
        self.client.send_message(
            chat_id,
            f"Поставил в очередь {len(jobs)} {task_word} из одного сообщения.",
            reply_markup=queue_status_keyboard(),
        )
        return jobs

    def snapshot(self) -> TelegramQueueSnapshot:
        with self._lock:
            return TelegramQueueSnapshot(
                active_job_id=self._active_job.job_id if self._active_job else None,
                active_preview=_job_preview(self._active_job.text) if self._active_job else "",
                pending_jobs=tuple((job.job_id, _job_preview(job.text)) for job in self._pending_jobs),
                completed_count=self._completed_count,
                failed_count=self._failed_count,
            )

    def status_text(self) -> str:
        snapshot = self.snapshot()
        lines = ["Очередь Telegram"]
        if snapshot.active_job_id:
            lines.append(f"Сейчас: {snapshot.active_job_id} - {snapshot.active_preview}")
        else:
            lines.append("Сейчас: нет активного рендера")

        pending_count = len(snapshot.pending_jobs)
        lines.append(f"Ждет: {pending_count}")
        for index, (job_id, preview) in enumerate(snapshot.pending_jobs[:8], start=1):
            lines.append(f"{index}. {job_id} - {preview}")
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
            handle_ticker_message(
                self.client,
                self.settings,
                job.chat_id,
                job.text,
                job_id=job.job_id,
                custom_followup_key=job.job_id,
            )
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


def _extract_example_callback(update: dict[str, Any]) -> TelegramExampleCallback | None:
    callback_query = update.get("callback_query") or {}
    callback_query_id = callback_query.get("id")
    data = (callback_query.get("data") or "").strip()
    if not callback_query_id or not data.startswith("example:"):
        return None
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    parts = [part.strip() for part in data.split(":")]
    if len(parts) != 2:
        return None
    example = _get_telegram_example(parts[1])
    if example is None:
        return None
    return TelegramExampleCallback(str(callback_query_id), int(chat_id), example.request, example.name)


def _extract_custom_followup_callback(update: dict[str, Any]) -> TelegramCustomFollowupCallback | None:
    callback_query = update.get("callback_query") or {}
    callback_query_id = callback_query.get("id")
    data = (callback_query.get("data") or "").strip()
    if not callback_query_id or not data.startswith("custom:"):
        return None
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    parts = [part.strip() for part in data.split(":")]
    if len(parts) != 3:
        return None
    request_key = parts[1]
    mode = parts[2].lower()
    if not request_key or mode not in CUSTOM_FOLLOWUP_MODES:
        return None
    return TelegramCustomFollowupCallback(str(callback_query_id), int(chat_id), request_key, mode)


def _extract_queue_status_callback(update: dict[str, Any]) -> TelegramQueueStatusCallback | None:
    callback_query = update.get("callback_query") or {}
    callback_query_id = callback_query.get("id")
    data = (callback_query.get("data") or "").strip()
    if not callback_query_id or data != QUEUE_STATUS_CALLBACK_DATA:
        return None
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    return TelegramQueueStatusCallback(str(callback_query_id), int(chat_id))


def _help_text(default_engine: str, default_market: str) -> str:
    return (
        "Напиши тикер или несколько тикеров, и я поставлю задачу в очередь и верну MP4-график.\n"
        f"По умолчанию: {default_engine}|{default_market}\n"
        "Готовые сценарии: /ideas, /идеи, /drafts, /черновики, /examples, /примеры, все черновики, черновики примеров, случайный черновик, случайный пример, /queue, металлы, черновик металлы\n"
        "Можно отправить несколько запросов строками в одном сообщении.\n"
        "После постановки задачи будет кнопка: Статус очереди.\n"
        "После preset-видео будут кнопки: черновик 4s, шортс 16s, вариант 12s.\n"
        "После custom-видео будут такие же быстрые варианты для этого запроса.\n"
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
        "/examples\n"
        "/примеры\n"
        "черновики примеров\n"
        "случайный пример\n"
        "/queue\n"
        "очередь\n"
        "AAPL global USD gradient theme=studio\n"
        "gold silver palladium 2010-2026 RUB capital invest initial=0 monthly=30000 gradient\n"
        "золото серебро палладий с 2010 по 2026 в рублях капитал инвестируя каждый месяц 30000 градиент шортс\n"
        "SiH4 futures 2024 close\n"
        "USD000UTSTOM selt 2024 close\n"
        "Параметры: from=YYYY-MM-DD to=YYYY-MM-DD shorts draft close capital invest initial=0 monthly=30000 "
        "или по-русски: с 2020 по 2024, каждый месяц 30000 рублей, по 30 000 рублей в месяц. "
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


def _is_examples(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "/examples",
        "/example",
        "/примеры",
        "/пример",
        "examples",
        "example",
        "примеры",
        "пример",
        "примеры запросов",
    }


def _is_example_draft_batch(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "/example_drafts",
        "/examples_drafts",
        "/draft_examples",
        "/all_examples",
        "/примеры_черновики",
        "example drafts",
        "examples drafts",
        "draft examples",
        "all examples",
        "черновики примеров",
        "примеры черновики",
        "все примеры",
        "пакет примеров",
    }


def _is_random_example_draft(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "/random_example",
        "/random_example_draft",
        "/случайный_пример",
        "random example",
        "random example draft",
        "example random",
        "случайный пример",
        "случайный черновик примера",
        "пример случайный",
    }


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


def _batch_request_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _format_amount(value: int, currency: str) -> str:
    return f"{value:,}".replace(",", " ") + f" {currency}"


def _metric_label(value_col: str) -> str:
    if value_col.upper() == "CLOSE":
        return "цена закрытия"
    return "капитал с реинвестированием"


def _market_tags(parsed: ParsedTelegramRequest) -> str:
    tags = ["#пульс", "#инвестиции", "#график"]
    markets = {spec.market for spec in parsed.request.ticker_specs}
    engines = {spec.engine for spec in parsed.request.ticker_specs}
    if "crypto" in markets:
        tags.append("#крипто")
    if "metals" in markets or "commodities" in markets:
        tags.append("#сырье")
    if "futures" in markets or "forts" in markets or "futures" in engines:
        tags.append("#фьючерсы")
    if "currency" in markets or "selt" in markets or "currency" in engines:
        tags.append("#валюта")
    if "shares" in markets or "stock" in engines:
        tags.append("#акции")
    return " ".join(dict.fromkeys(tags))


def _custom_story_label(parsed: ParsedTelegramRequest) -> str:
    render = parsed.request.render
    markets = {spec.market for spec in parsed.request.ticker_specs}
    engines = {spec.engine for spec in parsed.request.ticker_specs}
    ticker_count = len(parsed.request.ticker_specs)

    if render.with_investments and ticker_count > 1:
        return "ежемесячные покупки против разных активов"
    if "crypto" in markets:
        return "крипта на одной шкале"
    if "metals" in markets or "commodities" in markets:
        return "сырьевой сюжет на длинной дистанции"
    if "futures" in markets or "forts" in markets or "futures" in engines:
        return "фьючерсная динамика без лишних слов"
    if "currency" in markets or "selt" in markets or "currency" in engines:
        return "валютная траектория"
    if ticker_count == 1:
        return "один актив на истории"
    return "сравнение активов на одной шкале"


def _custom_pulse_hook(parsed: ParsedTelegramRequest) -> str:
    render = parsed.request.render
    if render.with_investments and render.monthly_investment:
        return (
            f"Если каждый месяц откладывать {_format_amount(render.monthly_investment, render.currency)}, "
            f"какой из вариантов выглядит убедительнее на истории: {parsed.display_name}?"
        )
    if len(parsed.request.ticker_specs) == 1:
        return f"Один график, который быстро показывает характер {parsed.display_name} на выбранном периоде."
    return f"На одном графике {parsed.display_name}: где была спокойная траектория, а где началась настоящая драма?"


def _custom_pulse_question(parsed: ParsedTelegramRequest) -> str:
    render = parsed.request.render
    if render.with_investments:
        return "Вопрос для обсуждения: вы бы выдержали такую регулярную стратегию до финального результата?"
    if len(parsed.request.ticker_specs) > 1:
        return "Вопрос для обсуждения: какой актив на графике выглядит самым неожиданным?"
    return "Вопрос для обсуждения: это больше похоже на возможность или на ловушку ожиданий?"


def _custom_music_mood(parsed: ParsedTelegramRequest) -> str:
    markets = {spec.market for spec in parsed.request.ticker_specs}
    if "crypto" in markets:
        return "быстрый электронный бит, резкие акценты на разворотах"
    if "metals" in markets or "commodities" in markets:
        return "плотный драматичный бит, пауза на финальном сравнении"
    if len(parsed.request.ticker_specs) == 1:
        return "минималистичный бит, акцент на финальной подписи"
    return "энергичный темп, короткая пауза на победителе и отстающих"


def format_generic_pulse_post(parsed: ParsedTelegramRequest) -> str:
    render = parsed.request.render
    period = f"{render.start_date:%d.%m.%Y} - {render.end_date:%d.%m.%Y}"
    story_label = _custom_story_label(parsed)
    lines = [
        "Текст для Пульса:",
        f"Заголовок: {parsed.display_name} - {story_label}",
        f"Хук: {_custom_pulse_hook(parsed)}",
        "",
        f"Период: {period}. Валюта: {render.currency}. Метрика: {_metric_label(render.value_col)}.",
    ]
    if render.with_investments:
        parts = [f"старт {_format_amount(render.initial_investment, render.currency)}"]
        if render.monthly_investment:
            parts.append(f"ежемесячно {_format_amount(render.monthly_investment, render.currency)}")
        if render.yearly_investment:
            parts.append(f"ежегодно {_format_amount(render.yearly_investment, render.currency)}")
        lines.append(f"Сценарий инвестирования: {', '.join(parts)}.")
    lines.extend(
        [
            "На видео историческая траектория, а не прогноз. Хороший формат для обсуждения: где график удивляет, где ожидания ломаются, а где регулярные покупки действительно меняют картину.",
            "",
            _custom_pulse_question(parsed),
            f"Музыка/монтаж: {_custom_music_mood(parsed)}.",
            f"{_market_tags(parsed)}",
            "Не инвестиционная рекомендация.",
        ]
    )
    return "\n".join(lines)


def handle_ticker_message(
    client: TelegramClient,
    settings: TelegramBotSettings,
    chat_id: int,
    text: str,
    job_id: str | None = None,
    custom_followup_key: str | None = None,
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
    if _is_example_draft_batch(text):
        client.send_message(chat_id, "Команда пакетных draft-примеров работает в режиме Telegram-очереди.")
        return
    if _is_random_example_draft(text):
        client.send_message(chat_id, "Команда случайного draft-примера работает в режиме Telegram-очереди.")
        return
    if _is_queue_status(text):
        client.send_message(chat_id, "Статус очереди доступен в режиме Telegram-бота.")
        return
    if _is_examples(text):
        client.send_message(chat_id, format_example_list(), reply_markup=example_inline_keyboard())
        return
    if len(_batch_request_lines(text)) > 1:
        client.send_message(chat_id, "Несколько запросов одним сообщением работают в режиме Telegram-очереди.")
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
    else:
        client.send_message(chat_id, format_generic_pulse_post(parsed))
        if custom_followup_key:
            client.send_message(
                chat_id,
                "Быстрые варианты для этого запроса:",
                reply_markup=custom_followup_keyboard(custom_followup_key),
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
                        elif _is_example_draft_batch(text):
                            job_queue.enqueue_example_drafts(chat_id, int(update["update_id"]))
                        elif _is_random_example_draft(text):
                            job_queue.enqueue_random_example_draft(chat_id, int(update["update_id"]))
                        elif _is_queue_status(text):
                            client.send_message(chat_id, job_queue.status_text(), reply_markup=queue_status_keyboard())
                        elif _is_examples(text):
                            client.send_message(chat_id, format_example_list(), reply_markup=example_inline_keyboard())
                        else:
                            preset_list_mode = _preset_list_mode(text)
                            if preset_list_mode is not None:
                                client.send_message(
                                    chat_id,
                                    format_preset_list(preset_list_mode),
                                    reply_markup=preset_inline_keyboard(mode=preset_list_mode),
                                )
                            else:
                                batch_lines = _batch_request_lines(text)
                                if len(batch_lines) > 1:
                                    job_queue.enqueue_batch(chat_id, batch_lines, int(update["update_id"]))
                                else:
                                    job_queue.enqueue(chat_id, text, int(update["update_id"]))
                        continue
                    queue_callback = _extract_queue_status_callback(update)
                    if queue_callback is not None:
                        if settings.allowed_chat_ids and queue_callback.chat_id not in settings.allowed_chat_ids:
                            client.answer_callback_query(queue_callback.callback_query_id, "This chat is not allowed.")
                            client.send_message(queue_callback.chat_id, "This chat is not allowed to use this bot.")
                        else:
                            client.answer_callback_query(queue_callback.callback_query_id, "Статус очереди обновлен.")
                            client.send_message(
                                queue_callback.chat_id,
                                job_queue.status_text(),
                                reply_markup=queue_status_keyboard(),
                            )
                        continue
                    example_callback = _extract_example_callback(update)
                    if example_callback is not None:
                        if settings.allowed_chat_ids and example_callback.chat_id not in settings.allowed_chat_ids:
                            client.answer_callback_query(example_callback.callback_query_id, "This chat is not allowed.")
                            client.send_message(example_callback.chat_id, "This chat is not allowed to use this bot.")
                        else:
                            client.answer_callback_query(example_callback.callback_query_id, "Пример поставлен в очередь.")
                            job_queue.enqueue(
                                example_callback.chat_id,
                                example_callback.text,
                                int(update["update_id"]),
                                job_suffix=f"example-{example_callback.name}",
                            )
                        continue
                    custom_callback = _extract_custom_followup_callback(update)
                    if custom_callback is not None:
                        if settings.allowed_chat_ids and custom_callback.chat_id not in settings.allowed_chat_ids:
                            client.answer_callback_query(custom_callback.callback_query_id, "This chat is not allowed.")
                            client.send_message(custom_callback.chat_id, "This chat is not allowed to use this bot.")
                        else:
                            followup_text = job_queue.build_custom_followup_text(
                                custom_callback.request_key,
                                custom_callback.mode,
                            )
                            if followup_text is None:
                                client.answer_callback_query(
                                    custom_callback.callback_query_id,
                                    "Исходный запрос уже недоступен.",
                                )
                                client.send_message(
                                    custom_callback.chat_id,
                                    "Исходный запрос для кнопки уже недоступен. Отправь текст запроса еще раз.",
                                )
                            else:
                                client.answer_callback_query(custom_callback.callback_query_id, "Вариант поставлен в очередь.")
                                job_queue.enqueue(
                                    custom_callback.chat_id,
                                    followup_text,
                                    int(update["update_id"]),
                                    job_suffix=f"variant-{custom_callback.mode}",
                                )
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
