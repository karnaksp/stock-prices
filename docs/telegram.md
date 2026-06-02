---
title: Telegram-запросы
---

# Как писать запросы в Telegram

Бот не придумывает идеи сам и не использует LLM. Он принимает короткий текстовый запрос, ставит генерацию в очередь, загружает данные, рендерит MP4 и отправляет видео обратно в чат.

## Базовый формат

```text
TICKER [TICKER...] [period] [market/source] [currency] [metric] [options]
```

Примеры:

```text
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
AAPL global USD gradient theme=studio
gold silver palladium 2010-2026 RUB capital invest initial=0 monthly=30000 gradient
SiH4 futures 2024 close
USD000UTSTOM selt 2024 close
```

## Готовые сценарии для Пульса

Для быстрых шортсов можно не вспоминать тикеры и даты, а взять проверенный сценарий. Отправьте `/ideas`, и бот покажет список вместе с короткими русскими кнопками. Нажатие на кнопку сразу ставит выбранный сценарий в очередь, при этом текстовые команды `preset <name>` остаются стабильными.

После MP4 по preset-сценарию бот дополнительно отправляет текст для Пульса: хук, короткое описание, хэштеги, музыкальное/монтажное настроение и дисклеймер. Следующим сообщением бот показывает follow-up кнопки для этого же сценария: быстрый черновик 4s, полноценный шортс 16s и вариант 12s.

```text
/ideas
/drafts
/идеи
/черновики
follow-up: черновик 4s / шортс 16s / вариант 12s
preset metals
пресет металлы
металлы
черновик металлы
госы
экспортёры
черновик угольщики
preset neweconomy
preset vodka
preset mechel
preset wagons
preset bluechips
preset techru
```

Команды `preset <name>` и `пресет <имя>` делают то же самое текстом: разворачиваются в обычный запрос с тикерами, датами, валютой, инвестициями и темой. Для русских story-имен слово `пресет` можно опускать: `металлы`, `черновик металлы`, `голубые фишки`.

После имени можно дописать параметры, и они переопределят дефолт пресета:

```text
preset metals duration=12 theme=studio
металлы
черновик металлы
голубые фишки duration=12
госы
экспортёры duration=12
черновик угольщики
пресет металлы draft
сценарий голубые фишки duration=12
preset neweconomy from=2021-12-17 to=2026-06-01 fps=24
preset vodka monthly=50000
preset metals draft
```

Все preset-сценарии по умолчанию используют `shorts`: это короткий режим `duration=16`, `fps=24` и `gradient`. Если нужен другой темп, допишите свои `duration=` или `fps=` после имени preset. Для быстрой проверки идеи используйте `draft`: это черновой режим `duration=4`, `fps=8`, без `gradient`. Команды `/drafts` и `/черновики` показывают те же preset-кнопки, но каждая кнопка сразу запускает черновой прогон. Команды `/ideas` и `/идеи` показывают кнопки полноценного shorts-режима.

Текущие сценарии:

```text
neweconomy   SMLT / SGZH / POSI, новая экономика 2021-2026
metals       золото / серебро / палладий в RUB с monthly=30000
vodka        BELU / ABRD / KLVZ, алкогольные акции
mechel       MTLR / MTLRP, циклическая драма
wagons       UWGN / IMOEX, вагоны против рынка
stateowned   GAZP / AFLT / SNGS, госкомпании и длинная дистанция ожиданий
exporters    LKOH / PHOR / NLMK, экспортеры, рубль и сырьевые циклы
coalminers   MTLR / RASP, угольщики и циклическая волатильность
bluechips    SBER / LKOH / MGNT, понятная база для широкой аудитории
techru       YDEX / OZON / VKCO, российский технологический сюжет
```

## Даты

```text
2020 2024              с 01.01.2020 по 31.12.2024
2018-2026              короткий диапазон лет
from=2020-01-01        точная дата начала
to=2026-06-01          точная дата окончания
```

## Рынки и источники

```text
LKOH                   MOEX stock/shares по умолчанию
AAPL global            Yahoo Finance / global
GC=F                   Yahoo Finance futures
BTC-USD                Yahoo Finance crypto
SiH4 futures           MOEX futures/forts
USD000UTSTOM selt      MOEX currency/selt
```

Сокращения активов:

```text
gold / золото          GC=F
silver / серебро       SI=F
palladium              PA=F
oil / нефть            CL=F
btc / биткоин          BTC-USD
eth / эфир             ETH-USD
eurusd                 EURUSD=X
```

## Метрики и инвестиции

```text
close / price          цена закрытия
capital / reinvest     капитал с реинвестированием
invest                 добавить линию Invested
initial=0              стартовое вложение
monthly=30000          ежемесячное вложение
yearly=120000          ежегодное вложение
```

Если глобальный актив строится в `RUB`, цены сначала конвертируются в рубли, а `initial`, `monthly` и `yearly` считаются рублевыми взносами. Если график строится в `USD`, взносы считаются в долларах.

## Видео и стиль

```text
gradient               градиентный хвост линии
nogradient             обычная линия
nolegend               скрыть легенду
duration=12            длительность основной анимации
fps=24                 кадров в секунду
shorts                 короткий режим: duration=16 fps=24 gradient
draft                  быстрый черновик: duration=4 fps=8 без gradient
theme=default          базовая темная тема
theme=aurora           зелено-бирюзовая тема
theme=studio           контрастная студийная тема
```

На графике подписи у линий показывают текущую сумму. Нижние подписи показывают проценты по тикерам, а `Invested` показывает фактически вложенную сумму.

## Проверенные сценарии

Российские акции:

```text
SBER LKOH 2020 2024 RUB capital gradient
SMLT SGZH POSI from=2021-12-17 to=2026-06-01 RUB capital invest initial=0 monthly=30000 gradient
BELU ABRD KLVZ from=2024-02-22 to=2026-06-01 RUB capital invest initial=0 monthly=30000 gradient
```

Металлы:

```text
gold silver palladium from=2010-01-01 to=2026-05-27 RUB capital invest initial=0 monthly=30000 gradient theme=aurora
```

Иностранные акции:

```text
AAPL MSFT NVDA global USD capital gradient theme=studio
AAPL global RUB capital invest initial=0 monthly=30000 gradient
```

Фьючерсы и валюта MOEX:

```text
SiH4 futures 2024 close
USD000UTSTOM selt 2024 close
```

Криптовалюта:

```text
btc eth 2020-2026 USD close gradient
```

## Очередь и эксплуатация

Каждый запрос на генерацию получает `job id` вида `tg-123456`. Если отправить несколько сообщений подряд, бот обработает их последовательно, чтобы тяжелый рендер и скачивание данных не мешали друг другу.

Для подсказки отправьте:

```text
/help
```
