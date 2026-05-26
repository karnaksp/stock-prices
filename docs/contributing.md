---
title: Разработка
---

# Разработка

## Принципы

- Держать один общий pipeline генерации видео для CLI, Telegram и Python API.
- Не дублировать бизнес-логику в интерфейсных слоях.
- Для новых рынков добавлять нормализацию данных и тесты на минимальный реальный пример.
- Не коммитить `.env`, токены, сгенерированные MP4, parquet-кэш и локальные логи.

## Локальная подготовка

```powershell
python -m pip install -e .
$env:PYTHONPATH = "src"
```

Проверить импорт и CLI:

```powershell
python -m stock_prices -h
python -m stock_prices bot -h
```

## Проверки перед изменениями

```powershell
python -m pytest -q
python -m ruff check .
python -m compileall -q src tests
```

## Проверка рендера

```powershell
python -m stock_prices --tickers "SBER|stock|shares" "LKOH|stock|shares" --start_date 2020-01-01 --end_date 2024-12-31 --duration 2 --fps 2 --currency RUB --output_dir animations\check
```

## Проверка Docker

```powershell
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 stock-prices-bot
```

## Структура проекта

```text
src/stock_prices/_internal/cli.py                CLI и настройки запуска
src/stock_prices/_internal/telegram_bot.py       Telegram Bot API
src/stock_prices/_internal/telegram_requests.py  парсер Telegram-сообщений
src/stock_prices/_internal/pipeline.py           общий pipeline генерации
src/stock_prices/_internal/lib/downloader.py     загрузка данных
src/stock_prices/_internal/lib/dataset_builder.py подготовка датасета
src/stock_prices/_internal/lib/plotting.py       рендер MP4
tests/                                           pytest-проверки
docs/                                            документация MkDocs
```

## Работа с документацией

Документация живет в `docs/` и собирается MkDocs Material:

```powershell
python -m mkdocs serve
python -m mkdocs build --strict
```

Главная точка входа: `docs/index.md`.

## Автоматический деплой GitHub Pages

Workflow `.github/workflows/pages.yml` запускается при каждом push в `main` и вручную через `workflow_dispatch`. Он собирает `site/`, загружает результат как GitHub Pages artifact и публикует сайт через GitHub Pages.

Для работы в настройках репозитория нужно выбрать Pages source `GitHub Actions`.
