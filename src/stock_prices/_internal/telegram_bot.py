from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread
from typing import Any, Callable

import requests

from stock_prices._internal.env import get_cleanup_retention_days, get_mini_app_url
from stock_prices._internal.content_universe import (
    GeneratedContentIdea,
    build_random_content_idea,
    build_weekly_content_plan,
    resolve_universe_category,
    universe_category_label,
)
from stock_prices._internal.models import RenderSettings
from stock_prices._internal.pipeline import generate_video, log_event
from stock_prices._internal.telegram_presets import (
    PRESET_CATEGORIES,
    PRESETS,
    format_cover_list,
    format_music_list,
    format_preset_category,
    format_preset_category_list,
    format_preset_list,
    format_pulse_post,
    get_preset_category,
    get_preset,
    preset_button_label,
    preset_followup_keyboard,
    preset_inline_keyboard,
    presets_for_category,
    ready_preset_commands,
)
from stock_prices._internal.telegram_requests import ParsedTelegramRequest, parse_telegram_video_request


class TelegramApiError(RuntimeError):
    pass


TELEGRAM_BOT_COMMANDS: tuple[tuple[str, str], ...] = (
    ("menu", "главный пульт"),
    ("app", "мини-приложение"),
    ("shoot", "быстрый запуск"),
    ("shorts", "истории или свой запрос"),
    ("params", "параметры запроса"),
    ("queue", "статус очереди"),
    ("help", "короткая справка"),
)
RENDER_PROGRESS_FIRST_NOTICE_SECONDS = 90.0
RENDER_PROGRESS_REPEAT_SECONDS = 180.0
MINI_APP_PAYLOAD_TYPE = "stock_prices.video_request.v1"


def telegram_bot_command_menu() -> list[dict[str, str]]:
    return [{"command": command, "description": description} for command, description in TELEGRAM_BOT_COMMANDS]


def telegram_mini_app_menu_button(mini_app_url: str) -> dict[str, Any]:
    return {
        "type": "web_app",
        "text": "Mini App",
        "web_app": {"url": mini_app_url},
    }


def telegram_commands_menu_button() -> dict[str, str]:
    return {"type": "commands"}


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

    def set_my_commands(self, commands: list[dict[str, str]]) -> None:
        self.call("setMyCommands", commands=json.dumps(commands, ensure_ascii=False))

    def set_chat_menu_button(self, menu_button: dict[str, Any]) -> None:
        self.call("setChatMenuButton", menu_button=json.dumps(menu_button, ensure_ascii=False))

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
        mini_app_url: str | None = None,
        mini_app_menu_button: bool = False,
    ) -> None:
        self.token = token
        self.render = render
        self.allowed_chat_ids = allowed_chat_ids or set()
        self.default_engine = default_engine
        self.default_market = default_market
        self.poll_timeout = poll_timeout
        self.once = once
        self.mini_app_url = (mini_app_url or get_mini_app_url()).strip()
        self.mini_app_menu_button = mini_app_menu_button
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
    active_runtime_seconds: int | None
    active_wait_seconds: int | None
    pending_jobs: tuple[tuple[str, str, int], ...]
    completed_count: int
    failed_count: int


QUEUE_STATUS_CALLBACK_DATA = "queue:status"
MENU_CALLBACK_PREFIX = "menu:"
PRESET_CATEGORY_CALLBACK_PREFIX = "category:"
MENU_ACTIONS = {
    "guide",
    "help",
    "main_menu",
    "mini_app",
    "parameters",
    "quick_launch",
    "reference",
    "random_menu",
    "preset_categories",
    "content_plan",
    "content_plan_shorts",
    "daily_kit",
    "daily_post",
    "daily_short",
    "publication_day",
    "publication_week",
    "weekly_posts",
    "ideas",
    "examples",
    "pack",
    "kits",
    "posts",
    "drafts",
    "draft_presets",
    "hot_drafts",
    "hot_shorts",
    "hot_shorts_aurora",
    "hot_shorts_studio",
    "all_shorts",
    "all_shorts_aurora",
    "all_shorts_studio",
    "example_drafts",
    "random_shorts",
    "random_1",
    "random_2",
    "random_3",
    "random_metals_1",
    "random_drama_2",
    "random_stocks_2",
    "random_crypto_1",
    "random_draft",
    "random_example",
    "music",
    "covers",
    "queue",
}
RANDOM_SHORT_MENU_ACTIONS: dict[str, tuple[str | None, int | None, str]] = {
    "random_1": (None, 1, "Случайный шортс из 1 тикера поставлен в очередь."),
    "random_2": (None, 2, "Случайное сравнение из 2 тикеров поставлено в очередь."),
    "random_3": (None, 3, "Случайное сравнение из 3 тикеров поставлено в очередь."),
    "random_metals_1": ("metals", 1, "Random по металлам из 1 тикера поставлен в очередь."),
    "random_drama_2": ("drama", 2, "Драматичный random из 2 тикеров поставлен в очередь."),
    "random_stocks_2": ("stocks", 2, "Random по акциям из 2 тикеров поставлен в очередь."),
    "random_crypto_1": ("crypto", 1, "Random по крипто из 1 тикера поставлен в очередь."),
}
HOT_MENU_PRESETS = (
    ("Металлы", "metals"),
    ("Новая экономика", "neweconomy"),
    ("Алкоголь", "vodka"),
    ("Мечел", "mechel"),
)
CUSTOM_FOLLOWUP_MODES = {
    "draft": "draft",
    "shorts": "shorts",
    "12s": "duration=12 fps=24 gradient",
    "aurora": "theme=aurora",
    "studio": "theme=studio",
}
THEME_VARIANTS = ("default", "aurora", "studio")
PRESET_THEME_VARIANT_PREFIXES = (
    "/theme_variants",
    "/themes",
    "/variants",
    "theme variants",
    "themes",
    "variants",
    "style variants",
    "styles",
    "series",
    "варианты",
    "варианты тем",
    "все темы",
    "серия",
    "стили",
)
PRESET_KIT_PREFIXES = (
    "/kit",
    "/content_kit",
    "/content kit",
    "/pulse_kit",
    "/pulse kit",
    "/пакет",
    "kit",
    "content kit",
    "pulse kit",
    "story kit",
    "preset kit",
    "пакет",
    "пакет пульса",
    "пульс пакет",
    "контент пакет",
    "контент-пакет",
)
HOT_BATCH_THEME_ALIASES = {
    "aurora": "aurora",
    "аурора": "aurora",
    "studio": "studio",
    "студио": "studio",
    "студия": "studio",
}
HOT_DRAFT_BATCH_ALIASES = {
    "/hot_drafts",
    "/top_drafts",
    "/топ_черновики",
    "hot drafts",
    "top drafts",
    "hot draft",
    "top draft",
    "топ черновики",
    "топовые черновики",
    "горячие черновики",
    "черновики топ",
}
HOT_SHORTS_BATCH_ALIASES = {
    "/hot_shorts",
    "/top_shorts",
    "/топ_шортсы",
    "hot shorts",
    "top shorts",
    "hot short",
    "top short",
    "топ шортсы",
    "топовые шортсы",
    "горячие шортсы",
    "шортсы топ",
}
SHORTS_BATCH_ALIASES = {
    "/all shorts",
    "/shorts all",
    "/shorts batch",
    "/все шортсы",
    "all shorts",
    "shorts all",
    "shorts batch",
    "batch shorts",
    "все шортсы",
    "шортсы все",
    "пакет шортсов",
    "полный пакет шортсов",
}
CATEGORY_BATCH_SHORTS_PREFIXES = {
    "/shorts",
    "/short",
    "/шортс",
    "/шортсы",
    "shorts",
    "short",
    "top",
    "top shorts",
    "top short",
    "шортс",
    "шортсы",
    "топ",
    "топ шортсы",
    "снять",
    "снять шортс",
}
CATEGORY_BATCH_DRAFT_PREFIXES = {
    "/draft",
    "/drafts",
    "/черновик",
    "/черновики",
    "draft",
    "drafts",
    "top drafts",
    "top draft",
    "черновик",
    "черновики",
    "топ черновики",
}
CATEGORY_RANDOM_SHORTS_PREFIXES = {
    "/random",
    "/random_short",
    "/random_shorts",
    "/случайный",
    "/случайный_шортс",
    "random",
    "random short",
    "random shorts",
    "случайный",
    "случайный шортс",
    "случайный шорт",
    "случайный ролик",
}
CATEGORY_RANDOM_DRAFT_PREFIXES = {
    "/random_draft",
    "/случайный_черновик",
    "random draft",
    "random drafts",
    "draft random",
    "случайный черновик",
    "черновик случайный",
}


def queue_status_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {"inline_keyboard": [[{"text": "⏳ Статус очереди", "callback_data": QUEUE_STATUS_CALLBACK_DATA}]]}


def main_menu_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "🌐 Mini App", "callback_data": f"{MENU_CALLBACK_PREFIX}mini_app"},
            ],
            [
                {"text": "✍️ Свой ролик", "callback_data": f"{MENU_CALLBACK_PREFIX}quick_launch"},
                {"text": "🎲 Random", "callback_data": f"{MENU_CALLBACK_PREFIX}random_menu"},
            ],
            [
                {"text": "🧩 Серия", "callback_data": f"{MENU_CALLBACK_PREFIX}content_plan"},
                {"text": "⚙️ Параметры", "callback_data": f"{MENU_CALLBACK_PREFIX}parameters"},
            ],
            [
                {"text": "⏳ Очередь", "callback_data": f"{MENU_CALLBACK_PREFIX}queue"},
                {"text": "📚 Примеры", "callback_data": f"{MENU_CALLBACK_PREFIX}reference"},
            ],
            [
                {"text": "❔ Help", "callback_data": f"{MENU_CALLBACK_PREFIX}help"},
            ],
        ]
    }


def reference_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "📚 Истории", "callback_data": f"{MENU_CALLBACK_PREFIX}preset_categories"},
                {"text": "💬 Примеры", "callback_data": f"{MENU_CALLBACK_PREFIX}examples"},
            ],
            [
                {"text": "📝 Посты", "callback_data": f"{MENU_CALLBACK_PREFIX}posts"},
                {"text": "🎵 Музыка", "callback_data": f"{MENU_CALLBACK_PREFIX}music"},
            ],
            [
                {"text": "🖼 Обложки", "callback_data": f"{MENU_CALLBACK_PREFIX}covers"},
                {"text": "🏠 Меню", "callback_data": f"{MENU_CALLBACK_PREFIX}main_menu"},
            ],
        ]
    }


def random_menu_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "1 тикер", "callback_data": f"{MENU_CALLBACK_PREFIX}random_1"},
                {"text": "2 тикера", "callback_data": f"{MENU_CALLBACK_PREFIX}random_2"},
                {"text": "3 тикера", "callback_data": f"{MENU_CALLBACK_PREFIX}random_3"},
            ],
            [
                {"text": "Металлы 1", "callback_data": f"{MENU_CALLBACK_PREFIX}random_metals_1"},
                {"text": "Драма 2", "callback_data": f"{MENU_CALLBACK_PREFIX}random_drama_2"},
                {"text": "Крипто 1", "callback_data": f"{MENU_CALLBACK_PREFIX}random_crypto_1"},
            ],
            [
                {"text": "Акции 2", "callback_data": f"{MENU_CALLBACK_PREFIX}random_stocks_2"},
                {"text": "Серия", "callback_data": f"{MENU_CALLBACK_PREFIX}content_plan"},
            ],
            [
                {"text": "Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
                {"text": "Меню", "callback_data": f"{MENU_CALLBACK_PREFIX}main_menu"},
            ],
        ]
    }


def quick_launch_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return main_menu_keyboard()


def mini_app_keyboard(mini_app_url: str) -> dict[str, Any]:
    return {
        "keyboard": [
            [
                {
                    "text": "Открыть Mini App",
                    "web_app": {"url": mini_app_url},
                }
            ],
            [
                {"text": "Меню"},
                {"text": "Статус очереди"},
            ],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
        "input_field_placeholder": "Открой Mini App или напиши тикеры вручную",
    }


def help_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "✍️ Свой ролик", "callback_data": f"{MENU_CALLBACK_PREFIX}quick_launch"},
                {"text": "🎲 Random", "callback_data": f"{MENU_CALLBACK_PREFIX}random_menu"},
            ],
            [
                {"text": "🧩 Серия", "callback_data": f"{MENU_CALLBACK_PREFIX}content_plan"},
                {"text": "📚 Примеры", "callback_data": f"{MENU_CALLBACK_PREFIX}reference"},
            ],
            [
                {"text": "⚙️ Параметры", "callback_data": f"{MENU_CALLBACK_PREFIX}parameters"},
                {"text": "🧭 Гайд", "callback_data": f"{MENU_CALLBACK_PREFIX}guide"},
            ],
            [
                {"text": "⏳ Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
                {"text": "🏠 Меню", "callback_data": f"{MENU_CALLBACK_PREFIX}main_menu"},
            ],
        ]
    }


def custom_followup_keyboard(request_key: str) -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "Черновик 4s", "callback_data": f"custom:{request_key}:draft"},
                {"text": "Шортс 16s", "callback_data": f"custom:{request_key}:shorts"},
            ],
            [
                {"text": "12s", "callback_data": f"custom:{request_key}:12s"},
            ],
            [
                {"text": "Aurora 16s", "callback_data": f"custom:{request_key}:aurora"},
                {"text": "Studio 16s", "callback_data": f"custom:{request_key}:studio"},
            ],
            [
                {"text": "Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
                {"text": "Меню", "callback_data": f"{MENU_CALLBACK_PREFIX}main_menu"},
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


def _format_queue_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}с"
    minutes, rest_seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}м {rest_seconds:02d}с"
    hours, rest_minutes = divmod(minutes, 60)
    return f"{hours}ч {rest_minutes:02d}м"


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
        "Проверенные примеры запросов без LLM:",
        "",
    ]
    for index, example in enumerate(_TELEGRAM_EXAMPLES, start=1):
        lines.append(f"{index}. {example.button_label} - {example.description}")
        lines.append(f"   {example.request}")
        lines.append("")
    lines.append("Кнопки ниже запускают пример, случайный draft или весь набор draft-примеров.")
    lines.append("Идеи фиксированные: без автопридумывания и LLM.")
    return "\n".join(lines).strip()


def example_inline_keyboard(columns: int = 2) -> dict[str, list[list[dict[str, str]]]]:
    buttons = [
        {"text": example.button_label, "callback_data": f"example:{example.name}"}
        for example in _TELEGRAM_EXAMPLES
    ]
    rows = [buttons[index : index + columns] for index in range(0, len(buttons), columns)]
    rows.append(
        [
            {"text": "🎲 Случайный draft", "callback_data": f"{MENU_CALLBACK_PREFIX}random_example"},
            {"text": "🧪 Все draft", "callback_data": f"{MENU_CALLBACK_PREFIX}example_drafts"},
        ]
    )
    rows.append(
        [
            {"text": "⏳ Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
            {"text": "🏠 Меню", "callback_data": f"{MENU_CALLBACK_PREFIX}main_menu"},
        ]
    )
    return {"inline_keyboard": rows}


def format_post_list() -> str:
    lines = [
        "Текстовые пакеты для Пульса:",
        "",
    ]
    for preset in PRESETS:
        lines.append(f"{preset_button_label(preset)}: post {preset.name}")
        lines.append(preset.description)
        lines.append("")
    lines.append("Кнопки ниже возвращают готовый текст, обложки, хэштеги, музыку и дисклеймер без рендера.")
    lines.append("Для произвольного запроса: post LKOH SBER 2020 2024 или текст SBER LKOH за год.")
    return "\n".join(lines).strip()


def post_inline_keyboard(columns: int = 2) -> dict[str, list[list[dict[str, str]]]]:
    buttons = [
        {"text": preset_button_label(preset), "callback_data": f"post:{preset.name}"}
        for preset in PRESETS
    ]
    rows = [buttons[index : index + columns] for index in range(0, len(buttons), columns)]
    return {"inline_keyboard": rows}


def _weekly_content_items(
    today: date | None = None,
    *,
    days: int = 7,
    count: int | None = None,
    categories: tuple[str | None, ...] = (),
) -> tuple[GeneratedContentIdea, ...]:
    return build_weekly_content_plan(today, days=days, count=count, categories=categories or None)


def _controlled_content_plan_items(
    days: int = 7,
    count: int | None = None,
    categories: tuple[str | None, ...] = (),
) -> tuple[GeneratedContentIdea, ...]:
    if days == 7 and count is None and not categories:
        return _weekly_content_items()
    return _weekly_content_items(days=days, count=count, categories=categories)


def _today() -> date:
    return date.today()


def _daily_content_plan_item(today: date | None = None) -> tuple[int, GeneratedContentIdea]:
    day = today or _today()
    plan = _weekly_content_items(day)
    index = (day.isoweekday() - 1) % len(plan)
    return index + 1, plan[index]


def _content_plan_control_summary(days: int, count: int | None, categories: tuple[str | None, ...]) -> str:
    controls = [f"{days} выпуск(ов)"]
    if count is not None:
        controls.append(f"по {count} тикер(а)")
    if categories:
        controls.append("категории: " + ", ".join(universe_category_label(category) for category in categories))
    return "; ".join(controls)


def format_content_plan(
    plan: tuple[GeneratedContentIdea, ...] | None = None,
    *,
    days: int = 7,
    count: int | None = None,
    categories: tuple[str | None, ...] = (),
) -> str:
    items = plan or _controlled_content_plan_items(days=days, count=count, categories=categories)
    lines = [
        "Контент-план для Пульса:",
        "",
        "План без LLM: тикеры случайно комбинируются из расширяемой вселенной по категориям и пересечению истории.",
        f"Параметры: {_content_plan_control_summary(len(items), count, categories)}.",
        "Можно поставить весь план в очередь одной кнопкой или взять отдельный запрос из списка.",
        "",
    ]
    for index, item in enumerate(items, start=1):
        track = item.music_tracks[0] if item.music_tracks else item.music_mood
        lines.append(f"День {index}: {item.title}")
        lines.append(f"Запрос: {item.request}")
        lines.append(f"Обложка: {item.cover_text}")
        lines.append(f"Музыка: {track}")
        lines.append("")
    lines.append(f"Первая кнопка ставит эти {len(items)} shorts в очередь. Свой сценарий можно написать одной строкой.")
    return "\n".join(lines).strip()


def _format_content_plan_action(action: TelegramContentPlanAction) -> str:
    return format_content_plan(
        _controlled_content_plan_items(days=action.days, count=action.count, categories=action.categories),
        days=action.days,
        count=action.count,
        categories=action.categories,
    )


def content_plan_keyboard(columns: int = 2) -> dict[str, list[list[dict[str, str]]]]:
    rows = [
        [
            {"text": "🎬 Весь план", "callback_data": f"{MENU_CALLBACK_PREFIX}content_plan_shorts"},
            {"text": "📝 Посты", "callback_data": f"{MENU_CALLBACK_PREFIX}weekly_posts"},
        ]
    ]
    rows.append(
        [
            {"text": "🎲 Случайный", "callback_data": f"{MENU_CALLBACK_PREFIX}random_shorts"},
            {"text": "📚 Примеры", "callback_data": f"{MENU_CALLBACK_PREFIX}reference"},
        ]
    )
    rows.append(
        [
            {"text": "⏳ Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
            {"text": "🏠 Меню", "callback_data": f"{MENU_CALLBACK_PREFIX}main_menu"},
        ]
    )
    return {"inline_keyboard": rows}


def format_preset_kit(preset_name: str) -> str:
    preset = get_preset(preset_name)
    cover_texts = " / ".join(preset.cover_texts)
    music_tracks = ", ".join(preset.music_tracks)
    commands = "\n".join(f"- {command}" for command in ready_preset_commands(preset))
    return (
        f"Пакет сценария: {preset.title}\n"
        f"{preset.description}\n\n"
        f"Шортс: preset {preset.name}\n"
        f"Черновик: preset {preset.name} draft\n"
        f"Варианты тем: variants {preset.name}\n"
        f"Пост без рендера: post {preset.name}\n\n"
        f"Готовые команды:\n{commands}\n\n"
        f"Хук: {preset.hook}\n"
        f"Текст на обложку: {cover_texts}.\n"
        f"Музыка/монтаж: {preset.music_mood}.\n"
        f"Треки-референсы: {music_tracks}.\n\n"
        "Права на треки нужно проверять отдельно. Это фиксированный пакет без LLM."
    )


def preset_kit_keyboard(preset_name: str) -> dict[str, list[list[dict[str, str]]]]:
    preset = get_preset(preset_name)
    return {
        "inline_keyboard": [
            [
                {"text": "Шортс 16s", "callback_data": f"preset:{preset.name}:shorts"},
                {"text": "Черновик 4s", "callback_data": f"preset:{preset.name}:draft"},
            ],
            [
                {"text": "Все темы x3", "callback_data": f"preset:{preset.name}:themes"},
                {"text": "12s", "callback_data": f"preset:{preset.name}:12s"},
            ],
            [
                {"text": "Пост", "callback_data": f"post:{preset.name}"},
                {"text": "Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
            ],
        ]
    }


def format_daily_content_kit(today: date | None = None) -> str:
    day_index, item = _daily_content_plan_item(today)
    tracks = ", ".join(item.music_tracks)
    return (
        f"Пакет дня: Д{day_index} {item.title}\n"
        "Сценарий взят из недельного random-плана тикерной вселенной.\n\n"
        f"Шортс: {item.request}\n"
        f"Пост без рендера: пост дня\n"
        f"Обложка: {item.cover_text}\n"
        f"Монтаж: {item.music_mood}.\n"
        f"Треки-референсы: {tracks}.\n\n"
        f"{item.post_text}\n\n"
        "Не является индивидуальной инвестиционной рекомендацией."
    )


def daily_content_kit_keyboard(today: date | None = None) -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "Шортс дня", "callback_data": f"{MENU_CALLBACK_PREFIX}daily_short"},
                {"text": "Пост дня", "callback_data": f"{MENU_CALLBACK_PREFIX}daily_post"},
            ],
            [
                {"text": "План", "callback_data": f"{MENU_CALLBACK_PREFIX}content_plan"},
                {"text": "Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
            ],
        ]
    }


def format_daily_post(today: date | None = None) -> str:
    day_index, item = _daily_content_plan_item(today)
    return format_generated_weekly_post(day_index, item)


def daily_post_keyboard(today: date | None = None) -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "Шортс дня", "callback_data": f"{MENU_CALLBACK_PREFIX}daily_short"},
                {"text": "Пакет дня", "callback_data": f"{MENU_CALLBACK_PREFIX}daily_kit"},
            ],
            [
                {"text": "План", "callback_data": f"{MENU_CALLBACK_PREFIX}content_plan"},
                {"text": "Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
            ],
        ]
    }


def format_weekly_post_intro() -> str:
    return (
        "Посты недели для Пульса:\n"
        "Отправляю 7 готовых текстов из недельного контент-плана отдельными сообщениями, чтобы их было удобно брать в работу."
    )


def format_weekly_post(day_index: int, preset_name: str) -> str:
    preset = get_preset(preset_name)
    return (
        f"Пост недели: Д{day_index} {preset.title}\n"
        "Сценарий взят из недельного контент-плана.\n\n"
        f"{format_pulse_post(preset)}"
    )


def format_generated_weekly_post(day_index: int, item: GeneratedContentIdea) -> str:
    tracks = ", ".join(item.music_tracks)
    return (
        f"Пост недели: Д{day_index} {item.title}\n"
        "Пост для Пульса (можно копировать):\n\n"
        f"{item.post_text}\n\n"
        f"Запрос: {item.request}\n"
        f"Обложка: {item.cover_text}\n"
        f"Монтаж: {item.music_mood}.\n"
        f"Треки-референсы: {tracks}.\n\n"
        "Не является индивидуальной инвестиционной рекомендацией."
    )


def weekly_posts_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "📊 План", "callback_data": f"{MENU_CALLBACK_PREFIX}content_plan"},
                {"text": "🎬 Неделя", "callback_data": f"{MENU_CALLBACK_PREFIX}publication_week"},
            ],
            [
                {"text": "⏳ Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
            ],
        ]
    }


def send_weekly_posts(client: TelegramClient, chat_id: int) -> None:
    plan = _weekly_content_items()
    client.send_message(chat_id, format_weekly_post_intro(), reply_markup=weekly_posts_keyboard())
    for index, item in enumerate(plan, start=1):
        client.send_message(chat_id, format_generated_weekly_post(index, item))


def format_weekly_publication_pack(plan: tuple[GeneratedContentIdea, ...] | None = None) -> str:
    items = plan or _weekly_content_items()
    lines = [
        "Недельный выпуск для Пульса:",
        "",
        "Ставлю 7 shorts в очередь и даю компактный чеклист публикаций. План собран случайно из тикерной вселенной.",
        "",
    ]
    for index, item in enumerate(items, start=1):
        track = item.music_tracks[0] if item.music_tracks else item.music_mood
        lines.append(f"Д{index}: {item.title}")
        lines.append(f"Шортс: {item.request}")
        lines.append(f"Обложка: {item.cover_text}")
        lines.append(f"Музыка: {track}")
        lines.append("")
    lines.append("Статус рендера: /queue. Ручные fixed-сценарии остаются в /ideas.")
    return "\n".join(lines).strip()


def weekly_publication_pack_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "⏳ Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
                {"text": "📊 План", "callback_data": f"{MENU_CALLBACK_PREFIX}content_plan"},
            ],
            [
                {"text": "📝 Неделя", "callback_data": f"{MENU_CALLBACK_PREFIX}weekly_posts"},
                {"text": "Посты", "callback_data": f"{MENU_CALLBACK_PREFIX}posts"},
            ],
            [
                {"text": "🎵 Музыка", "callback_data": f"{MENU_CALLBACK_PREFIX}music"},
                {"text": "🖼 Обложки", "callback_data": f"{MENU_CALLBACK_PREFIX}covers"},
            ],
        ]
    }


def format_preset_kit_list() -> str:
    lines = [
        "Публикационные пакеты сценариев:",
        "",
    ]
    for preset in PRESETS:
        lines.append(f"{preset_button_label(preset)}: kit {preset.name}")
        lines.append(preset.description)
        lines.append("")
    lines.append("Кнопки ниже открывают хук, обложки, музыку и действия для выбранного preset без немедленного рендера.")
    return "\n".join(lines).strip()


def preset_kit_inline_keyboard(columns: int = 2) -> dict[str, list[list[dict[str, str]]]]:
    buttons = [
        {"text": preset_button_label(preset), "callback_data": f"kit:{preset.name}"}
        for preset in PRESETS
    ]
    rows = [buttons[index : index + columns] for index in range(0, len(buttons), columns)]
    return {"inline_keyboard": rows}


def preset_category_inline_keyboard(columns: int = 2, mode: str = "shorts") -> dict[str, list[list[dict[str, str]]]]:
    if mode not in {"shorts", "draft"}:
        msg = f"Unknown preset category keyboard mode: {mode}."
        raise ValueError(msg)
    category_suffix = ":draft" if mode == "draft" else ""
    all_label = "Полный список" if mode == "draft" else "Все preset"
    all_callback = "draft_presets" if mode == "draft" else "ideas"
    buttons = [
        {"text": category.title, "callback_data": f"{PRESET_CATEGORY_CALLBACK_PREFIX}{category.name}{category_suffix}"}
        for category in PRESET_CATEGORIES
    ]
    rows = [buttons[index : index + columns] for index in range(0, len(buttons), columns)]
    rows.append(
        [
            {"text": all_label, "callback_data": f"{MENU_CALLBACK_PREFIX}{all_callback}"},
            {"text": "📚 Справка", "callback_data": f"{MENU_CALLBACK_PREFIX}reference"},
        ]
    )
    return {"inline_keyboard": rows}


def preset_category_keyboard(category_name: str, columns: int = 2, mode: str = "shorts") -> dict[str, list[list[dict[str, str]]]]:
    if mode not in {"shorts", "draft"}:
        msg = f"Unknown preset category keyboard mode: {mode}."
        raise ValueError(msg)
    category = get_preset_category(category_name)
    preset_suffix = ":draft" if mode == "draft" else ":shorts"
    back_callback = "drafts" if mode == "draft" else "preset_categories"
    buttons = [
        {"text": preset_button_label(preset), "callback_data": f"preset:{preset.name}{preset_suffix}"}
        for preset in presets_for_category(category.name)
    ]
    rows = [buttons[index : index + columns] for index in range(0, len(buttons), columns)]
    rows.append(
        [
            {"text": "Категории", "callback_data": f"{MENU_CALLBACK_PREFIX}{back_callback}"},
            {"text": "Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
        ]
    )
    return {"inline_keyboard": rows}


def format_pulse_pack() -> str:
    return (
        "Пакеты для Пульса\n\n"
        "Здесь только готовые production-действия: top-серия, черновики, случайный ролик "
        "или batch по всем preset.\n\n"
        "Истории по категориям, тексты, музыку, обложки и полный список preset держу в Справочнике, чтобы этот экран "
        "оставался коротким.\n\n"
        "Это фиксированный пакет без LLM и без автопридумывания идей."
    )


def pulse_pack_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "✨ Top Studio", "callback_data": f"{MENU_CALLBACK_PREFIX}hot_shorts_studio"},
                {"text": "🎲 Случайный", "callback_data": f"{MENU_CALLBACK_PREFIX}random_shorts"},
            ],
            [
                {"text": "🔥 Top", "callback_data": f"{MENU_CALLBACK_PREFIX}hot_shorts"},
                {"text": "🧪 Draft", "callback_data": f"{MENU_CALLBACK_PREFIX}hot_drafts"},
            ],
            [
                {"text": "🎬 Все", "callback_data": f"{MENU_CALLBACK_PREFIX}all_shorts"},
                {"text": "🏛 Studio", "callback_data": f"{MENU_CALLBACK_PREFIX}all_shorts_studio"},
            ],
            [
                {"text": "📚 Справка", "callback_data": f"{MENU_CALLBACK_PREFIX}reference"},
                {"text": "⏳ Очередь", "callback_data": f"{MENU_CALLBACK_PREFIX}queue"},
            ],
        ]
    }


@dataclass(frozen=True)
class TelegramPresetCallback:
    callback_query_id: str
    chat_id: int
    text: str


@dataclass(frozen=True)
class TelegramPresetThemeVariantsCallback:
    callback_query_id: str
    chat_id: int
    preset_name: str


@dataclass(frozen=True)
class TelegramExampleCallback:
    callback_query_id: str
    chat_id: int
    text: str
    name: str


@dataclass(frozen=True)
class TelegramPostCallback:
    callback_query_id: str
    chat_id: int
    preset_name: str


@dataclass(frozen=True)
class TelegramPresetKitCallback:
    callback_query_id: str
    chat_id: int
    preset_name: str


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


@dataclass(frozen=True)
class TelegramMenuCallback:
    callback_query_id: str
    chat_id: int
    action: str


@dataclass(frozen=True)
class TelegramPresetCategoryCallback:
    callback_query_id: str
    chat_id: int
    category_name: str
    mode: str = "shorts"


@dataclass(frozen=True)
class TelegramCategoryPresetAction:
    kind: str
    mode: str
    category_name: str
    theme: str | None = None


@dataclass(frozen=True)
class TelegramRandomContentAction:
    mode: str
    category_name: str | None = None
    count: int | None = None
    theme: str | None = None


@dataclass(frozen=True)
class TelegramContentPlanAction:
    mode: str
    days: int = 7
    count: int | None = None
    categories: tuple[str | None, ...] = ()


class TelegramJobQueue:
    def __init__(self, client: TelegramClient, settings: TelegramBotSettings) -> None:
        self.client = client
        self.settings = settings
        self._jobs: Queue[TelegramJob | None] = Queue()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._pending_jobs: list[TelegramJob] = []
        self._active_job: TelegramJob | None = None
        self._active_started_at: float | None = None
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
                f"Задача ID {job.job_id} поставлена в очередь.\nПозиция: {queue_position}.",
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

    def enqueue_preset_shorts(self, chat_id: int, update_id: int, theme: str | None = None) -> list[TelegramJob]:
        labels = ", ".join(preset_button_label(preset) for preset in PRESETS)
        theme_suffix = f" theme={theme}" if theme else ""
        theme_label = f" в теме {theme}" if theme else ""
        self.client.send_message(
            chat_id,
            f"Ставлю в очередь {len(PRESETS)} shorts-роликов{theme_label}: {labels}.",
            reply_markup=queue_status_keyboard(),
        )
        jobs: list[TelegramJob] = []
        for index, preset in enumerate(PRESETS, start=1):
            job_suffix_theme = f"-{theme}" if theme else ""
            jobs.append(
                self.enqueue(
                    chat_id,
                    f"preset {preset.name} shorts{theme_suffix}",
                    update_id,
                    job_suffix=f"shorts{job_suffix_theme}-{index}-{preset.name}",
                    notify=False,
                )
            )
        return jobs

    def _enqueue_category_presets(
        self,
        chat_id: int,
        update_id: int,
        category_name: str,
        mode: str,
        theme: str | None = None,
    ) -> list[TelegramJob]:
        if mode not in {"draft", "shorts"}:
            msg = f"Unsupported category preset mode: {mode}"
            raise ValueError(msg)
        category = get_preset_category(category_name)
        presets = presets_for_category(category.name)
        labels = ", ".join(preset_button_label(preset) for preset in presets)
        theme_suffix = f" theme={theme}" if theme and mode == "shorts" else ""
        theme_label = f" в теме {theme}" if theme and mode == "shorts" else ""
        mode_label = "draft-черновиков" if mode == "draft" else "shorts-роликов"
        self.client.send_message(
            chat_id,
            f"Ставлю в очередь {len(presets)} {mode_label} категории {category.title}{theme_label}: {labels}.",
            reply_markup=queue_status_keyboard(),
        )
        jobs: list[TelegramJob] = []
        for index, preset in enumerate(presets, start=1):
            job_suffix_theme = f"-{theme}" if theme and mode == "shorts" else ""
            jobs.append(
                self.enqueue(
                    chat_id,
                    f"preset {preset.name} {mode}{theme_suffix}",
                    update_id,
                    job_suffix=f"{category.name}-{mode}{job_suffix_theme}-{index}-{preset.name}",
                    notify=False,
                )
            )
        return jobs

    def enqueue_category_preset_shorts(
        self,
        chat_id: int,
        update_id: int,
        category_name: str,
        theme: str | None = None,
    ) -> list[TelegramJob]:
        return self._enqueue_category_presets(chat_id, update_id, category_name, "shorts", theme=theme)

    def enqueue_category_preset_drafts(self, chat_id: int, update_id: int, category_name: str) -> list[TelegramJob]:
        return self._enqueue_category_presets(chat_id, update_id, category_name, "draft")

    def enqueue_content_plan_shorts(
        self,
        chat_id: int,
        update_id: int,
        *,
        days: int = 7,
        count: int | None = None,
        categories: tuple[str | None, ...] = (),
    ) -> list[TelegramJob]:
        plan = _controlled_content_plan_items(days=days, count=count, categories=categories)
        labels = ", ".join(f"Д{index} {' / '.join(item.tickers)}" for index, item in enumerate(plan, start=1))
        controls = []
        if days != 7:
            controls.append(f"{days} дн.")
        if count is not None:
            controls.append(f"{count} тикер(а)")
        if categories:
            controls.append("категории: " + ", ".join(universe_category_label(category) for category in categories))
        control_label = f" ({'; '.join(controls)})" if controls else ""
        self.client.send_message(
            chat_id,
            f"Ставлю в очередь {len(plan)} shorts-роликов контент-плана{control_label}: {labels}.",
            reply_markup=queue_status_keyboard(),
        )
        jobs: list[TelegramJob] = []
        for index, item in enumerate(plan, start=1):
            jobs.append(
                self.enqueue(
                    chat_id,
                    item.request,
                    update_id,
                    job_suffix=f"plan-shorts-{index}-{item.slug}",
                    notify=False,
                )
            )
        return jobs

    def enqueue_daily_content_plan_short(self, chat_id: int, update_id: int) -> TelegramJob:
        day_index, item = _daily_content_plan_item()
        self.client.send_message(
            chat_id,
            f"Шортс дня: Д{day_index} {item.title}. Ставлю random shorts-ролик из тикерной вселенной в очередь.",
            reply_markup=queue_status_keyboard(),
        )
        return self.enqueue(
            chat_id,
            item.request,
            update_id,
            job_suffix=f"daily-short-{day_index}-{item.slug}",
            notify=False,
        )

    def enqueue_daily_publication_day(self, chat_id: int, update_id: int) -> TelegramJob:
        day_index, item = _daily_content_plan_item()
        self.client.send_message(
            chat_id,
            f"Публикационный день: Д{day_index} {item.title}. "
            "Ставлю random shorts-ролик в очередь и отправляю пакет для поста.",
            reply_markup=queue_status_keyboard(),
        )
        self.client.send_message(chat_id, format_daily_content_kit(), reply_markup=daily_content_kit_keyboard())
        return self.enqueue(
            chat_id,
            item.request,
            update_id,
            job_suffix=f"publication-day-{day_index}-{item.slug}",
            notify=False,
        )

    def enqueue_weekly_publication_pack(self, chat_id: int, update_id: int) -> list[TelegramJob]:
        plan = _weekly_content_items()
        labels = ", ".join(f"Д{index} {' / '.join(item.tickers)}" for index, item in enumerate(plan, start=1))
        self.client.send_message(
            chat_id,
            f"Недельный выпуск: ставлю в очередь {len(plan)} shorts-роликов контент-плана: {labels}.",
            reply_markup=queue_status_keyboard(),
        )
        self.client.send_message(
            chat_id,
            format_weekly_publication_pack(plan),
            reply_markup=weekly_publication_pack_keyboard(),
        )
        jobs: list[TelegramJob] = []
        for index, item in enumerate(plan, start=1):
            jobs.append(
                self.enqueue(
                    chat_id,
                    item.request,
                    update_id,
                    job_suffix=f"publication-week-{index}-{item.slug}",
                    notify=False,
                )
            )
        return jobs

    def _enqueue_hot_presets(self, chat_id: int, update_id: int, mode: str, theme: str | None = None) -> list[TelegramJob]:
        if mode not in {"draft", "shorts"}:
            msg = f"Unsupported hot preset mode: {mode}"
            raise ValueError(msg)
        labels = ", ".join(label for label, _preset_name in HOT_MENU_PRESETS)
        mode_label = "top-draft" if mode == "draft" else "top-shorts"
        theme_suffix = f" theme={theme}" if theme else ""
        theme_label = f" в теме {theme}" if theme else ""
        self.client.send_message(
            chat_id,
            f"Ставлю в очередь {len(HOT_MENU_PRESETS)} {mode_label}{theme_label}: {labels}.",
            reply_markup=queue_status_keyboard(),
        )
        jobs: list[TelegramJob] = []
        for index, (_label, preset_name) in enumerate(HOT_MENU_PRESETS, start=1):
            job_suffix_theme = f"-{theme}" if theme else ""
            jobs.append(
                self.enqueue(
                    chat_id,
                    f"preset {preset_name} {mode}{theme_suffix}",
                    update_id,
                    job_suffix=f"hot-{mode}{job_suffix_theme}-{index}-{preset_name}",
                    notify=False,
                )
            )
        return jobs

    def enqueue_hot_preset_drafts(self, chat_id: int, update_id: int) -> list[TelegramJob]:
        return self._enqueue_hot_presets(chat_id, update_id, "draft")

    def enqueue_hot_preset_shorts(self, chat_id: int, update_id: int) -> list[TelegramJob]:
        return self._enqueue_hot_presets(chat_id, update_id, "shorts")

    def enqueue_hot_preset_shorts_with_theme(self, chat_id: int, update_id: int, theme: str) -> list[TelegramJob]:
        return self._enqueue_hot_presets(chat_id, update_id, "shorts", theme=theme)

    def enqueue_preset_theme_variants(self, chat_id: int, update_id: int, preset_name: str) -> list[TelegramJob]:
        preset = get_preset(preset_name)
        label = preset_button_label(preset)
        themes = ", ".join(THEME_VARIANTS)
        self.client.send_message(
            chat_id,
            f"Ставлю в очередь {len(THEME_VARIANTS)} визуальных варианта для {label}: {themes}.",
            reply_markup=queue_status_keyboard(),
        )
        jobs: list[TelegramJob] = []
        for index, theme in enumerate(THEME_VARIANTS, start=1):
            jobs.append(
                self.enqueue(
                    chat_id,
                    f"preset {preset.name} shorts theme={theme}",
                    update_id,
                    job_suffix=f"theme-{index}-{theme}-{preset.name}",
                    notify=False,
                )
            )
        return jobs

    def enqueue_random_universe_shorts(
        self,
        chat_id: int,
        update_id: int,
        category_name: str | None = None,
        count: int | None = None,
        theme: str | None = None,
    ) -> TelegramJob:
        resolved_category = resolve_universe_category(category_name)
        item = build_random_content_idea(resolved_category, count=count, theme=theme)
        category_label = f" категории {universe_category_label(resolved_category)}" if resolved_category else ""
        count_label = f", {count} тикер{'' if count == 1 else 'а' if count in {2, 3} else 'ов'}" if count else ""
        theme_label = f", тема {theme}" if theme else ""
        self.client.send_message(
            chat_id,
            f"Случайный шортс{category_label}{count_label}{theme_label}: {item.title}. Ставлю shorts-ролик в очередь.",
            reply_markup=queue_status_keyboard(),
        )
        job_suffix_theme = f"-{theme}" if theme else ""
        job_suffix_count = f"-{count}x" if count else ""
        job_suffix_category = f"-{resolved_category}" if resolved_category else ""
        return self.enqueue(
            chat_id,
            item.request,
            update_id,
            job_suffix=f"random{job_suffix_category}-shorts{job_suffix_count}{job_suffix_theme}-{item.slug}",
            notify=False,
        )

    def enqueue_random_universe_draft(
        self,
        chat_id: int,
        update_id: int,
        category_name: str | None = None,
        count: int | None = None,
    ) -> TelegramJob:
        resolved_category = resolve_universe_category(category_name)
        item = build_random_content_idea(resolved_category, count=count, mode="draft")
        category_label = f" категории {universe_category_label(resolved_category)}" if resolved_category else ""
        count_label = f", {count} тикер{'' if count == 1 else 'а' if count in {2, 3} else 'ов'}" if count else ""
        self.client.send_message(
            chat_id,
            f"Случайный черновик{category_label}{count_label}: {item.title}. Ставлю короткий draft в очередь.",
            reply_markup=queue_status_keyboard(),
        )
        job_suffix_count = f"-{count}x" if count else ""
        job_suffix_category = f"-{resolved_category}" if resolved_category else ""
        return self.enqueue(
            chat_id,
            item.request,
            update_id,
            job_suffix=f"random{job_suffix_category}-draft{job_suffix_count}-{item.slug}",
            notify=False,
        )

    def enqueue_random_category_universe_shorts(
        self,
        chat_id: int,
        update_id: int,
        category_name: str,
        theme: str | None = None,
        count: int | None = None,
    ) -> TelegramJob:
        return self.enqueue_random_universe_shorts(
            chat_id,
            update_id,
            category_name=category_name,
            count=count,
            theme=theme,
        )

    def enqueue_random_category_universe_draft(
        self,
        chat_id: int,
        update_id: int,
        category_name: str,
        count: int | None = None,
    ) -> TelegramJob:
        return self.enqueue_random_universe_draft(
            chat_id,
            update_id,
            category_name=category_name,
            count=count,
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
        previews = "\n".join(f"{index}. {_job_preview(text, 48)}" for index, text in enumerate(texts[:6], start=1))
        if len(texts) > 6:
            previews = f"{previews}\n... еще {len(texts) - 6}"
        self.client.send_message(
            chat_id,
            f"Поставил в очередь {len(jobs)} {task_word} из одного сообщения:\n{previews}",
            reply_markup=queue_status_keyboard(),
        )
        return jobs

    def snapshot(self) -> TelegramQueueSnapshot:
        with self._lock:
            now = time.monotonic()
            active_runtime_seconds: int | None = None
            active_wait_seconds: int | None = None
            if self._active_job:
                active_started_at = self._active_started_at or now
                active_runtime_seconds = max(0, int(now - active_started_at))
                active_wait_seconds = max(0, int(active_started_at - self._active_job.queued_at))
            return TelegramQueueSnapshot(
                active_job_id=self._active_job.job_id if self._active_job else None,
                active_preview=_job_preview(self._active_job.text) if self._active_job else "",
                active_runtime_seconds=active_runtime_seconds,
                active_wait_seconds=active_wait_seconds,
                pending_jobs=tuple(
                    (job.job_id, _job_preview(job.text), max(0, int(now - job.queued_at)))
                    for job in self._pending_jobs
                ),
                completed_count=self._completed_count,
                failed_count=self._failed_count,
            )

    def status_text(self) -> str:
        snapshot = self.snapshot()
        lines = ["Очередь Telegram"]
        if snapshot.active_job_id:
            lines.append(f"В работе: ID {snapshot.active_job_id} - {snapshot.active_preview}")
            if snapshot.active_runtime_seconds is not None:
                lines.append(f"Идет: {_format_queue_duration(snapshot.active_runtime_seconds)}")
            if snapshot.active_wait_seconds:
                lines.append(f"Ждал перед стартом: {_format_queue_duration(snapshot.active_wait_seconds)}")
        else:
            lines.append("В работе: нет активного рендера")

        pending_count = len(snapshot.pending_jobs)
        lines.append(f"Ожидают: {pending_count}")
        for index, (job_id, preview, wait_seconds) in enumerate(snapshot.pending_jobs[:8], start=1):
            lines.append(f"{index}. ID {job_id} - {preview} (ждет {_format_queue_duration(wait_seconds)})")
        if pending_count > 8:
            lines.append(f"... еще {pending_count - 8}")
        lines.append(f"Завершено: {snapshot.completed_count}, ошибки: {snapshot.failed_count}")
        return "\n".join(lines)

    def _mark_started(self, job: TelegramJob) -> None:
        with self._lock:
            self._pending_jobs = [pending_job for pending_job in self._pending_jobs if pending_job.job_id != job.job_id]
            self._active_job = job
            self._active_started_at = time.monotonic()

    def _mark_finished(self, job: TelegramJob, success: bool) -> None:
        with self._lock:
            if self._active_job and self._active_job.job_id == job.job_id:
                self._active_job = None
                self._active_started_at = None
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
    if not text:
        text = (_request_text_from_web_app_data((message.get("web_app_data") or {}).get("data")) or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not text or chat_id is None:
        return None
    return int(chat_id), text


def _request_text_from_web_app_data(data: Any) -> str | None:
    if not isinstance(data, str):
        return None
    payload = data.strip()
    if not payload:
        return None
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return payload
    if not isinstance(decoded, dict):
        return payload
    payload_type = decoded.get("type")
    if payload_type is not None and payload_type != MINI_APP_PAYLOAD_TYPE:
        return None
    request_text = decoded.get("text") or decoded.get("request")
    if isinstance(request_text, str) and request_text.strip():
        return request_text.strip()
    return None


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
    if mode not in {"", "draft", "shorts", "12s", "aurora", "studio"}:
        return None
    text = f"preset {preset_name}"
    if mode == "draft":
        text = f"{text} draft"
    elif mode == "shorts":
        text = f"{text} shorts"
    elif mode == "12s":
        text = f"{text} duration=12"
    elif mode in {"aurora", "studio"}:
        text = f"{text} theme={mode}"
    return TelegramPresetCallback(str(callback_query_id), int(chat_id), text)


def _extract_preset_theme_variants_callback(update: dict[str, Any]) -> TelegramPresetThemeVariantsCallback | None:
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
    if len(parts) != 3 or parts[2].lower() != "themes":
        return None
    try:
        preset = get_preset(parts[1])
    except ValueError:
        return None
    return TelegramPresetThemeVariantsCallback(str(callback_query_id), int(chat_id), preset.name)


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


def _extract_post_callback(update: dict[str, Any]) -> TelegramPostCallback | None:
    callback_query = update.get("callback_query") or {}
    callback_query_id = callback_query.get("id")
    data = (callback_query.get("data") or "").strip()
    if not callback_query_id or not data.startswith("post:"):
        return None
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    parts = [part.strip() for part in data.split(":")]
    if len(parts) != 2:
        return None
    try:
        preset = get_preset(parts[1])
    except ValueError:
        return None
    return TelegramPostCallback(str(callback_query_id), int(chat_id), preset.name)


def _extract_preset_kit_callback(update: dict[str, Any]) -> TelegramPresetKitCallback | None:
    callback_query = update.get("callback_query") or {}
    callback_query_id = callback_query.get("id")
    data = (callback_query.get("data") or "").strip()
    if not callback_query_id or not data.startswith("kit:"):
        return None
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    parts = [part.strip() for part in data.split(":")]
    if len(parts) != 2:
        return None
    try:
        preset = get_preset(parts[1])
    except ValueError:
        return None
    return TelegramPresetKitCallback(str(callback_query_id), int(chat_id), preset.name)


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


def _extract_menu_callback(update: dict[str, Any]) -> TelegramMenuCallback | None:
    callback_query = update.get("callback_query") or {}
    callback_query_id = callback_query.get("id")
    data = (callback_query.get("data") or "").strip()
    if not callback_query_id or not data.startswith(MENU_CALLBACK_PREFIX):
        return None
    action = data.removeprefix(MENU_CALLBACK_PREFIX).strip().lower()
    if action not in MENU_ACTIONS:
        return None
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    return TelegramMenuCallback(str(callback_query_id), int(chat_id), action)


def _extract_preset_category_callback(update: dict[str, Any]) -> TelegramPresetCategoryCallback | None:
    callback_query = update.get("callback_query") or {}
    callback_query_id = callback_query.get("id")
    data = (callback_query.get("data") or "").strip()
    if not callback_query_id or not data.startswith(PRESET_CATEGORY_CALLBACK_PREFIX):
        return None
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    category_payload = data.removeprefix(PRESET_CATEGORY_CALLBACK_PREFIX).strip().lower()
    category_name, separator, mode = category_payload.partition(":")
    if separator and mode != "draft":
        return None
    callback_mode = mode if separator else "shorts"
    try:
        category = get_preset_category(category_name)
    except ValueError:
        return None
    return TelegramPresetCategoryCallback(str(callback_query_id), int(chat_id), category.name, callback_mode)


def _main_menu_text() -> str:
    return (
        "Market Motion Bot\n"
        "Создает короткие видео по любым тикерам, рынкам и инвестиционным сценариям.\n\n"
        "Открой Mini App, напиши запрос одной строкой или выбери быстрый режим ниже."
    )


def _send_main_menu(client: TelegramClient, chat_id: int) -> None:
    client.send_message(chat_id, _main_menu_text(), reply_markup=main_menu_keyboard())


def format_random_menu() -> str:
    return (
        "Random video\n"
        "Бот сам выбирает тикеры из universe, берет пересечение истории и ставит ролик в очередь.\n\n"
        "Размер: 1, 2 или 3 тикера.\n"
        "Фильтр: mixed, metals, drama, stocks, crypto.\n\n"
        "Команды: random mixed 2, random metals 1, random drama 2."
    )


def format_reference_menu() -> str:
    return (
        "Примеры и материалы\n\n"
        "Здесь не основной сценарий, а ориентиры: проверенные истории, готовые запросы, "
        "посты, музыка и обложки."
    )


def format_quick_launch() -> str:
    return (
        "Свой ролик\n"
        "Напиши тикеры, период, валюту и режим. Бот скачает данные, построит график и пришлет MP4.\n\n"
        "Примеры:\n"
        "/shorts SBER LKOH за год\n"
        "gold silver palladium 2010-2026 RUB capital invest initial=0 monthly=30000 gradient\n"
        "AAPL MSFT NVDA global USD shorts\n\n"
        "Параметры: /params. Подбор без ручного выбора тикеров: random mixed 2."
    )


def _send_quick_launch(client: TelegramClient, chat_id: int) -> None:
    client.send_message(chat_id, format_quick_launch(), reply_markup=quick_launch_keyboard())


def format_mini_app_launch() -> str:
    return (
        "Market Motion Mini App\n\n"
        "Открой форму, собери запрос кнопками и отправь его в бот. "
        "После отправки ролик попадет в очередь генерации."
    )


def _send_mini_app_launch(client: TelegramClient, settings: TelegramBotSettings, chat_id: int) -> None:
    client.send_message(chat_id, format_mini_app_launch(), reply_markup=mini_app_keyboard(settings.mini_app_url))


def parameters_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "✍️ Свой ролик", "callback_data": f"{MENU_CALLBACK_PREFIX}quick_launch"},
                {"text": "🧭 Гайд", "callback_data": f"{MENU_CALLBACK_PREFIX}guide"},
            ],
            [
                {"text": "📚 Примеры", "callback_data": f"{MENU_CALLBACK_PREFIX}reference"},
                {"text": "⏳ Очередь", "callback_data": QUEUE_STATUS_CALLBACK_DATA},
            ],
            [
                {"text": "🏠 Меню", "callback_data": f"{MENU_CALLBACK_PREFIX}main_menu"},
            ],
        ]
    }


def format_parameters_guide() -> str:
    return (
        "Параметры запроса\n\n"
        "Пиши параметры в той же строке после тикеров. Их можно комбинировать.\n\n"
        "Период:\n"
        "from=2010-01-01, to=2026-06-01, 2010-2026, за год, last 3 years.\n\n"
        "Рынок и тикеры:\n"
        "SBER, AAPL global, GC=F futures, BTC crypto, EURUSD currency.\n"
        "ticker|engine|market, engine=stock/global/currency/futures, market=shares/forts/metals/commodities/crypto/selt.\n\n"
        "Видео:\n"
        "duration=12 или 12s (1-90), fps=24 (1-30).\n"
        "shorts = 16s/24fps/gradient, draft = 4s/8fps/line.\n"
        "gradient, nogradient, gradient=true/false, legend=true/false, nolegend.\n\n"
        "Деньги и метрика:\n"
        "RUB/USD/EUR/CNY/GBP/JPY/CHF или currency=USD.\n"
        "close/price/value=CLOSE; capital/reinvest/value=CAPITAL_REINVEST.\n\n"
        "Инвестиции:\n"
        "invest, initial=0, monthly=30000, yearly=100000.\n"
        "Можно по-русски: с нуля ежемесячно 30к₽.\n\n"
        "Вид:\n"
        "theme=default|aurora|studio, title=My_Title.\n\n"
        "Примеры:\n"
        "SBER LKOH from=2020-01-01 to=2024-12-31 duration=12 fps=24 gradient theme=studio\n"
        "gold silver palladium 2010-2026 RUB capital invest initial=0 monthly=30000 shorts\n"
        "AAPL MSFT global USD close 12s nogradient"
    )


def _send_parameters_guide(client: TelegramClient, chat_id: int) -> None:
    client.send_message(chat_id, format_parameters_guide(), reply_markup=parameters_keyboard())


def production_guide_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "✍️ Свой ролик", "callback_data": f"{MENU_CALLBACK_PREFIX}quick_launch"},
                {"text": "🎲 Random", "callback_data": f"{MENU_CALLBACK_PREFIX}random_menu"},
            ],
            [
                {"text": "🧩 Серия", "callback_data": f"{MENU_CALLBACK_PREFIX}content_plan"},
                {"text": "⚙️ Параметры", "callback_data": f"{MENU_CALLBACK_PREFIX}parameters"},
            ],
            [
                {"text": "⏳ Очередь", "callback_data": f"{MENU_CALLBACK_PREFIX}queue"},
                {"text": "📚 Примеры", "callback_data": f"{MENU_CALLBACK_PREFIX}reference"},
            ],
            [
                {"text": "🏠 Меню", "callback_data": f"{MENU_CALLBACK_PREFIX}main_menu"},
            ],
        ]
    }


def format_production_guide() -> str:
    return (
        "Product guide\n\n"
        "Ценность бота - универсальное видео из одной строки, а не список пресетов.\n\n"
        "1. Свой ролик\n"
        "/shorts SBER LKOH за год\n"
        "gold silver palladium 2010-2026 RUB capital invest initial=0 monthly=30000 gradient\n\n"
        "2. Подбор тикеров\n"
        "random mixed 2 - любой рынок\n"
        "random metals 1 - один металл\n"
        "random drama 2 - две волатильные истории\n\n"
        "3. Серия\n"
        "plan drama 5 days 2 tickers - показать сетку\n"
        "plan shorts metals count=1 days=5 - поставить серию в очередь\n\n"
        "4. Контроль\n"
        "/queue или статус - очередь и ошибки.\n\n"
        "Пресеты и примеры остаются как ориентиры, но рабочий путь - свой запрос, random или серия."
    )


def _help_text(default_engine: str, default_market: str) -> str:
    return (
        "Market Motion: как сделать ролик\n"
        f"По умолчанию: {default_engine}|{default_market}\n"
        "\n"
        "Mini App: /app. Свой: /shorts + тикеры + период + валюта + invest/monthly.\n"
        "Random: random mixed 1/2/3, random metals 1, random drama 2.\n"
        "Серия: plan drama 5 days 2 tickers или plan shorts metals count=1 days=5.\n"
        "Статус: /queue или статус.\n\n"
        "Примеры:\n"
        "/shorts SBER LKOH за год\n"
        "золото серебро палладий 2010-2026 RUB капитал с нуля ежемесячно 30к₽ gradient\n"
        "AAPL MSFT NVDA global USD shorts\n\n"
        "Параметры: /params. Подробный процесс: /guide. Меню: /menu."
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


def configure_telegram_command_menu(client: TelegramClient) -> None:
    try:
        client.set_my_commands(telegram_bot_command_menu())
    except TelegramApiError:
        logging.warning("Failed to update Telegram bot command menu.", exc_info=True)


def configure_telegram_mini_app_menu_button(client: TelegramClient, mini_app_url: str, *, enabled: bool = True) -> None:
    menu_button: dict[str, Any]
    if enabled and mini_app_url:
        menu_button = telegram_mini_app_menu_button(mini_app_url)
    else:
        menu_button = telegram_commands_menu_button()
    try:
        client.set_chat_menu_button(menu_button)
    except TelegramApiError:
        logging.warning("Failed to update Telegram Mini App menu button.", exc_info=True)


def _slash_command_and_payload(text: str) -> tuple[str, str] | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    command, _separator, payload = stripped.partition(" ")
    command = command.split("@", 1)[0].lower()
    return command, payload.strip()


def _is_start(text: str) -> bool:
    command = _slash_command_and_payload(text)
    if command is None:
        return False
    return command[0] in {"/start", "/старт"}


def _is_help(text: str) -> bool:
    command = _slash_command_and_payload(text)
    if command is not None:
        return command[0] in {"/help", "/помощь"}
    normalized = text.strip().lower()
    return normalized in {"помощь", "help"}


def _is_quick_launch(text: str) -> bool:
    command = _slash_command_and_payload(text)
    if command is not None:
        return command[0] in {
            "/quick",
            "/shoot",
            "/go",
            "/fast",
            "/launch",
            "/быстро",
            "/быстрый_запуск",
            "/запуск",
        }
    normalized = " ".join(text.strip().lower().replace("ё", "е").split())
    return normalized in {
        "quick",
        "fast",
        "launch",
        "shoot",
        "go",
        "быстро",
        "снять",
        "запустить",
        "запусти съемку",
        "запусти съёмку",
        "быстрый запуск",
        "запуск",
        "снять быстро",
        "быстрый пульт",
    }


def _is_production_guide(text: str) -> bool:
    command = _slash_command_and_payload(text)
    if command is not None:
        return command[0] in {
            "/guide",
            "/workflow",
            "/cheatsheet",
            "/шпаргалка",
            "/инструкция",
            "/гайд",
        }
    normalized = " ".join(text.strip().lower().replace("ё", "е").split())
    return normalized in {
        "guide",
        "workflow",
        "cheatsheet",
        "шпаргалка",
        "инструкция",
        "гайд",
        "как снимать",
        "как делать шортсы",
        "производство",
        "производство шортсов",
        "шпаргалка шортсов",
        "шпаргалка пульса",
    }


def _is_mini_app(text: str) -> bool:
    command = _slash_command_and_payload(text)
    if command is not None:
        return command[0] in {
            "/app",
            "/miniapp",
            "/mini_app",
            "/webapp",
            "/web_app",
            "/приложение",
            "/мини",
        }
    normalized = " ".join(text.strip().lower().replace("ё", "е").split())
    return normalized in {
        "app",
        "miniapp",
        "mini app",
        "webapp",
        "web app",
        "приложение",
        "мини приложение",
        "мини-приложение",
    }


def _is_parameters_guide(text: str) -> bool:
    command = _slash_command_and_payload(text)
    if command is not None:
        return command[0] in {
            "/params",
            "/parameters",
            "/options",
            "/settings",
            "/параметры",
            "/настройки",
        }
    normalized = " ".join(text.strip().lower().replace("ё", "е").split())
    return normalized in {
        "params",
        "parameters",
        "options",
        "settings",
        "параметры",
        "настройки",
        "параметры запроса",
        "как настроить",
    }


def _is_menu(text: str) -> bool:
    command = _slash_command_and_payload(text)
    if command is not None:
        return command[0] in {"/menu", "/меню"}
    normalized = " ".join(text.strip().lower().split())
    return normalized in {"menu", "меню"}


def _shortcut_mode_and_text(text: str) -> tuple[str, str] | None:
    command = _slash_command_and_payload(text)
    if command is None:
        return None
    command_name, payload = command
    if command_name in {"/shorts", "/short", "/reels", "/шортс", "/шортсы", "/шорт"}:
        return "shorts", f"{payload} shorts".strip() if payload else ""
    if command_name in {"/draft", "/preview", "/черновик", "/превью"}:
        return "draft", f"{payload} draft".strip() if payload else ""
    return None


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


def _is_preset_categories(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    if normalized in {
        "/categories",
        "/category",
        "/stories",
        "/истории",
        "/категории",
        "categories",
        "category",
        "stories",
        "истории",
        "категории",
        "по категориям",
        "истории по категориям",
    }:
        return True
    return False


def _preset_category_name(text: str) -> str | None:
    tokens = text.strip().split()
    if len(tokens) < 2:
        return None
    command = tokens[0].lstrip("/").lower()
    if command not in {"category", "cat", "категория", "категории"}:
        return None
    candidate = " ".join(tokens[1:])
    try:
        return get_preset_category(candidate).name
    except ValueError:
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


def _is_music_references(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "/music",
        "/tracks",
        "/музыка",
        "/треки",
        "music",
        "tracks",
        "музыка",
        "треки",
        "музыкальные референсы",
    }


def _is_cover_texts(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "/covers",
        "/cover",
        "/обложки",
        "/обложка",
        "covers",
        "cover",
        "обложки",
        "обложка",
        "тексты обложек",
        "тексты для обложек",
    }


def _is_pulse_pack(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "/pack",
        "/pulse_pack",
        "/pulse-pack",
        "/пакет",
        "pack",
        "pulse pack",
        "pulse-pack",
        "shorts pack",
        "content pack",
        "пакет",
        "пакет пульса",
        "пакет для пульса",
        "пульс пакет",
        "контент пакет",
        "контент-пакет",
        "шортс пакет",
    }


def _is_content_plan(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "/plan",
        "/content_plan",
        "/content-plan",
        "/calendar",
        "/план",
        "/контент_план",
        "/контент-план",
        "plan",
        "calendar",
        "content plan",
        "content-plan",
        "контент план",
        "контент-план",
        "план",
        "план пульса",
        "план для пульса",
        "план публикаций",
        "сетка",
        "сетка пульса",
        "сетка публикаций",
    }


def _is_content_plan_shorts(text: str) -> bool:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    return normalized in {
        "/plan shorts",
        "/content plan shorts",
        "/shoot plan",
        "/снять план",
        "/шортсы плана",
        "plan shorts",
        "content plan shorts",
        "shoot plan",
        "run plan",
        "queue plan",
        "снять план",
        "снять контент план",
        "запусти план",
        "запустить план",
        "выпустить план",
        "план шортсы",
        "план пульса шортсы",
        "контент план шортсы",
        "шортсы плана",
        "шортсы контент плана",
    }


def _is_daily_content_plan_short(text: str) -> bool:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    return normalized in {
        "/today",
        "/daily",
        "/daily short",
        "/daily shorts",
        "/short of day",
        "/shorts of day",
        "/ролик дня",
        "/шортс дня",
        "/сегодня",
        "today",
        "daily",
        "daily short",
        "daily shorts",
        "short of day",
        "shorts of day",
        "ролик дня",
        "шортс дня",
        "шорт дня",
        "шортсы дня",
        "сегодня",
        "снять сегодня",
        "выпуск дня",
        "сценарий дня",
    }


def _is_daily_publication_day(text: str) -> bool:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    return normalized in {
        "/publish day",
        "/publication day",
        "/today publish",
        "/daily publish",
        "/shoot day",
        "/снять день",
        "/день публикации",
        "publish day",
        "publication day",
        "today publish",
        "daily publish",
        "shoot day",
        "снять день",
        "снять публикацию",
        "снять выпуск дня",
        "день публикации",
        "публикационный день",
        "запусти день",
        "запустить день",
        "выпустить день",
    }


def _is_daily_post(text: str) -> bool:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    return normalized in {
        "/today post",
        "/daily post",
        "/day post",
        "/post today",
        "/post day",
        "/пост дня",
        "/текст дня",
        "/текст сегодня",
        "today post",
        "daily post",
        "day post",
        "post today",
        "post day",
        "пост дня",
        "пост сегодня",
        "текст дня",
        "текст сегодня",
        "текст публикации дня",
    }


def _is_weekly_publication_pack(text: str) -> bool:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    return normalized in {
        "/publish week",
        "/publication week",
        "/weekly publish",
        "/week pack",
        "/shoot week",
        "/снять неделю",
        "/неделя публикаций",
        "publish week",
        "publication week",
        "weekly publish",
        "week pack",
        "shoot week",
        "снять неделю",
        "снять недельный план",
        "снять неделю публикаций",
        "неделя публикаций",
        "недельный выпуск",
        "недельный пакет",
        "запусти неделю",
        "запустить неделю",
        "выпустить неделю",
    }


def _is_weekly_posts(text: str) -> bool:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    return normalized in {
        "/week posts",
        "/weekly posts",
        "/posts week",
        "/posts weekly",
        "/посты недели",
        "/тексты недели",
        "week posts",
        "weekly posts",
        "posts week",
        "posts weekly",
        "посты недели",
        "недельные посты",
        "тексты недели",
        "недельные тексты",
        "посты контент плана",
        "тексты контент плана",
    }


def _is_daily_content_kit(text: str) -> bool:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    return normalized in {
        "/today kit",
        "/daily kit",
        "/day kit",
        "/today pack",
        "/kit today",
        "/пакет дня",
        "/пакет сегодня",
        "today kit",
        "daily kit",
        "day kit",
        "today pack",
        "kit today",
        "daily content kit",
        "пакет дня",
        "пакет сегодня",
        "сегодня пакет",
        "контент дня",
        "контент пакет дня",
        "публикация дня",
        "сценарий дня пакет",
    }


def _preset_kit_name(text: str) -> str | None:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    for prefix in sorted(PRESET_KIT_PREFIXES, key=len, reverse=True):
        if not normalized.startswith(f"{prefix} "):
            continue
        candidate = normalized.removeprefix(prefix).strip()
        if not candidate:
            return None
        try:
            return get_preset(candidate).name
        except ValueError:
            return None
    return None


def _is_preset_kits(text: str) -> bool:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    return normalized in {
        "/kits",
        "/kit list",
        "/preset kits",
        "/content kits",
        "/пакеты",
        "/пакеты сценариев",
        "kits",
        "kit list",
        "preset kits",
        "content kits",
        "пакеты",
        "пакеты сценариев",
        "публикационные пакеты",
        "контент пакеты",
    }


def _is_pulse_posts(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return normalized in {
        "/posts",
        "/post_list",
        "/copy_posts",
        "/посты",
        "/тексты",
        "posts",
        "post list",
        "copy posts",
        "посты",
        "тексты",
        "тексты для пульса",
        "пакеты для пульса",
    }


def _preset_post_name(text: str) -> str | None:
    tokens = text.strip().split()
    if not tokens:
        return None
    command = tokens[0].lstrip("/").lower()
    if command not in {"post", "copy", "pulse", "text", "пост", "текст", "пульс"}:
        return None
    return " ".join(tokens[1:]).strip()


def _send_pulse_post(client: TelegramClient, settings: TelegramBotSettings, chat_id: int, post_request: str) -> None:
    if not post_request:
        client.send_message(chat_id, "Напиши название сценария или запрос, например: пост металлы")
        return
    try:
        parsed = parse_telegram_video_request(post_request, settings.render, settings.default_engine, settings.default_market)
    except ValueError as exc:
        client.send_message(chat_id, f"Не смог разобрать запрос для текста Пульса: {exc}")
        return
    if parsed.preset_name:
        preset = get_preset(parsed.preset_name)
        client.send_message(chat_id, format_pulse_post(preset))
    else:
        client.send_message(chat_id, format_generic_pulse_post(parsed))


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


def _hot_batch_mode_and_theme(text: str) -> tuple[str, str | None] | None:
    normalized = " ".join(text.strip().lower().replace("ё", "е").split())
    if normalized in HOT_DRAFT_BATCH_ALIASES:
        return ("draft", None)
    if normalized in HOT_SHORTS_BATCH_ALIASES:
        return ("shorts", None)
    for alias in HOT_SHORTS_BATCH_ALIASES:
        for theme_alias, theme in HOT_BATCH_THEME_ALIASES.items():
            if normalized in {
                f"{alias} {theme_alias}",
                f"{theme_alias} {alias}",
                f"{alias}_{theme_alias}",
                f"{alias}-{theme_alias}",
            }:
                return ("shorts", theme)
    return None


def _preset_theme_variants_name(text: str) -> str | None:
    normalized = " ".join(text.strip().lower().replace("ё", "е").split())
    for prefix in sorted(PRESET_THEME_VARIANT_PREFIXES, key=len, reverse=True):
        if not normalized.startswith(f"{prefix} "):
            continue
        candidate = normalized.removeprefix(prefix).strip()
        if not candidate:
            return None
        try:
            return get_preset(candidate).name
        except ValueError:
            return None
    return None


def _is_hot_draft_batch(text: str) -> bool:
    return _hot_batch_mode_and_theme(text) == ("draft", None)


def _is_hot_shorts_batch(text: str) -> bool:
    return _hot_batch_mode_and_theme(text) == ("shorts", None)


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


def _shorts_batch_theme(text: str) -> tuple[bool, str | None]:
    normalized = " ".join(text.strip().lower().replace("_", " ").replace("-", " ").split())
    if normalized in SHORTS_BATCH_ALIASES:
        return (True, None)
    for alias in SHORTS_BATCH_ALIASES:
        for theme_alias, theme in HOT_BATCH_THEME_ALIASES.items():
            if normalized in {
                f"{alias} {theme_alias}",
                f"{theme_alias} {alias}",
            }:
                return (True, theme)
    return (False, None)


def _is_shorts_batch(text: str) -> bool:
    return _shorts_batch_theme(text)[0]


def _is_random_shorts(text: str) -> bool:
    normalized = " ".join(text.strip().lower().replace("_", " ").replace("-", " ").split())
    random_action = _random_content_action(text)
    if random_action is not None:
        return random_action.mode == "shorts" and random_action.category_name is None
    return normalized in {
        "/random shorts",
        "/random short",
        "/случайный шортс",
        "/случайный шорт",
        "random shorts",
        "random short",
        "shorts random",
        "short random",
        "случайный шортс",
        "случайный шорт",
        "шортс случайный",
        "шорт случайный",
        "случайный ролик",
        "случайное видео",
    }


def _is_random_draft(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    random_action = _random_content_action(text)
    if random_action is not None:
        return random_action.mode == "draft" and random_action.category_name is None
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


_RANDOM_WORDS = {"random", "случайный", "случайная", "случайное", "случайные"}
_RANDOM_SHORT_WORDS = {"short", "shorts", "reels", "ролик", "ролики", "шорт", "шортс", "шортсы", "видео"}
_RANDOM_DRAFT_WORDS = {"draft", "drafts", "preview", "черновик", "черновики", "превью"}
_RANDOM_MIX_WORDS = {"mix", "mixed", "all", "any", "микс", "смешанный", "смешанные", "разные", "любой", "любые"}
_RANDOM_COUNT_WORDS = {
    "1": 1,
    "one": 1,
    "один": 1,
    "одна": 1,
    "одно": 1,
    "2": 2,
    "two": 2,
    "два": 2,
    "две": 2,
    "3": 3,
    "three": 3,
    "три": 3,
}
_PLAN_WORDS = {"plan", "calendar", "план", "сетка"}
_PLAN_IGNORED_WORDS = {"content", "контент", "пульс", "pulse", "category", "категория", "из"}
_PLAN_SHORTS_WORDS = {
    "short",
    "shorts",
    "reels",
    "shoot",
    "run",
    "queue",
    "ролик",
    "ролики",
    "шорт",
    "шортс",
    "шортсы",
    "снять",
    "запустить",
    "запусти",
    "выпустить",
}
_PLAN_DAYS_KEYS = {"days", "day", "d", "items", "выпуски", "выпусков", "дни", "дней", "день", "дня"}
_PLAN_COUNT_KEYS = {"count", "tickers", "ticker", "assets", "тикеры", "тикеров", "тикера", "тикер", "активы", "актива"}
_PLAN_CATEGORY_KEYS = {"category", "categories", "cat", "type", "категория", "категории", "тип"}
_PLAN_MIXED_CATEGORY_WORDS = {"mixed", "mix", "all", "any", "микс", "смешанные", "разные", "любой", "любые"}


def _parse_plan_positive_int(value: str, minimum: int, maximum: int) -> int | None:
    if not value.isdigit():
        return None
    return max(minimum, min(maximum, int(value)))


def _append_plan_category(categories: list[str | None], raw_category: str) -> None:
    if not raw_category:
        return
    normalized_category = resolve_universe_category(raw_category)
    normalized_raw = raw_category.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized_category is None and normalized_raw not in _PLAN_MIXED_CATEGORY_WORDS:
        return
    if normalized_category not in categories:
        categories.append(normalized_category)


def _content_plan_action(text: str) -> TelegramContentPlanAction | None:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    tokens = [token.lstrip("/") for token in normalized.split()]
    if not tokens or not any(token in _PLAN_WORDS for token in tokens):
        return None

    mode = "shorts" if any(token in _PLAN_SHORTS_WORDS for token in tokens) else "view"
    days = 7
    count: int | None = None
    categories: list[str | None] = []
    free_category_tokens: list[str] = []

    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token in _PLAN_WORDS | _PLAN_IGNORED_WORDS | _PLAN_SHORTS_WORDS:
            idx += 1
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in _PLAN_DAYS_KEYS:
                parsed_days = _parse_plan_positive_int(value, 1, 14)
                if parsed_days is not None:
                    days = parsed_days
            elif key in _PLAN_COUNT_KEYS:
                count = _parse_plan_positive_int(value, 1, 3)
            elif key in _PLAN_CATEGORY_KEYS:
                _append_plan_category(categories, value)
            elif key == "mode" and value in {"shorts", "short", "shoot", "run"}:
                mode = "shorts"
            idx += 1
            continue
        if token.isdigit():
            parsed_number = int(token)
            next_token = tokens[idx + 1] if idx + 1 < len(tokens) else ""
            if next_token in _PLAN_DAYS_KEYS:
                days = max(1, min(14, parsed_number))
                idx += 2
                continue
            if next_token in _PLAN_COUNT_KEYS:
                count = max(1, min(3, parsed_number))
                idx += 2
                continue
            if parsed_number <= 3 and count is None:
                count = parsed_number
            elif parsed_number > 3:
                days = min(14, parsed_number)
            idx += 1
            continue
        if token not in _PLAN_DAYS_KEYS | _PLAN_COUNT_KEYS | _PLAN_CATEGORY_KEYS:
            free_category_tokens.append(token)
        idx += 1

    for token in free_category_tokens:
        _append_plan_category(categories, token)
    if free_category_tokens:
        _append_plan_category(categories, " ".join(free_category_tokens))

    return TelegramContentPlanAction(mode=mode, days=days, count=count, categories=tuple(categories))


def _random_content_action(text: str) -> TelegramRandomContentAction | None:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    for explicit_prefix in ("category ", "категория "):
        if normalized.startswith(explicit_prefix):
            normalized = normalized.removeprefix(explicit_prefix).strip()
            break
    normalized, theme = _strip_category_action_theme(normalized)
    tokens = [token.lstrip("/") for token in normalized.split()]
    if not tokens or not any(token in _RANDOM_WORDS for token in tokens):
        return None

    explicit_draft = any(token in _RANDOM_DRAFT_WORDS for token in tokens)
    explicit_short = any(token in _RANDOM_SHORT_WORDS for token in tokens)
    count = next((_RANDOM_COUNT_WORDS[token] for token in tokens if token in _RANDOM_COUNT_WORDS), None)
    mixed = any(token in _RANDOM_MIX_WORDS for token in tokens)
    category_tokens = [
        token
        for token in tokens
        if token
        and token not in _RANDOM_WORDS
        and token not in _RANDOM_SHORT_WORDS
        and token not in _RANDOM_DRAFT_WORDS
        and token not in _RANDOM_MIX_WORDS
        and token not in _RANDOM_COUNT_WORDS
    ]
    category_name: str | None = None
    if category_tokens and not mixed:
        category_name = resolve_universe_category(" ".join(category_tokens))

    if explicit_draft:
        mode = "draft"
    elif explicit_short or category_name is not None or mixed or count is not None:
        mode = "shorts"
    else:
        return None
    return TelegramRandomContentAction(mode=mode, category_name=category_name, count=count, theme=theme)


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


def _strip_category_action_theme(normalized: str) -> tuple[str, str | None]:
    for theme_alias, theme in HOT_BATCH_THEME_ALIASES.items():
        if normalized.startswith(f"{theme_alias} "):
            return normalized.removeprefix(f"{theme_alias} ").strip(), theme
        if normalized.endswith(f" {theme_alias}"):
            return normalized.removesuffix(f" {theme_alias}").strip(), theme
    return normalized, None


def _match_category_action_prefix(normalized: str, prefixes: set[str]) -> str | None:
    for prefix in sorted(prefixes, key=len, reverse=True):
        candidates: list[str] = []
        if normalized.startswith(f"{prefix} "):
            candidates.append(normalized.removeprefix(f"{prefix} ").strip())
        if normalized.endswith(f" {prefix}"):
            candidates.append(normalized.removesuffix(f" {prefix}").strip())
        for candidate in candidates:
            candidate = candidate.lstrip("/").strip()
            if not candidate:
                continue
            try:
                category = get_preset_category(candidate)
            except ValueError:
                continue
            candidate_key = candidate.lower().replace(" ", "").replace("_", "").replace("-", "")
            try:
                get_preset(candidate)
            except ValueError:
                return category.name
            if candidate_key == category.name:
                return category.name
    return None


def _category_preset_action(text: str) -> TelegramCategoryPresetAction | None:
    normalized = " ".join(text.strip().lower().replace("ё", "е").replace("_", " ").replace("-", " ").split())
    for explicit_prefix in ("category ", "категория "):
        if normalized.startswith(explicit_prefix):
            normalized = normalized.removeprefix(explicit_prefix).strip()
            break
    normalized, theme = _strip_category_action_theme(normalized)
    random_draft = _match_category_action_prefix(normalized, CATEGORY_RANDOM_DRAFT_PREFIXES)
    if random_draft is not None:
        return TelegramCategoryPresetAction("random", "draft", random_draft)
    random_shorts = _match_category_action_prefix(normalized, CATEGORY_RANDOM_SHORTS_PREFIXES)
    if random_shorts is not None:
        return TelegramCategoryPresetAction("random", "shorts", random_shorts, theme=theme)
    batch_draft = _match_category_action_prefix(normalized, CATEGORY_BATCH_DRAFT_PREFIXES)
    if batch_draft is not None:
        return TelegramCategoryPresetAction("batch", "draft", batch_draft)
    batch_shorts = _match_category_action_prefix(normalized, CATEGORY_BATCH_SHORTS_PREFIXES)
    if batch_shorts is not None:
        return TelegramCategoryPresetAction("batch", "shorts", batch_shorts, theme=theme)
    return None


def _clean_batch_request_line(line: str) -> str:
    line = line.strip()
    while line[:1] in {"-", "–", "—", "*", "•"}:
        line = line[1:].strip()
    while line:
        matched_number = False
        for separator in (".", ")"):
            prefix, found, rest = line.partition(separator)
            if found and prefix.isdigit():
                line = rest.strip()
                matched_number = True
                break
        if not matched_number:
            break
    return line


def _batch_request_lines(text: str) -> list[str]:
    lines = [_clean_batch_request_line(line) for line in text.splitlines()]
    return [line for line in lines if line]


def _format_amount(value: int, currency: str) -> str:
    return f"{value:,}".replace(",", " ") + f" {currency}"


def _metric_label(value_col: str) -> str:
    if value_col.upper() == "CLOSE":
        return "цена закрытия"
    return "капитал с реинвестированием"


def _render_summary(render: RenderSettings) -> str:
    parts = [
        f"Тема: {render.theme}",
        f"Метрика: {_metric_label(render.value_col)}",
        f"Валюта: {render.currency}",
        f"Градиент: {'да' if render.use_gradient else 'нет'}",
    ]
    if render.with_investments:
        investment_parts: list[str] = []
        if render.initial_investment:
            investment_parts.append(f"старт {_format_amount(render.initial_investment, render.currency)}")
        if render.monthly_investment:
            investment_parts.append(f"ежемесячно {_format_amount(render.monthly_investment, render.currency)}")
        if render.yearly_investment:
            investment_parts.append(f"ежегодно {_format_amount(render.yearly_investment, render.currency)}")
        parts.append(f"Инвестиции: {', '.join(investment_parts) if investment_parts else 'включены'}")
    return ". ".join(parts) + "."


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


def _custom_cover_texts(parsed: ParsedTelegramRequest) -> tuple[str, ...]:
    render = parsed.request.render
    if render.with_investments and render.monthly_investment:
        return (
            f"{_format_amount(render.monthly_investment, render.currency)}/мес: кто выиграл?",
            f"{parsed.display_name}: регулярные покупки",
            "Что показал долгий DCA?",
        )
    if len(parsed.request.ticker_specs) == 1:
        return (
            f"{parsed.display_name}: график без лишних слов",
            "Возможность или ловушка?",
            f"{render.start_date:%Y} - {render.end_date:%Y}",
        )
    return (
        f"{parsed.display_name}: кто сильнее?",
        "Сравнение без эмоций",
        "Где была главная драма?",
    )


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


def _start_render_progress_notifier(
    client: TelegramClient,
    chat_id: int,
    job_id: str | None,
    display_name: str,
    first_notice_seconds: float = RENDER_PROGRESS_FIRST_NOTICE_SECONDS,
    repeat_seconds: float = RENDER_PROGRESS_REPEAT_SECONDS,
) -> Callable[[], None]:
    stop_event = Event()
    job_label = job_id or "manual"

    def notify_loop() -> None:
        if stop_event.wait(max(first_notice_seconds, 0.0)):
            return
        notice_count = 1
        while not stop_event.is_set():
            try:
                client.send_message(
                    chat_id,
                    f"Рендер еще идет: {display_name}\n"
                    f"Job {job_label}. Длинные периоды и 3+ тикера могут считаться несколько минут.",
                    reply_markup=queue_status_keyboard(),
                )
                log_event("render", "progress", job_id=job_id, chat_id=chat_id, notice_count=notice_count)
            except Exception:
                logging.exception("Failed to send render progress notice for %s", job_label)
            notice_count += 1
            if stop_event.wait(max(repeat_seconds, 1.0)):
                return

    thread = Thread(target=notify_loop, name=f"telegram-render-progress-{job_label}", daemon=True)
    thread.start()

    def stop() -> None:
        stop_event.set()
        thread.join(timeout=1.0)

    return stop


def format_generic_pulse_post(parsed: ParsedTelegramRequest) -> str:
    render = parsed.request.render
    period = f"{render.start_date:%d.%m.%Y} - {render.end_date:%d.%m.%Y}"
    story_label = _custom_story_label(parsed)
    details = f"Параметры: {period}, {render.currency}, {_metric_label(render.value_col)}."
    lines = [
        "Пост для Пульса (можно копировать):",
        _custom_pulse_hook(parsed),
        "",
        f"На видео {story_label}: {parsed.display_name}. "
        "Это не прогноз, а повод обсудить, где ожидания совпали с графиком, а где картинка оказалась неожиданной.",
    ]
    if render.with_investments:
        parts = [f"старт {_format_amount(render.initial_investment, render.currency)}"]
        if render.monthly_investment:
            parts.append(f"ежемесячно {_format_amount(render.monthly_investment, render.currency)}")
        if render.yearly_investment:
            parts.append(f"ежегодно {_format_amount(render.yearly_investment, render.currency)}")
        details += f" Инвестиции: {', '.join(parts)}."
    lines.extend(
        [
            _custom_pulse_question(parsed),
            "",
            _market_tags(parsed),
            "",
            "Не инвестиционная рекомендация.",
            "",
            "Обложка:",
            *[f"- {cover}" for cover in _custom_cover_texts(parsed)],
            "",
            "Монтаж:",
            f"- Настроение: {_custom_music_mood(parsed)}.",
            f"- {details}",
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
    if _is_start(text):
        _send_main_menu(client, chat_id)
        return
    if _is_help(text):
        client.send_message(chat_id, _help_text(settings.default_engine, settings.default_market), reply_markup=help_keyboard())
        return
    if _is_mini_app(text):
        _send_mini_app_launch(client, settings, chat_id)
        return
    if _is_quick_launch(text):
        _send_quick_launch(client, chat_id)
        return
    if _is_parameters_guide(text):
        _send_parameters_guide(client, chat_id)
        return
    if _is_production_guide(text):
        client.send_message(chat_id, format_production_guide(), reply_markup=production_guide_keyboard())
        return
    if _is_menu(text):
        _send_main_menu(client, chat_id)
        return
    shortcut = _shortcut_mode_and_text(text)
    if shortcut is not None:
        mode, shortcut_text = shortcut
        if not shortcut_text:
            client.send_message(
                chat_id,
                format_preset_category_list(mode),
                reply_markup=preset_category_inline_keyboard(mode=mode),
            )
            return
        text = shortcut_text
    if _is_draft_batch(text):
        client.send_message(chat_id, "Команда пакетных черновиков работает в режиме Telegram-очереди.")
        return
    shorts_batch = _shorts_batch_theme(text)
    if shorts_batch[0]:
        theme_label = f" в теме {shorts_batch[1]}" if shorts_batch[1] else ""
        client.send_message(chat_id, f"Команда полного пакета shorts-роликов{theme_label} работает в режиме Telegram-очереди.")
        return
    hot_batch = _hot_batch_mode_and_theme(text)
    if hot_batch is not None:
        mode, theme = hot_batch
        mode_label = "top-draft черновиков" if mode == "draft" else "top-shorts роликов"
        theme_label = f" в теме {theme}" if theme else ""
        client.send_message(chat_id, f"Команда {mode_label}{theme_label} работает в режиме Telegram-очереди.")
        return
    random_content_action = _random_content_action(text)
    if random_content_action is not None:
        category_label = ""
        if random_content_action.category_name:
            category_label = f" категории {universe_category_label(random_content_action.category_name)}"
        count_label = f" из {random_content_action.count} тикер(ов)" if random_content_action.count else ""
        mode_label = "черновика" if random_content_action.mode == "draft" else "shorts-ролика"
        client.send_message(chat_id, f"Команда случайного {mode_label}{category_label}{count_label} работает в режиме Telegram-очереди.")
        return
    if _is_random_shorts(text):
        client.send_message(chat_id, "Команда случайного shorts-ролика работает в режиме Telegram-очереди.")
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
    if _is_preset_categories(text):
        client.send_message(chat_id, format_preset_category_list(), reply_markup=preset_category_inline_keyboard())
        return
    preset_category_name = _preset_category_name(text)
    if preset_category_name is not None:
        client.send_message(
            chat_id,
            format_preset_category(preset_category_name),
            reply_markup=preset_category_keyboard(preset_category_name),
        )
        return
    if _is_examples(text):
        client.send_message(chat_id, format_example_list(), reply_markup=example_inline_keyboard())
        return
    if _is_music_references(text):
        client.send_message(chat_id, format_music_list())
        return
    if _is_cover_texts(text):
        client.send_message(chat_id, format_cover_list())
        return
    content_plan_action = _content_plan_action(text)
    if content_plan_action is not None:
        if content_plan_action.mode == "shorts":
            client.send_message(chat_id, "Команда запуска контент-плана работает в режиме Telegram-очереди.")
            return
        client.send_message(chat_id, _format_content_plan_action(content_plan_action), reply_markup=content_plan_keyboard())
        return
    if _is_content_plan_shorts(text):
        client.send_message(chat_id, "Команда запуска контент-плана работает в режиме Telegram-очереди.")
        return
    if _is_weekly_publication_pack(text):
        client.send_message(chat_id, "Команда недельного выпуска работает в режиме Telegram-очереди.")
        return
    if _is_weekly_posts(text):
        send_weekly_posts(client, chat_id)
        return
    if _is_daily_publication_day(text):
        client.send_message(chat_id, "Команда публикационного дня работает в режиме Telegram-очереди.")
        return
    if _is_daily_post(text):
        client.send_message(chat_id, format_daily_post(), reply_markup=daily_post_keyboard())
        return
    if _is_daily_content_plan_short(text):
        client.send_message(chat_id, "Команда шортса дня работает в режиме Telegram-очереди.")
        return
    if _is_daily_content_kit(text):
        client.send_message(chat_id, format_daily_content_kit(), reply_markup=daily_content_kit_keyboard())
        return
    if _is_content_plan(text):
        client.send_message(chat_id, format_content_plan(), reply_markup=content_plan_keyboard())
        return
    category_action = _category_preset_action(text)
    if category_action is not None:
        category = get_preset_category(category_action.category_name)
        action_label = "случайного" if category_action.kind == "random" else "пакета"
        mode_label = "черновика" if category_action.mode == "draft" else "shorts-роликов"
        client.send_message(
            chat_id,
            f"Команда {action_label} {mode_label} категории {category.title} работает в режиме Telegram-очереди.",
        )
        return
    if _is_preset_kits(text):
        client.send_message(chat_id, format_preset_kit_list(), reply_markup=preset_kit_inline_keyboard())
        return
    preset_kit_name = _preset_kit_name(text)
    if preset_kit_name is not None:
        client.send_message(
            chat_id,
            format_preset_kit(preset_kit_name),
            reply_markup=preset_kit_keyboard(preset_kit_name),
        )
        return
    if _is_pulse_pack(text):
        client.send_message(chat_id, format_pulse_pack(), reply_markup=pulse_pack_keyboard())
        return
    if _is_pulse_posts(text):
        client.send_message(chat_id, format_post_list(), reply_markup=post_inline_keyboard())
        return
    preset_post_name = _preset_post_name(text)
    if preset_post_name is not None:
        _send_pulse_post(client, settings, chat_id, preset_post_name)
        return
    if len(_batch_request_lines(text)) > 1:
        client.send_message(chat_id, "Несколько запросов одним сообщением работают в режиме Telegram-очереди.")
        return
    preset_list_mode = _preset_list_mode(text)
    if preset_list_mode is not None:
        if preset_list_mode == "draft":
            client.send_message(
                chat_id,
                format_preset_category_list("draft"),
                reply_markup=preset_category_inline_keyboard(mode="draft"),
            )
            return
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
        f"{render.start_date} - {render.end_date}, {render.duration}s/{render.fps}fps\n"
        f"{_render_summary(render)}",
    )
    stop_progress_notifier = _start_render_progress_notifier(client, chat_id, job_id, parsed.display_name)
    try:
        output_path = generate_video(parsed.request, job_id=job_id)
    finally:
        stop_progress_notifier()
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
    if settings.cleanup_retention_days <= 0:
        try:
            output_path.unlink(missing_ok=True)
            log_event("cleanup", "completed", job_id=job_id, removed_count=1, retention_days=0)
        except OSError as exc:
            logging.warning("Failed to delete sent output %s: %s", output_path, exc)
    else:
        removed = cleanup_old_outputs(render.output_dir, settings.cleanup_retention_days, keep={output_path})
        if removed:
            log_event("cleanup", "completed", job_id=job_id, removed_count=len(removed), retention_days=settings.cleanup_retention_days)


def run_telegram_bot(settings: TelegramBotSettings) -> None:
    client = TelegramClient(settings.token, settings.poll_timeout)
    configure_telegram_command_menu(client)
    configure_telegram_mini_app_menu_button(
        client,
        settings.mini_app_url,
        enabled=settings.mini_app_menu_button,
    )
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
                        elif _is_start(text):
                            _send_main_menu(client, chat_id)
                        elif _is_help(text):
                            client.send_message(
                                chat_id,
                                _help_text(settings.default_engine, settings.default_market),
                                reply_markup=help_keyboard(),
                            )
                        elif _is_mini_app(text):
                            _send_mini_app_launch(client, settings, chat_id)
                        elif _is_quick_launch(text):
                            _send_quick_launch(client, chat_id)
                        elif _is_parameters_guide(text):
                            _send_parameters_guide(client, chat_id)
                        elif _is_production_guide(text):
                            client.send_message(
                                chat_id,
                                format_production_guide(),
                                reply_markup=production_guide_keyboard(),
                            )
                        elif _is_menu(text):
                            _send_main_menu(client, chat_id)
                        else:
                            shortcut = _shortcut_mode_and_text(text)
                            if shortcut is not None:
                                shortcut_mode, shortcut_text = shortcut
                                if not shortcut_text:
                                    client.send_message(
                                        chat_id,
                                        format_preset_category_list(shortcut_mode),
                                        reply_markup=preset_category_inline_keyboard(mode=shortcut_mode),
                                    )
                                    continue
                                text = shortcut_text
                            hot_batch = _hot_batch_mode_and_theme(text)
                            shorts_batch = _shorts_batch_theme(text)
                            content_plan_action = _content_plan_action(text)
                            random_content_action = _random_content_action(text)
                            category_action = _category_preset_action(text)
                            preset_theme_variants_name = _preset_theme_variants_name(text)
                            preset_kit_name = _preset_kit_name(text)
                            preset_category_name = _preset_category_name(text)
                            if _is_weekly_publication_pack(text):
                                job_queue.enqueue_weekly_publication_pack(chat_id, int(update["update_id"]))
                            elif _is_weekly_posts(text):
                                send_weekly_posts(client, chat_id)
                            elif _is_daily_publication_day(text):
                                job_queue.enqueue_daily_publication_day(chat_id, int(update["update_id"]))
                            elif _is_daily_post(text):
                                client.send_message(
                                    chat_id,
                                    format_daily_post(),
                                    reply_markup=daily_post_keyboard(),
                                )
                            elif _is_daily_content_kit(text):
                                client.send_message(
                                    chat_id,
                                    format_daily_content_kit(),
                                    reply_markup=daily_content_kit_keyboard(),
                                )
                            elif _is_draft_batch(text):
                                job_queue.enqueue_preset_drafts(chat_id, int(update["update_id"]))
                            elif _is_daily_content_plan_short(text):
                                job_queue.enqueue_daily_content_plan_short(chat_id, int(update["update_id"]))
                            elif content_plan_action is not None:
                                if content_plan_action.mode == "shorts":
                                    job_queue.enqueue_content_plan_shorts(
                                        chat_id,
                                        int(update["update_id"]),
                                        days=content_plan_action.days,
                                        count=content_plan_action.count,
                                        categories=content_plan_action.categories,
                                    )
                                else:
                                    client.send_message(
                                        chat_id,
                                        _format_content_plan_action(content_plan_action),
                                        reply_markup=content_plan_keyboard(),
                                    )
                            elif _is_content_plan_shorts(text):
                                job_queue.enqueue_content_plan_shorts(chat_id, int(update["update_id"]))
                            elif shorts_batch[0]:
                                job_queue.enqueue_preset_shorts(chat_id, int(update["update_id"]), theme=shorts_batch[1])
                            elif hot_batch is not None:
                                mode, theme = hot_batch
                                if mode == "draft":
                                    job_queue.enqueue_hot_preset_drafts(chat_id, int(update["update_id"]))
                                elif theme:
                                    job_queue.enqueue_hot_preset_shorts_with_theme(chat_id, int(update["update_id"]), theme)
                                else:
                                    job_queue.enqueue_hot_preset_shorts(chat_id, int(update["update_id"]))
                            elif random_content_action is not None:
                                if random_content_action.mode == "draft":
                                    job_queue.enqueue_random_universe_draft(
                                        chat_id,
                                        int(update["update_id"]),
                                        category_name=random_content_action.category_name,
                                        count=random_content_action.count,
                                    )
                                else:
                                    job_queue.enqueue_random_universe_shorts(
                                        chat_id,
                                        int(update["update_id"]),
                                        category_name=random_content_action.category_name,
                                        count=random_content_action.count,
                                        theme=random_content_action.theme,
                                    )
                            elif category_action is not None:
                                if category_action.kind == "random" and category_action.mode == "draft":
                                    job_queue.enqueue_random_category_universe_draft(
                                        chat_id,
                                        int(update["update_id"]),
                                        category_action.category_name,
                                    )
                                elif category_action.kind == "random":
                                    job_queue.enqueue_random_category_universe_shorts(
                                        chat_id,
                                        int(update["update_id"]),
                                        category_action.category_name,
                                        theme=category_action.theme,
                                    )
                                elif category_action.mode == "draft":
                                    job_queue.enqueue_category_preset_drafts(
                                        chat_id,
                                        int(update["update_id"]),
                                        category_action.category_name,
                                    )
                                else:
                                    job_queue.enqueue_category_preset_shorts(
                                        chat_id,
                                        int(update["update_id"]),
                                        category_action.category_name,
                                        theme=category_action.theme,
                                    )
                            elif preset_theme_variants_name is not None:
                                job_queue.enqueue_preset_theme_variants(
                                    chat_id,
                                    int(update["update_id"]),
                                    preset_theme_variants_name,
                                )
                            elif _is_random_shorts(text):
                                job_queue.enqueue_random_universe_shorts(chat_id, int(update["update_id"]))
                            elif _is_random_draft(text):
                                job_queue.enqueue_random_universe_draft(chat_id, int(update["update_id"]))
                            elif _is_example_draft_batch(text):
                                job_queue.enqueue_example_drafts(chat_id, int(update["update_id"]))
                            elif _is_random_example_draft(text):
                                job_queue.enqueue_random_example_draft(chat_id, int(update["update_id"]))
                            elif _is_queue_status(text):
                                client.send_message(chat_id, job_queue.status_text(), reply_markup=queue_status_keyboard())
                            elif _is_preset_categories(text):
                                client.send_message(
                                    chat_id,
                                    format_preset_category_list(),
                                    reply_markup=preset_category_inline_keyboard(),
                                )
                            elif preset_category_name is not None:
                                client.send_message(
                                    chat_id,
                                    format_preset_category(preset_category_name),
                                    reply_markup=preset_category_keyboard(preset_category_name),
                                )
                            elif _is_examples(text):
                                client.send_message(chat_id, format_example_list(), reply_markup=example_inline_keyboard())
                            elif _is_music_references(text):
                                client.send_message(chat_id, format_music_list())
                            elif _is_cover_texts(text):
                                client.send_message(chat_id, format_cover_list())
                            elif _is_content_plan(text):
                                client.send_message(
                                    chat_id,
                                    format_content_plan(),
                                    reply_markup=content_plan_keyboard(),
                                )
                            elif _is_preset_kits(text):
                                client.send_message(
                                    chat_id,
                                    format_preset_kit_list(),
                                    reply_markup=preset_kit_inline_keyboard(),
                                )
                            elif preset_kit_name is not None:
                                client.send_message(
                                    chat_id,
                                    format_preset_kit(preset_kit_name),
                                    reply_markup=preset_kit_keyboard(preset_kit_name),
                                )
                            elif _is_pulse_pack(text):
                                client.send_message(chat_id, format_pulse_pack(), reply_markup=pulse_pack_keyboard())
                            elif _is_pulse_posts(text):
                                client.send_message(chat_id, format_post_list(), reply_markup=post_inline_keyboard())
                            else:
                                preset_post_name = _preset_post_name(text)
                                if preset_post_name is not None:
                                    _send_pulse_post(client, settings, chat_id, preset_post_name)
                                    continue
                                preset_list_mode = _preset_list_mode(text)
                                if preset_list_mode is not None:
                                    if preset_list_mode == "draft":
                                        client.send_message(
                                            chat_id,
                                            format_preset_category_list("draft"),
                                            reply_markup=preset_category_inline_keyboard(mode="draft"),
                                        )
                                        continue
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
                    menu_callback = _extract_menu_callback(update)
                    if menu_callback is not None:
                        if settings.allowed_chat_ids and menu_callback.chat_id not in settings.allowed_chat_ids:
                            client.answer_callback_query(menu_callback.callback_query_id, "This chat is not allowed.")
                            client.send_message(menu_callback.chat_id, "This chat is not allowed to use this bot.")
                        elif menu_callback.action == "main_menu":
                            client.answer_callback_query(menu_callback.callback_query_id, "Меню открыто.")
                            _send_main_menu(client, menu_callback.chat_id)
                        elif menu_callback.action == "mini_app":
                            client.answer_callback_query(menu_callback.callback_query_id, "Mini App открыт.")
                            _send_mini_app_launch(client, settings, menu_callback.chat_id)
                        elif menu_callback.action == "quick_launch":
                            client.answer_callback_query(menu_callback.callback_query_id, "Быстрый запуск открыт.")
                            _send_quick_launch(client, menu_callback.chat_id)
                        elif menu_callback.action == "reference":
                            client.answer_callback_query(menu_callback.callback_query_id, "Справочник открыт.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_reference_menu(),
                                reply_markup=reference_keyboard(),
                            )
                        elif menu_callback.action == "random_menu":
                            client.answer_callback_query(menu_callback.callback_query_id, "Random открыт.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_random_menu(),
                                reply_markup=random_menu_keyboard(),
                            )
                        elif menu_callback.action == "parameters":
                            client.answer_callback_query(menu_callback.callback_query_id, "Параметры открыты.")
                            _send_parameters_guide(client, menu_callback.chat_id)
                        elif menu_callback.action == "help":
                            client.answer_callback_query(menu_callback.callback_query_id, "Помощь открыта.")
                            client.send_message(
                                menu_callback.chat_id,
                                _help_text(settings.default_engine, settings.default_market),
                                reply_markup=help_keyboard(),
                            )
                        elif menu_callback.action == "guide":
                            client.answer_callback_query(menu_callback.callback_query_id, "Шпаргалка открыта.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_production_guide(),
                                reply_markup=production_guide_keyboard(),
                            )
                        elif menu_callback.action == "preset_categories":
                            client.answer_callback_query(menu_callback.callback_query_id, "Истории открыты.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_preset_category_list(),
                                reply_markup=preset_category_inline_keyboard(),
                            )
                        elif menu_callback.action == "ideas":
                            client.answer_callback_query(menu_callback.callback_query_id, "Меню обновлено.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_preset_list("shorts"),
                                reply_markup=preset_inline_keyboard(mode="shorts"),
                            )
                        elif menu_callback.action == "examples":
                            client.answer_callback_query(menu_callback.callback_query_id, "Меню обновлено.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_example_list(),
                                reply_markup=example_inline_keyboard(),
                            )
                        elif menu_callback.action == "posts":
                            client.answer_callback_query(menu_callback.callback_query_id, "Посты открыты.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_post_list(),
                                reply_markup=post_inline_keyboard(),
                            )
                        elif menu_callback.action == "pack":
                            client.answer_callback_query(menu_callback.callback_query_id, "Пакет открыт.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_pulse_pack(),
                                reply_markup=pulse_pack_keyboard(),
                            )
                        elif menu_callback.action == "content_plan":
                            client.answer_callback_query(menu_callback.callback_query_id, "Контент-план открыт.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_content_plan(),
                                reply_markup=content_plan_keyboard(),
                            )
                        elif menu_callback.action == "content_plan_shorts":
                            client.answer_callback_query(menu_callback.callback_query_id, "Контент-план поставлен в очередь.")
                            job_queue.enqueue_content_plan_shorts(menu_callback.chat_id, int(update["update_id"]))
                        elif menu_callback.action == "publication_week":
                            client.answer_callback_query(menu_callback.callback_query_id, "Недельный выпуск поставлен в очередь.")
                            job_queue.enqueue_weekly_publication_pack(menu_callback.chat_id, int(update["update_id"]))
                        elif menu_callback.action == "weekly_posts":
                            client.answer_callback_query(menu_callback.callback_query_id, "Посты недели открыты.")
                            send_weekly_posts(client, menu_callback.chat_id)
                        elif menu_callback.action == "daily_short":
                            client.answer_callback_query(menu_callback.callback_query_id, "Шортс дня поставлен в очередь.")
                            job_queue.enqueue_daily_content_plan_short(menu_callback.chat_id, int(update["update_id"]))
                        elif menu_callback.action == "publication_day":
                            client.answer_callback_query(menu_callback.callback_query_id, "Публикационный день поставлен в очередь.")
                            job_queue.enqueue_daily_publication_day(menu_callback.chat_id, int(update["update_id"]))
                        elif menu_callback.action == "daily_post":
                            client.answer_callback_query(menu_callback.callback_query_id, "Пост дня открыт.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_daily_post(),
                                reply_markup=daily_post_keyboard(),
                            )
                        elif menu_callback.action == "daily_kit":
                            client.answer_callback_query(menu_callback.callback_query_id, "Пакет дня открыт.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_daily_content_kit(),
                                reply_markup=daily_content_kit_keyboard(),
                            )
                        elif menu_callback.action == "kits":
                            client.answer_callback_query(menu_callback.callback_query_id, "Пакеты открыты.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_preset_kit_list(),
                                reply_markup=preset_kit_inline_keyboard(),
                            )
                        elif menu_callback.action == "drafts":
                            client.answer_callback_query(menu_callback.callback_query_id, "Меню обновлено.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_preset_category_list("draft"),
                                reply_markup=preset_category_inline_keyboard(mode="draft"),
                            )
                        elif menu_callback.action == "draft_presets":
                            client.answer_callback_query(menu_callback.callback_query_id, "Меню обновлено.")
                            client.send_message(
                                menu_callback.chat_id,
                                format_preset_list("draft"),
                                reply_markup=preset_inline_keyboard(mode="draft"),
                            )
                        elif menu_callback.action == "hot_drafts":
                            client.answer_callback_query(menu_callback.callback_query_id, "Top-draft поставлены в очередь.")
                            job_queue.enqueue_hot_preset_drafts(menu_callback.chat_id, int(update["update_id"]))
                        elif menu_callback.action == "hot_shorts":
                            client.answer_callback_query(menu_callback.callback_query_id, "Top-shorts поставлены в очередь.")
                            job_queue.enqueue_hot_preset_shorts(menu_callback.chat_id, int(update["update_id"]))
                        elif menu_callback.action == "hot_shorts_studio":
                            client.answer_callback_query(menu_callback.callback_query_id, "Top-shorts Studio поставлены в очередь.")
                            job_queue.enqueue_hot_preset_shorts_with_theme(menu_callback.chat_id, int(update["update_id"]), "studio")
                        elif menu_callback.action == "hot_shorts_aurora":
                            client.answer_callback_query(menu_callback.callback_query_id, "Top-shorts Aurora поставлены в очередь.")
                            job_queue.enqueue_hot_preset_shorts_with_theme(menu_callback.chat_id, int(update["update_id"]), "aurora")
                        elif menu_callback.action == "all_shorts":
                            client.answer_callback_query(menu_callback.callback_query_id, "Все shorts поставлены в очередь.")
                            job_queue.enqueue_preset_shorts(menu_callback.chat_id, int(update["update_id"]))
                        elif menu_callback.action == "all_shorts_studio":
                            client.answer_callback_query(menu_callback.callback_query_id, "Все shorts Studio поставлены в очередь.")
                            job_queue.enqueue_preset_shorts(menu_callback.chat_id, int(update["update_id"]), theme="studio")
                        elif menu_callback.action == "all_shorts_aurora":
                            client.answer_callback_query(menu_callback.callback_query_id, "Все shorts Aurora поставлены в очередь.")
                            job_queue.enqueue_preset_shorts(menu_callback.chat_id, int(update["update_id"]), theme="aurora")
                        elif menu_callback.action == "example_drafts":
                            client.answer_callback_query(menu_callback.callback_query_id, "Draft-примеры поставлены в очередь.")
                            job_queue.enqueue_example_drafts(menu_callback.chat_id, int(update["update_id"]))
                        elif menu_callback.action == "random_shorts":
                            client.answer_callback_query(menu_callback.callback_query_id, "Случайный шортс поставлен в очередь.")
                            job_queue.enqueue_random_universe_shorts(menu_callback.chat_id, int(update["update_id"]))
                        elif menu_callback.action in RANDOM_SHORT_MENU_ACTIONS:
                            category_name, count, answer_text = RANDOM_SHORT_MENU_ACTIONS[menu_callback.action]
                            client.answer_callback_query(menu_callback.callback_query_id, answer_text)
                            job_queue.enqueue_random_universe_shorts(
                                menu_callback.chat_id,
                                int(update["update_id"]),
                                category_name=category_name,
                                count=count,
                            )
                        elif menu_callback.action == "random_draft":
                            client.answer_callback_query(menu_callback.callback_query_id, "Случайный draft поставлен в очередь.")
                            job_queue.enqueue_random_universe_draft(menu_callback.chat_id, int(update["update_id"]))
                        elif menu_callback.action == "random_example":
                            client.answer_callback_query(menu_callback.callback_query_id, "Случайный пример поставлен в очередь.")
                            job_queue.enqueue_random_example_draft(menu_callback.chat_id, int(update["update_id"]))
                        elif menu_callback.action == "music":
                            client.answer_callback_query(menu_callback.callback_query_id, "Музыка открыта.")
                            client.send_message(menu_callback.chat_id, format_music_list())
                        elif menu_callback.action == "covers":
                            client.answer_callback_query(menu_callback.callback_query_id, "Обложки открыты.")
                            client.send_message(menu_callback.chat_id, format_cover_list())
                        elif menu_callback.action == "queue":
                            client.answer_callback_query(menu_callback.callback_query_id, "Статус очереди обновлен.")
                            client.send_message(
                                menu_callback.chat_id,
                                job_queue.status_text(),
                                reply_markup=queue_status_keyboard(),
                            )
                        continue
                    category_callback = _extract_preset_category_callback(update)
                    if category_callback is not None:
                        if settings.allowed_chat_ids and category_callback.chat_id not in settings.allowed_chat_ids:
                            client.answer_callback_query(category_callback.callback_query_id, "This chat is not allowed.")
                            client.send_message(category_callback.chat_id, "This chat is not allowed to use this bot.")
                        else:
                            category = get_preset_category(category_callback.category_name)
                            client.answer_callback_query(category_callback.callback_query_id, "Категория открыта.")
                            client.send_message(
                                category_callback.chat_id,
                                format_preset_category(category.name, category_callback.mode),
                                reply_markup=preset_category_keyboard(category.name, mode=category_callback.mode),
                            )
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
                    post_callback = _extract_post_callback(update)
                    if post_callback is not None:
                        if settings.allowed_chat_ids and post_callback.chat_id not in settings.allowed_chat_ids:
                            client.answer_callback_query(post_callback.callback_query_id, "This chat is not allowed.")
                            client.send_message(post_callback.chat_id, "This chat is not allowed to use this bot.")
                        else:
                            preset = get_preset(post_callback.preset_name)
                            client.answer_callback_query(post_callback.callback_query_id, "Пост открыт.")
                            client.send_message(post_callback.chat_id, format_pulse_post(preset))
                        continue
                    kit_callback = _extract_preset_kit_callback(update)
                    if kit_callback is not None:
                        if settings.allowed_chat_ids and kit_callback.chat_id not in settings.allowed_chat_ids:
                            client.answer_callback_query(kit_callback.callback_query_id, "This chat is not allowed.")
                            client.send_message(kit_callback.chat_id, "This chat is not allowed to use this bot.")
                        else:
                            client.answer_callback_query(kit_callback.callback_query_id, "Пакет открыт.")
                            client.send_message(
                                kit_callback.chat_id,
                                format_preset_kit(kit_callback.preset_name),
                                reply_markup=preset_kit_keyboard(kit_callback.preset_name),
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
                    preset_theme_variants_callback = _extract_preset_theme_variants_callback(update)
                    if preset_theme_variants_callback is not None:
                        if settings.allowed_chat_ids and preset_theme_variants_callback.chat_id not in settings.allowed_chat_ids:
                            client.answer_callback_query(
                                preset_theme_variants_callback.callback_query_id,
                                "This chat is not allowed.",
                            )
                            client.send_message(
                                preset_theme_variants_callback.chat_id,
                                "This chat is not allowed to use this bot.",
                            )
                        else:
                            client.answer_callback_query(
                                preset_theme_variants_callback.callback_query_id,
                                "Варианты по темам поставлены в очередь.",
                            )
                            job_queue.enqueue_preset_theme_variants(
                                preset_theme_variants_callback.chat_id,
                                int(update["update_id"]),
                                preset_theme_variants_callback.preset_name,
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
