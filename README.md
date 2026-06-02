# Stock Prices

Stock Prices генерирует стильные MP4-видео с анимированными графиками по тикерам. Проект можно запускать из CLI, через Python API или как постоянно работающего Telegram-бота в Docker.

## Единый вход в документацию

Основная документация находится в [docs/index.md](docs/index.md). Локально красивую версию сайта можно открыть через MkDocs:

```bash
python -m mkdocs serve
```

После запуска откройте `http://127.0.0.1:8000`.

Ветки разработки:

- `develop` - интеграционная ветка для рабочих улучшений и проверок.
- `main` - стабильная ветка, из которой публикуется GitHub Pages.

CI запускается для `main`, `develop` и pull request в эти ветки. GitHub Pages публикуется автоматически через workflow `.github/workflows/pages.yml` только при push в `main`.

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
/ideas
/drafts
/идеи
/черновики
случайный черновик
random draft
/random_draft
/queue
очередь
LKOH
SBER LKOH 2020 2024
металлы
черновик металлы
госы
экспортёры
черновик угольщики
preset metals
пресет металлы
preset neweconomy duration=12 theme=studio
пресет голубые фишки draft
SBER LKOH shorts
AAPL global USD shorts
BTC price duration=12 fps=24
gold 2018-2026 USD gradient
gold silver palladium 2018-2026 RUB capital invest initial=0 monthly=30000 gradient theme=aurora
SiH4 futures 2024 close
USD000UTSTOM selt 2024 close
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

Бот использует тот же pipeline, что CLI: загружает данные, готовит датасет, рендерит MP4 и отправляет ролик обратно в чат. Команда `/ideas` показывает готовые сценарии для Пульса с русскими кнопками запуска. Команды `случайный черновик`, `random draft` и `/random_draft` выбирают один из проверенных preset-сценариев и ставят короткий draft в очередь без LLM. Несколько запросов можно отправить одним сообщением: бот поставит каждую непустую строку отдельной задачей. После постановки задачи бот показывает кнопку `Статус очереди`; команды `/queue`, `/status` и `очередь` делают то же текстом: показывают активный job, ожидающие job id и счетчики завершений/ошибок. После любого MP4 бот отправляет черновик текста для Пульса. Для preset-сценариев это ручной хук, описание, хэштеги и музыкальное/монтажное настроение; для custom-запросов - нейтральный шаблон по тикерам, периоду, валюте и инвестиционному сценарию. После preset-текста появляются follow-up кнопки: быстрый черновик 4s, полноценный шортс 16s и вариант 12s.

Запуск локально:

```bash
stock-prices bot --allowed_chat_id 123456789
```

Полезные сокращения в сообщениях:

```text
/ideas                  список готовых сценариев для Пульса с кнопками
/drafts                 те же preset-кнопки, но в быстром черновом режиме
/идеи                  русская команда для списка shorts-сценариев
кнопки /ideas          подписаны по-русски, команды preset остаются английскими
/черновики             русская команда для быстрых draft-прогонов
все черновики          поставить в очередь draft-прогоны всех готовых сценариев
случайный черновик     выбрать один проверенный preset и поставить draft в очередь без LLM
random draft           английский вариант случайного черновика
/random_draft          command-формат для того же действия
/queue                 статус очереди: активный job, ожидание, готово и ошибки
очередь                русский вариант статуса очереди
Статус очереди         кнопка после постановки задачи; обновляет статус без нового текста
несколько строк        каждая непустая строка становится отдельной задачей в очереди
Текст для Пульса       бот присылает черновик поста после каждого MP4
follow-up кнопки       после preset-видео: черновик 4s, шортс 16s, вариант 12s
металлы                короткий запуск preset-сценария с металлами
черновик металлы       быстрый draft-прогон сценария с металлами
госы                  госкомпании: GAZP / AFLT / SNGS
экспортёры            экспортеры: LKOH / PHOR / NLMK
черновик угольщики    быстрый draft-прогон MTLR / RASP
preset metals           готовый сценарий с металлами
пресет металлы          тот же сценарий русским текстом
preset neweconomy       готовый сценарий новой экономики
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
shorts                 короткий режим: duration=16 fps=24 gradient
draft                  быстрый черновик: duration=4 fps=8 без gradient
theme=aurora           визуальная тема: default, aurora или studio
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
- [Как писать запросы в Telegram](docs/telegram.md)
- [Запуск и проверка](docs/runbook.md)
- [Docker и постоянный бот](docs/docker.md)
- [API](docs/reference/api.md)
