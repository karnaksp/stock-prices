# Docker и постоянный Telegram-бот

Docker-режим нужен, чтобы бот был всегда запущен и принимал запросы из Telegram в любой момент. Контейнер запускает `python -m stock_prices bot`, читает настройки из `.env`, а видео и parquet-кэш хранит на хосте через volume mounts.

## Файлы

- `Dockerfile` собирает образ приложения.
- `docker-compose.yml` запускает сервис `stock-prices-bot` с `restart: unless-stopped`.
- `.dockerignore` не отправляет в image `.env`, `.git`, MP4, parquet и кэши.
- `.env.example` показывает безопасный шаблон переменных без секретов.

## Настроить `.env`

В корне проекта должен быть локальный `.env`:

```env
TELEGRAM_BOT_TOKEN=<botfather-token>
STOCK_PRICES_DEFAULT_ENGINE=stock
STOCK_PRICES_DEFAULT_MARKET=shares
STOCK_PRICES_CURRENCY=RUB
STOCK_PRICES_DURATION=30
STOCK_PRICES_FPS=20
STOCK_PRICES_OUTPUT_DIR=animations
STOCK_PRICES_ALLOWED_CHAT_IDS=
```

`STOCK_PRICES_ALLOWED_CHAT_IDS` можно оставить пустым или указать список chat id через запятую:

```env
STOCK_PRICES_ALLOWED_CHAT_IDS=123456789,987654321
```

## Запустить

```powershell
cd C:\Users\d.irinyakov\Documents\github\stock_prices
docker compose up -d --build
```

Проверить состояние:

```powershell
docker compose ps
docker compose logs -f stock-prices-bot
```

После запуска можно писать боту:

```text
LKOH
SBER LKOH 2020 2024
BTC price duration=12 fps=24
gold 2018-2026 USD gradient
SiH4 futures 2024 close
```

## Остановить или перезапустить

```powershell
docker compose restart stock-prices-bot
docker compose down
```

`restart: unless-stopped` означает, что Docker будет поднимать контейнер после падения процесса и после перезапуска Docker Desktop, пока сервис не остановлен вручную.

## Где лежат данные

```text
animations/  готовые MP4
logs/        логи
stock/       parquet-кэш MOEX stock
global/      parquet-кэш Yahoo Finance
currency/    parquet-кэш MOEX currency
futures/     parquet-кэш MOEX futures
```

Эти папки остаются на хосте и переживают пересборку контейнера.

## Проверка без запуска бота

Проверить сборку image:

```powershell
docker compose build
```

Проверить справку внутри контейнера:

```powershell
docker compose run --rm stock-prices-bot python -m stock_prices -h
docker compose run --rm stock-prices-bot python -m stock_prices bot -h
```

Проверить Telegram token внутри контейнера без вывода секрета:

```powershell
docker compose run --rm stock-prices-bot python -c "from stock_prices._internal.telegram_bot import TelegramClient; import os; print(TelegramClient(os.environ['TELEGRAM_BOT_TOKEN'], timeout=10).call('getMe')['username'])"
```

## Диагностика

Если в логах есть `Conflict: terminated by other getUpdates request`, запущен второй экземпляр этого же бота. Нужно оставить только один процесс polling: либо контейнер, либо локальный `python -m stock_prices bot`.

Если контейнер постоянно перезапускается:

```powershell
docker compose logs --tail=200 stock-prices-bot
```

Частые причины: пустой `TELEGRAM_BOT_TOKEN`, нет интернета, временно недоступны Telegram или источники данных.
