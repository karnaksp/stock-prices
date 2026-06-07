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

Telegram-бот делает market-motion videos из Mini App или обычного сообщения: принимает тикеры, категорию или сценарий, ставит задачу в очередь, рендерит MP4 и присылает ролик обратно в чат. Главная ценность - не каталог пресетов, а универсальный конструктор красивых рыночных видео под любые тикеры, периоды и инвестиционные истории. Готовые примеры остаются ориентирами.

Короткие входы:

| Задача | Что отправить |
| --- | --- |
| Открыть Mini App | кнопка `Mini App` в Telegram или `/app` |
| Открыть меню | `/start` или `/menu` |
| Посмотреть справку | `/help` |
| Посмотреть параметры | `/params` |
| Снять свой ролик | `/shorts SBER LKOH за год` |
| Случайный ролик | `random mixed 2` |
| Ролик по категории | `random metals 1` |
| Собрать план | `plan drama 5 days 2 tickers` |
| Поставить серию shorts в очередь | `plan shorts metals count=1 days=5` |
| Смотреть очередь | `/queue` |

Обычный текстовый запрос тоже работает:

```text
LKOH
SBER LKOH 2020 2024
gold silver palladium 2018-2026 RUB capital invest initial=0 monthly=30000 gradient
```

Подробный синтаксис: [docs/telegram.md](docs/telegram.md).

Исторические данные не сохраняются в parquet: pipeline скачивает их для конкретного запроса и передает дальше в памяти. Для Docker-бота production-значение `STOCK_PRICES_RETENTION_DAYS=0`: MP4 удаляется сразу после успешной отправки и не копится на диске.

Чтобы расширить random-подборки всеми доступными MOEX-акциями, соберите metadata-файл и укажите его в `.env`:

```powershell
python scripts/collect_moex_universe.py --output config/moex_universe.json
```

```env
STOCK_PRICES_UNIVERSE_FILE=config/moex_universe.json
```

Файл содержит только тикеры, даты истории и классификации, без ценовых рядов.

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
