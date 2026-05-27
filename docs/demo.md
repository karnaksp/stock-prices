# Демонстрация Stock Prices

## Что делает проект

Stock Prices генерирует короткие MP4-видео с анимированными графиками цен и инвестиционного результата по тикерам. Пользователь может запустить генерацию из командной строки или просто написать тикер Telegram-боту: проект сам загрузит исторические данные, подготовит датасет, отрендерит стильный график и отправит готовое видео обратно.

Проект полезен для инвесторов, аналитиков, авторов финансового контента и команд, которым нужно быстро получить понятную визуализацию динамики актива без ручной подготовки графиков.

<figure class="sp-media sp-media--wide">
  <img src="/stock-prices/assets/demo-sber-lkoh.png" alt="Пример финального кадра видео SBER и LKOH">
  <figcaption>Финальный кадр ролика: цветные линии, события на нижних дорожках и процентные подписи по тикерам.</figcaption>
</figure>

## Ключевые возможности

- Генерация MP4-видео по одному или нескольким тикерам.
- Поддержка MOEX и глобальных инструментов через разные источники данных.
- Сценарии `price` и `capital`: можно показывать обычную цену закрытия или результат условной инвестиции с реинвестированием.
- Настраиваемые даты, валюта подписи, длительность, FPS, легенда и градиентная линия.
- Удобная работа через Telegram для быстрых запросов естественным коротким текстом.
- Единый Python API `generate_video(VideoRequest)`, который используется и CLI, и Telegram-ботом.
- Локальное сохранение промежуточных данных в parquet и финальных роликов в `animations/`.

## Для кого

- Частный инвестор: быстро сравнить `SBER` и `LKOH` за 5 лет.
- Автор Telegram-канала: получить ролик по `AAPL`, `BTC` или `gold` прямо из чата.
- Аналитик: проверить разные классы активов в одном стиле.
- Разработчик: встроить генерацию видео в другой Python-сервис через API.

## Архитектура

```text
CLI / Telegram
    |
    v
Parser -> VideoRequest / RenderSettings / TickerSpec
    |
    v
Pipeline generate_video()
    |
    +--> Downloader
    |       +--> MOEX ISS через apimoex
    |       +--> Yahoo Finance через yfinance
    |
    +--> Dataset builder
    |       +--> нормализация OHLCV
    |       +--> дивиденды и события
    |       +--> расчет CAPITAL_REINVEST
    |
    v
Matplotlib renderer -> imageio-ffmpeg -> MP4
    |
    v
Файл в animations/ или ответ Telegram-бота
```

Сильная сторона архитектуры в том, что вся генерация проходит через один pipeline. CLI, Python API и Telegram-бот не дублируют бизнес-логику, а только собирают параметры запроса.

## Источники данных

- MOEX ISS через `apimoex`: российские акции, индексы, облигации, валютный рынок и срочные инструменты.
- Yahoo Finance через `yfinance`: иностранные акции, ETF, индексы, валютные пары, криптовалюты, металлы и товарные фьючерсы.
- `currencyconverter`: конвертация глобальных инструментов в рублевую шкалу, когда это требуется.
- Локальные события из проекта: дополнительный контекст для дивидендов, сплитов и корпоративных событий.

## Поддерживаемые рынки и активы

| Класс | Пример | Формат |
| --- | --- | --- |
| Российские акции | `SBER`, `LKOH`, `GAZP` | `TICKER` или `TICKER|stock|shares` |
| Индексы MOEX | `IMOEX` | `IMOEX|stock|index` |
| Облигации MOEX | тикер облигации | `TICKER|stock|bonds` |
| Валютный рынок MOEX | `USD000UTSTOM` | `USD000UTSTOM|currency|selt` |
| Фьючерсы MOEX | `SiH4` | `SiH4|futures|forts` |
| Иностранные акции | `AAPL`, `MSFT`, `NVDA` | `AAPL|global|shares` |
| Глобальные индексы | `^GSPC`, `^IXIC` | `^GSPC|global|index` |
| Металлы | `gold`, `silver`, `GC=F` | Telegram alias или `GC=F|global|metals` |
| Товарные фьючерсы | `oil`, `BRENT`, `CL=F` | Telegram alias или `CL=F|global|commodities` |
| Валютные пары | `eurusd`, `EURUSD=X` | alias или `EURUSD=X|global|currency` |
| Криптовалюты | `btc`, `eth`, `BTC-USD` | alias или `BTC-USD|global|crypto` |

## CLI-примеры

Установка в режиме разработки:

```bash
pip install -e .
```

Российская акция:

```bash
stock-prices --tickers LKOH --start_date 2015-01-01 --end_date 2026-05-26 --currency RUB --duration 20 --fps 20
```

Сравнение двух российских акций:

```bash
stock-prices --tickers SBER LKOH --start_date 2020-01-01 --end_date 2026-05-26 --duration 24 --fps 20 --use_gradient
```

Иностранная акция:

```bash
stock-prices --tickers "AAPL|global|shares" --start_date 2018-01-01 --end_date 2026-05-26 --currency USD
```

Криптовалюта:

```bash
stock-prices --tickers "BTC-USD|global|crypto" --start_date 2020-01-01 --end_date 2026-05-26 --currency USD --value_col CLOSE
```

Металл через Yahoo Finance futures ticker:

```bash
stock-prices --tickers "GC=F|global|metals" --start_date 2018-01-01 --end_date 2026-05-26 --currency USD --use_gradient
```

Фьючерс MOEX:

```bash
stock-prices --tickers "SiH4|futures|forts" --start_date 2024-01-01 --end_date 2024-03-20 --value_col CLOSE
```

Валютный рынок MOEX:

```bash
stock-prices --tickers "USD000UTSTOM|currency|selt" --start_date 2020-01-01 --end_date 2026-05-26 --value_col CLOSE
```

## Работа через Telegram

Telegram-бот рассчитан на короткие запросы без знания CLI. Пользователь пишет тикер или несколько параметров в одном сообщении, бот отвечает статусом, генерирует видео и отправляет MP4.

Примеры сообщений:

```text
LKOH
SBER LKOH 2020 2024
AAPL global USD gradient
BTC price duration=12 fps=24
gold 2018-2026 USD gradient
EURUSD close
USD000UTSTOM selt 2020 2026
SiH4 futures 2024-01-01 2024-03-20 close
```

Поддерживаемые короткие параметры:

```text
2020 2024              период с 2020-01-01 по 2024-12-31
2018-2026              короткий диапазон лет
from=2020-01-01        точная дата начала
to=2024-12-31          точная дата окончания
USD / RUB / EUR        подпись валюты
global / stock         источник и движок
shares / bonds / index рынок MOEX
futures                MOEX futures/forts
selt                   MOEX currency/selt
close / price          цена закрытия
capital / reinvest     расчет капитала с реинвестированием
initial=0              стартовая сумма
monthly=30000          ежемесячное пополнение
yearly=120000          ежегодное пополнение
gradient               градиентная линия
duration=12 fps=24     настройки видео
```

Пример для сравнения вложений в золото, серебро и палладий с ежемесячным пополнением 30 000 рублей:

```text
gold silver palladium 2018-2026 RUB capital invest initial=0 monthly=30000 gradient
```

## Запуск Telegram-бота

Создайте локальный `.env` рядом с `pyproject.toml`:

```env
TELEGRAM_BOT_TOKEN=<botfather-token>
STOCK_PRICES_DEFAULT_ENGINE=stock
STOCK_PRICES_DEFAULT_MARKET=shares
STOCK_PRICES_CURRENCY=RUB
STOCK_PRICES_DURATION=30
STOCK_PRICES_FPS=20
```

Запуск:

```bash
stock-prices bot
```

Ограничение доступа конкретным чатом:

```bash
stock-prices bot --allowed_chat_id 123456789
```

Одноразовая проверка доступных Telegram updates:

```bash
stock-prices bot --once
```

## Используемые технологии

- Python 3.10+: основной язык проекта.
- Pandas и NumPy: обработка временных рядов, нормализация данных, расчет инвестиционного результата.
- Matplotlib: отрисовка кадров и графиков.
- imageio-ffmpeg: поставка ffmpeg-бинарника и сборка MP4 без отдельной системной установки ffmpeg.
- yfinance: глобальные рынки, акции, индексы, валюты, криптовалюты и товарные фьючерсы.
- apimoex и MOEX ISS: российский рынок, включая акции, индексы, валютные инструменты и futures.
- requests: Telegram Bot API, сетевые запросы, retry/timeout для MOEX.
- pyarrow/parquet: быстрый локальный формат для исторических данных.
- pytest и MkDocs: автоматические проверки поведения и документации.

## Сценарий демонстрации на 3-5 минут

1. Показать цель проекта: "пишем тикер, получаем готовое видео с графиком".
2. Запустить CLI для `SBER LKOH 2020-2024` и показать, что видео появляется в `animations/`.
3. Сгенерировать глобальный актив: `AAPL|global|shares` или `BTC-USD|global|crypto`.
4. Открыть Telegram-бота и отправить `gold 2018-2026 USD gradient`.
5. Показать ответ бота: статус генерации и готовый MP4.
6. Объяснить архитектуру: один pipeline, разные входы, разные источники данных, единый renderer.
7. Завершить roadmap: куда проект можно развивать дальше.

## Ограничения

- Качество и глубина истории зависят от MOEX ISS и Yahoo Finance.
- Некоторые тикеры могут отсутствовать, быть переименованы или иметь неполную историю.
- Для Telegram-бота нужен доступ в интернет и валидный токен BotFather.
- Длительные периоды, несколько тикеров и высокий FPS увеличивают время генерации.
- Yahoo Finance не является официальным источником биржевых данных для production-grade торговых решений.

## План развития

- Очередь задач для Telegram, чтобы несколько пользователей могли параллельно заказывать видео.
- Inline-кнопки Telegram для выбора периода, метрики, валюты и стиля.
- Пресеты дизайна: dark, light, editorial, terminal.
- Кэширование уже сгенерированных видео по хэшу запроса.
- Улучшение Docker-режима: healthcheck по источникам данных, ротация логов и готовые production-профили.
- Web UI для предпросмотра и настройки графика.
- Больше тестовой матрицы по реальным активам и graceful fallback для нестабильных источников данных.
