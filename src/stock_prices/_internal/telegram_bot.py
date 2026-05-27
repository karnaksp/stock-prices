from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import requests

from stock_prices._internal.models import RenderSettings
from stock_prices._internal.pipeline import generate_video
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
    ) -> None:
        self.token = token
        self.render = render
        self.allowed_chat_ids = allowed_chat_ids or set()
        self.default_engine = default_engine
        self.default_market = default_market
        self.poll_timeout = poll_timeout
        self.once = once


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


def handle_ticker_message(client: TelegramClient, settings: TelegramBotSettings, chat_id: int, text: str) -> None:
    if settings.allowed_chat_ids and chat_id not in settings.allowed_chat_ids:
        client.send_message(chat_id, "This chat is not allowed to use this bot.")
        return
    if text.startswith("/start") or text.startswith("/help"):
        client.send_message(chat_id, _help_text(settings.default_engine, settings.default_market))
        return

    parsed = parse_telegram_video_request(text, settings.render, settings.default_engine, settings.default_market)
    render = parsed.request.render
    client.send_message(
        chat_id,
        f"Генерирую видео: {parsed.display_name}\n"
        f"{render.start_date} - {render.end_date}, {render.duration}s/{render.fps}fps",
    )
    output_path = generate_video(parsed.request)
    client.send_video(chat_id, output_path, f"{parsed.display_name}: {render.start_date} - {render.end_date}")


def run_telegram_bot(settings: TelegramBotSettings) -> None:
    client = TelegramClient(settings.token, settings.poll_timeout)
    offset: int | None = None
    logging.info("Telegram bot started.")

    while True:
        try:
            updates = client.get_updates(offset=offset, timeout=settings.poll_timeout)
            for update in updates:
                offset = int(update["update_id"]) + 1
                extracted = _extract_text_message(update)
                if extracted is None:
                    continue
                chat_id, text = extracted
                try:
                    handle_ticker_message(client, settings, chat_id, text)
                except Exception as exc:
                    logging.exception("Failed to process Telegram request")
                    client.send_message(chat_id, f"Failed to generate video: {exc}")
            if settings.once:
                return
        except KeyboardInterrupt:
            raise
        except Exception:
            logging.exception("Telegram polling failed")
            if settings.once:
                raise
            time.sleep(5)
