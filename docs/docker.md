# Docker и постоянный Telegram-бот

Docker-режим нужен, чтобы бот был всегда запущен и принимал запросы из Telegram в любой момент. Контейнер запускает `python -m stock_prices bot`, читает настройки из `.env`, рендерит MP4 в output-директорию и после отправки может очищать старые ролики.

## Файлы

- `Dockerfile` собирает образ приложения.
- `docker-compose.yml` запускает сервис `stock-prices-bot` с `restart: unless-stopped`.
- `.dockerignore` не отправляет в image `.env`, `.git`, MP4 и локальные кэши.
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
STOCK_PRICES_THEME=default
STOCK_PRICES_OUTPUT_DIR=animations
STOCK_PRICES_RETENTION_DAYS=0
STOCK_PRICES_UNIVERSE_FILE=
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

Во время тяжелого encode контейнер может быть сильно загружен CPU, поэтому healthcheck настроен с запасом по timeout. В Telegram бот дополнительно присылает промежуточный статус для долгих рендеров.

После запуска можно писать боту:

```text
LKOH
SBER LKOH 2020 2024
BTC price duration=12 fps=24
gold 2018-2026 USD gradient
gold silver palladium 2018-2026 RUB capital invest initial=0 monthly=30000 gradient theme=aurora
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
animations/  временные MP4 до отправки и очистки
logs/        логи
```

Эти папки остаются на хосте и переживают пересборку контейнера. Исторические данные не сохраняются в parquet: бот скачивает их для конкретного запроса и передает дальше в памяти.

`STOCK_PRICES_RETENTION_DAYS=0` удаляет MP4 сразу после успешной отправки. Это рабочий production-режим: видео не кешируются и не накапливаются. Положительное значение стоит использовать только временно для ручной отладки.

`STOCK_PRICES_UNIVERSE_FILE` можно указать на metadata-only JSON, созданный `python scripts/collect_moex_universe.py --output config/moex_universe.json`. Этот файл расширяет random/day/week подборки тикерами MOEX, но не хранит ценовые данные.

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

Проверить healthcheck вручную:

```powershell
docker compose run --rm stock-prices-bot python -m stock_prices._internal.healthcheck
```

## Диагностика

Если в логах есть `Conflict: terminated by other getUpdates request`, запущен второй экземпляр этого же бота. Нужно оставить только один процесс polling: либо контейнер, либо локальный `python -m stock_prices bot`.

Если контейнер постоянно перезапускается:

```powershell
docker compose logs --tail=200 stock-prices-bot
```

Частые причины: пустой `TELEGRAM_BOT_TOKEN`, нет интернета, временно недоступны Telegram или источники данных.
