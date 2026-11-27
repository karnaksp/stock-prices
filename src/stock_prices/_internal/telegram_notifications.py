"""Send job notifications independently of the render worker."""

from __future__ import annotations

import logging
from concurrent.futures import Future
from itertools import count
from pathlib import Path
from queue import PriorityQueue
from threading import Event, Thread
from typing import Any, Callable


class TelegramNotificationQueue:
    def __init__(self, client: Any):
        self.client = client
        self._queue: PriorityQueue[tuple[int, int, Callable[[], None] | None, Event | None, Future | None]] = PriorityQueue()
        self._sequence = count()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = Thread(target=self._run, name="telegram-notifications", daemon=True)
            self._thread.start()

    def send_message(self, chat_id: int, text: str, *, cancelled: Event | None = None, **kwargs) -> None:
        if cancelled is not None and cancelled.is_set():
            return
        if self._thread is None:
            self.client.send_message(chat_id, text, **kwargs)
        else:
            self._queue.put((1, next(self._sequence), lambda: self.client.send_message(chat_id, text, **kwargs), cancelled, None))

    def send_video(self, chat_id: int, path: Path, caption: str, **kwargs) -> None:
        if self._thread is None:
            self.client.send_video(chat_id, path, caption, **kwargs)
            return
        result = Future()
        self._queue.put((0, next(self._sequence), lambda: self.client.send_video(chat_id, path, caption, **kwargs), None, result))
        result.result()

    def join(self) -> None:
        self._queue.join()

    def stop(self) -> None:
        if self._thread is not None:
            self._queue.put((2, next(self._sequence), None, None, None))
            self._thread.join()
            self._thread = None

    def _run(self) -> None:
        while True:
            _priority, _sequence, operation, cancelled, result = self._queue.get()
            try:
                if operation is None:
                    return
                if cancelled is None or not cancelled.is_set():
                    operation()
                if result is not None:
                    result.set_result(None)
            except Exception as exc:
                if result is not None:
                    result.set_exception(exc)
                else:
                    logging.exception("Telegram job notification failed")
            finally:
                self._queue.task_done()
