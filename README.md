# Stock Prices

Stock Prices генерирует стильные MP4-видео с анимированными рыночными графиками. Проект можно запускать из CLI, через Python API или как постоянно работающего Telegram-бота в Docker.

## Единый вход в документацию

Основная документация находится в [docs/index.md](docs/index.md). Локально красивую версию сайта можно открыть через MkDocs:

```bash
python -m mkdocs serve
```

После запуска откройте `http://127.0.0.1:8000`.

Ветки разработки:

- `develop` - интеграционная ветка для рабочих улучшений и проверок.
- `main` - стабильная ветка, из которой публикуется GitHub Pages.

CI запускается для `main`, `develop` и pull request в эти ветки. GitHub Pages публикуется автоматически через `.github/workflows/pages.yml` только при push в `main`.

## Быстрый запуск в Docker

1. Создайте `.env` в корне проекта:

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
```

2. Запустите контейнер:

```bash
docker compose up -d --build
```

3. Проверьте состояние:

```bash
docker compose ps
docker compose logs -f stock-prices-bot
```

После этого можно писать Telegram-боту:

```text
/start
/shoot
снять
/help
/shorts SBER LKOH за год
/draft metals
снять день
снять неделю
/queue

LKOH
SBER LKOH 2020 2024
```

Можно отправить несколько роликов одним сообщением, по одному запросу на строку:

```text
металлы
черновик угольщики
SBER LKOH 2020 2024 shorts
```

## Локальный CLI

Установка в режиме разработки:

```bash
pip install -e .
```

Российская акция:

```bash
stock-prices --tickers LKOH --start_date 2015-01-01 --end_date 2026-05-26 --currency RUB --duration 20 --fps 20
```

Глобальный инструмент:

```bash
stock-prices --tickers "AAPL|global|shares" --start_date 2015-01-01 --end_date 2026-05-26 --currency USD
```

Формат тикера:

```text
TICKER
TICKER|ENGINE|MARKET
```

Если указан только `TICKER`, используется рынок по умолчанию: `stock|shares`.

## Telegram-бот

Бот использует тот же pipeline, что CLI: загружает данные, готовит датасет, рендерит MP4 и отправляет ролик обратно в чат.

Главные входы:

- `/menu`, `/start`, `/меню` - компактный пульт для Пульса: снять, день, неделя, пакеты, план, очередь, справочник.
- `/quick`, `/shoot`, `снять` - быстрый пульт: день, неделя, top-серия, случайный ролик, тексты и очередь.
- `/help` - короткая справка по синтаксису.
- `/guide` или `шпаргалка` - рабочий процесс публикации без длинного списка команд.
- `/queue` или `очередь` - статус активной и ожидающих задач.

При запуске бот обновляет встроенное меню команд Telegram: `/shoot`, `/publish_day`, `/publish_week`, `/shorts`, `/draft`, `/queue`, `/today_post`, `/week_posts`, `/help`.

Прямой запуск ролика:

```text
/shorts SBER LKOH за год
сделай шортс про SBER и LKOH за полгода для Пульса
gold silver palladium 2010-2026 RUB capital invest initial=0 monthly=30000 gradient
```

Для контента в Пульсе есть preset-сценарии, категории историй (`категории`, `category drama`, `category quiet`), публикационные пакеты и готовые тексты без LLM. Подробная справка находится в [docs/telegram.md](docs/telegram.md).

Запуск локально:

```bash
stock-prices bot --allowed_chat_id 123456789
```

## Python API

```python
from datetime import date

from stock_prices import RenderSettings, TickerSpec, VideoRequest, generate_video

path = generate_video(
    VideoRequest(
        ticker_specs=[TickerSpec("LKOH")],
        render=RenderSettings(
            start_date=date(2015, 1, 1),
            end_date=date(2026, 5, 26),
            duration=20,
            fps=20,
        ),
    )
)
print(path)
```

## Проверки

```bash
$env:PYTHONPATH = "src"
python -m pytest -q
python -m mkdocs build --strict
python -m compileall -q src tests scripts
```

## Разделы документации

- [Демонстрация возможностей](docs/demo.md)
- [Как писать запросы в Telegram](docs/telegram.md)
- [Запуск и проверка](docs/runbook.md)
- [Docker и постоянный бот](docs/docker.md)
- [API](docs/reference/api.md)
