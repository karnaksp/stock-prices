# Stock Prices

Stock Prices генерирует MP4-видео с анимированными рыночными графиками. Один и тот же pipeline работает из CLI, Python API и Telegram-бота.

## Единый вход

Основная русская документация живет на сайте MkDocs: [docs/index.md](docs/index.md).

Локально сайт открывается так:

```powershell
python -m mkdocs serve
```

После запуска откройте `http://127.0.0.1:8000`.

Разработка ведется в `develop`, стабильная версия и GitHub Pages публикуются из `main`. CI запускается для `main`, `develop` и pull request в эти ветки.

## Быстрый старт

### Docker-бот

```powershell
copy .env.example .env
# Заполните TELEGRAM_BOT_TOKEN в .env
docker compose up -d --build
docker compose ps
```

Логи:

```powershell
docker compose logs -f stock-prices-bot
```

### CLI

```powershell
python -m pip install -e .
python -m stock_prices --tickers "SBER|stock|shares" "LKOH|stock|shares" --start_date 2020-01-01 --end_date 2024-12-31 --currency RUB --duration 20 --fps 20
```

Формат тикера:

```text
TICKER
TICKER|ENGINE|MARKET
```

Если указан только `TICKER`, используется рынок по умолчанию: `stock|shares`.

## Telegram

Бот не придумывает идеи сам и не использует LLM. Он принимает команду или текстовый запрос, ставит генерацию в очередь, рендерит MP4 и отправляет результат обратно в чат.

Минимальный набор:

| Задача | Что отправить |
| --- | --- |
| Открыть меню | `/start` или `/menu` |
| Быстро снять ролик | `/shoot` или `снять` |
| Выбрать готовую историю | `/shorts` |
| Снять свой шортс | `/shorts SBER LKOH за год` |
| Проверить очередь | `/queue` или `статус` |
| Посмотреть справку | `/help` |

Обычный запрос тоже работает:

```text
LKOH
SBER LKOH 2020 2024
gold silver palladium 2018-2026 RUB capital invest initial=0 monthly=30000 gradient
```

Подробный синтаксис: [docs/telegram.md](docs/telegram.md).

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

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
python -m mkdocs build --strict
python -m compileall -q src tests scripts
```

## Разделы документации

- [Главная страница сайта](docs/index.md)
- [Демонстрация возможностей](docs/demo.md)
- [Telegram-запросы](docs/telegram.md)
- [Запуск и проверка](docs/runbook.md)
- [Docker и постоянный бот](docs/docker.md)
- [API](docs/reference/api.md)
