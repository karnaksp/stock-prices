"""Per-group forum routes shared by polling and asynchronous delivery."""
from __future__ import annotations

import json
import os
from typing import Any


def get_group_topic_ids() -> dict[int, int]:
    raw = os.getenv("STOCK_PRICES_GROUP_TOPICS", "").strip()
    if not raw:
        return {}
    error = "STOCK_PRICES_GROUP_TOPICS must map negative group IDs to positive integer topic IDs."
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(error)
        routes = {}
        for chat_id, topic_id in data.items():
            if (not chat_id.startswith("-") or not chat_id[1:].isdigit()
                    or int(chat_id) >= 0 or type(topic_id) is not int or topic_id <= 0):
                raise ValueError(error)
            routes[int(chat_id)] = topic_id
        return routes
    except (ValueError, TypeError):
        raise ValueError(error) from None


def update_is_in_group_topic(update: dict[str, Any], routes: dict[int, int]) -> bool:
    message = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    topic_id = routes.get(chat_id)
    return topic_id is None or message.get("message_thread_id") == topic_id
