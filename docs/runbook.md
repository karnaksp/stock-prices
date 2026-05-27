# Запуск и проверка

Этот runbook описывает рабочий запуск проекта на Windows/PowerShell и проверку Telegram-бота.

## 1. Подготовить окружение

В корне проекта:

```powershell
cd C:\Users\d.irinyakov\Documents\github\stock_prices
python -m pip install -e .
$env:PYTHONPATH = "src"
```

Проверить, что пакет импортируется из текущего проекта:

```powershell
python -m stock_prices -h
```

Ожидаемый результат: выводится справка `stock-prices` с параметрами `--tickers`, `--start_date`, `--end_date`, `bot`.

## 2. Проверить локальную генерацию видео

MOEX акция:

```powershell
python -m stock_prices --tickers "SBER|stock|shares" --start_date 2024-01-03 --end_date 2024-01-10 --duration 2 --fps 2 --currency RUB --output_dir animations\check
```

Иностранная акция:

```powershell
python -m stock_prices --tickers "AAPL|global|shares" --start_date 2024-01-03 --end_date 2024-01-10 --duration 2 --fps 2 --currency USD --output_dir animations\check
```

Другие полезные проверки:

```powershell
python -m stock_prices --tickers "SiH4|futures|forts" --start_date 2024-01-03 --end_date 2024-01-10 --value_col CLOSE --currency RUB --output_dir animations\check
python -m stock_prices --tickers "GC=F|global|metals" --start_date 2024-01-03 --end_date 2024-01-10 --value_col CLOSE --currency USD --output_dir animations\check
python -m stock_prices --tickers "BTC-USD|global|crypto" --start_date 2024-01-03 --end_date 2024-01-10 --value_col CLOSE --currency USD --output_dir animations\check
```

Ожидаемый результат: в `animations\check` появляются `.mp4` файлы.

## 3. Настроить Telegram

Токен хранится в локальном `.env` в корне проекта. Файл добавлен в `.gitignore`, его нельзя коммитить.

Минимальный `.env`:

```env
TELEGRAM_BOT_TOKEN=your-token
STOCK_PRICES_DEFAULT_ENGINE=stock
STOCK_PRICES_DEFAULT_MARKET=shares
STOCK_PRICES_CURRENCY=RUB
STOCK_PRICES_DURATION=30
STOCK_PRICES_FPS=20
STOCK_PRICES_OUTPUT_DIR=animations
```

Проверить, что Telegram API видит бота:

```powershell
@'
from stock_prices._internal.env import load_env_file
from stock_prices._internal.telegram_bot import TelegramClient
import os

load_env_file()
client = TelegramClient(os.environ["TELEGRAM_BOT_TOKEN"], timeout=10)
info = client.call("getMe")
print(info["username"], info["is_bot"])
'@ | python -
```

Ожидаемый результат: имя бота и `True`.

## 4. Узнать chat id

1. Написать боту любое сообщение в Telegram, например `/start`.
2. Выполнить:

```powershell
@'
from stock_prices._internal.env import load_env_file
from stock_prices._internal.telegram_bot import TelegramClient
import os

load_env_file()
client = TelegramClient(os.environ["TELEGRAM_BOT_TOKEN"], timeout=10)
updates = client.get_updates(offset=None, timeout=1, limit=10)
for update in updates:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    print(chat.get("id"), message.get("text"))
'@ | python -
```

Скопировать `chat id`.

## 5. Запустить бота

Для личного использования лучше ограничить доступ своим chat id:

```powershell
python -m stock_prices bot --allowed_chat_id 123456789
```

Для локальной быстрой проверки без ограничения:

```powershell
python -m stock_prices bot
```

Ожидаемый результат: процесс остается запущенным и пишет логи. Остановить можно `Ctrl+C`.

## 6. Проверить запросы из Telegram

Отправить боту сообщения:

```text
LKOH
LKOH SBER 2020 2024
AAPL global USD gradient
gold 2024
gold silver palladium 2018-2026 RUB capital invest initial=0 monthly=30000 gradient
btc 2024 close
SiH4 futures 2024 close
USD000UTSTOM selt 2024 close
```

Ожидаемый сценарий:

1. Бот отвечает статусом `Генерирую видео`.
2. Скачивает или обновляет данные.
3. Собирает MP4.
4. Отправляет видео обратно в чат.

## 7. Диагностика

Если Telegram пишет `Conflict: terminated by other getUpdates request`, значит где-то уже запущена копия этого же бота. Остановить старый процесс и запустить один экземпляр.

Если MOEX отвечает таймаутом, повторить запрос: в коде есть retry, но биржевой ISS иногда временно недоступен.

Если Yahoo Finance не находит инструмент, проверить тикер в формате Yahoo: `GC=F`, `BTC-USD`, `EURUSD=X`, `AAPL`.

Если видео не отправляется в Telegram, проверить размер файла и доступность `animations\...mp4`. Telegram Bot API принимает видео как файл через `sendVideo`.

## 8. Постоянный запуск через Docker

Чтобы бот работал постоянно и принимал запросы в любой момент:

```powershell
docker compose up -d --build
docker compose ps
docker compose logs -f stock-prices-bot
```

Подробно: [Docker и постоянный Telegram-бот](docker.md).

## 9. Контроль качества

Перед демонстрацией:

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
python -m mkdocs build --strict
python -m compileall -q src tests
```
