# Stock Prices

Stock Prices генерирует стильные MP4-видео с анимированными графиками по тикерам. Проект можно запускать из CLI, через Python API или как постоянно работающего Telegram-бота в Docker.

## Единый вход в документацию

Основная документация находится в [docs/index.md](docs/index.md). Локально красивую версию сайта можно открыть через MkDocs:

```bash
python -m mkdocs serve
```

После запуска откройте `http://127.0.0.1:8000`.

В GitHub Pages сайт публикуется автоматически через workflow `.github/workflows/pages.yml` при каждом push в `main`.

## Быстрый запуск в Docker

1. Создайте `.env` в корне проекта:

```env
TELEGRAM_BOT_TOKEN=<botfather-token>
STOCK_PRICES_DEFAULT_ENGINE=stock
STOCK_PRICES_DEFAULT_MARKET=shares
STOCK_PRICES_CURRENCY=RUB
STOCK_PRICES_DURATION=30
STOCK_PRICES_FPS=20
STOCK_PRICES_OUTPUT_DIR=animations
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
LKOH
SBER LKOH 2020 2024
AAPL global USD gradient
BTC price duration=12 fps=24
gold 2018-2026 USD gradient
gold silver palladium 2018-2026 RUB capital invest initial=0 monthly=30000 gradient
SiH4 futures 2024 close
USD000UTSTOM selt 2024 close
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

Запуск локально:

```bash
stock-prices bot --allowed_chat_id 123456789
```

Полезные сокращения в сообщениях:

```text
2020 2024              период
from=2020-01-01        точная дата начала
to=2024-12-31          точная дата окончания
USD / RUB / EUR        подпись валюты
global / stock         источник данных
shares / bonds / index рынок MOEX
futures / selt         MOEX futures или currency
close / price          цена закрытия
capital / reinvest     капитал с реинвестированием
gradient               градиентная линия
duration=12 fps=24     настройки видео
```

Сокращения активов:

```text
gold / золото          GC=F
silver / серебро       SI=F
oil / нефть            CL=F
btc / биткоин          BTC-USD
eth / эфир             ETH-USD
eurusd                 EURUSD=X
SiH4 futures           MOEX futures/forts
USD000UTSTOM selt      MOEX currency/selt
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
python -m compileall -q src tests
```

## Разделы документации

- [Демонстрация возможностей](docs/demo.md)
- [Запуск и проверка](docs/runbook.md)
- [Docker и постоянный бот](docs/docker.md)
- [API](docs/reference/api.md)
