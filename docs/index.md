---
title: Главная
hide:
- feedback
---

<section class="sp-hero">
  <div class="sp-hero__content">
    <span class="sp-kicker">Stock Prices</span>
    <h1>Видео с рыночными графиками по одному сообщению в Telegram</h1>
    <p>
      Проект загружает данные по российским и глобальным инструментам, строит
      стильный анимированный график и возвращает готовый MP4 через CLI,
      Python API или постоянно работающего Telegram-бота.
    </p>
    <div class="sp-actions">
      <a class="sp-button sp-button--primary" href="runbook/">Запустить локально</a>
      <a class="sp-button" href="docker/">Запустить в Docker</a>
      <a class="sp-button" href="demo/">Посмотреть возможности</a>
    </div>
  </div>
</section>

<div class="sp-badges">
  <span>MOEX</span>
  <span>Yahoo Finance</span>
  <span>Telegram Bot API</span>
  <span>Matplotlib</span>
  <span>Docker Compose</span>
</div>

## Пример результата

<figure class="sp-media">
  <img src="assets/demo-sber-lkoh.gif" alt="Анимированный пример графика SBER и LKOH">
  <figcaption>Ускоренный GIF из реального MP4: видно, как график SBER и LKOH постепенно строится по всей истории.</figcaption>
</figure>

## Что умеет проект

<div class="sp-grid">
  <a class="sp-card" href="demo/#поддерживаемые-рынки-и-активы">
    <strong>Много рынков</strong>
    <span>Российские акции, фьючерсы, валюты, иностранные акции, металлы, криптовалюты и индексы.</span>
  </a>
  <a class="sp-card" href="runbook/#6-проверить-запросы-из-telegram">
    <strong>Удобная работа через Telegram</strong>
    <span>Достаточно написать тикер и параметры: бот сам сделает видео и отправит MP4.</span>
  </a>
  <a class="sp-card" href="docker/">
    <strong>Постоянный запуск</strong>
    <span>Docker-контейнер держит бота онлайн и автоматически перезапускается.</span>
  </a>
  <a class="sp-card" href="reference/api/">
    <strong>Единый pipeline</strong>
    <span>CLI, Telegram и Python API используют общий `generate_video()` без дублирования логики.</span>
  </a>
</div>

## Быстрый старт

=== "Docker"

    ```powershell
    copy .env.example .env
    docker compose up -d --build
    docker compose ps
    ```

=== "CLI"

    ```powershell
    python -m pip install -e .
    python -m stock_prices --tickers "SBER|stock|shares" "LKOH|stock|shares" --start_date 2020-01-01 --end_date 2024-12-31
    ```

=== "Telegram"

    ```text
    /start
    /menu
    /меню
    /shorts SBER LKOH за год
    /draft metals
    /ideas
    /drafts
    /идеи
    /черновики
    top drafts
    топ черновики
    top shorts
    top shorts studio
    top shorts aurora
    топ шортсы
    топ шортсы студио
    все шортсы
    /all_shorts
    случайный шортс
    random shorts
    /random_shorts
    случайный черновик
    random draft
    /random_draft
    /queue
    очередь
    /pack
    пакет пульса
    /kits
    пакеты
    SBER LKOH 2020 2024
    SBER LKOH за 10 лет shorts
    YDEX OZON за 6 месяцев shorts
    YDEX OZON за полгода shorts
    сделай шортс про SBER и LKOH за полгода для Пульса
    сравни SBER с LKOH за год шортс
    металлы
    металлы студио
    металлы студио 12с
    studio metals
    variants metals
    варианты металлы
    /kits
    пакеты
    kit metals
    пакет металлы
    черновик металлы
    госы
    экспортёры
    черновик угольщики
    банки
    дивиденды
    стройка студио
    preset metals
    пресет металлы
    preset neweconomy duration=12 theme=studio
    сценарий голубые фишки draft
    AAPL global USD shorts
    BTC price duration=12 fps=24
    gold silver palladium RUB capital invest initial=0 monthly=30000 gradient theme=aurora

    # одним сообщением, по строке на ролик:
    металлы
    черновик угольщики
    банки
    SBER LKOH 2020 2024 shorts
    ```

## Основные разделы

<div class="sp-grid sp-grid--small">
  <a class="sp-card" href="demo/">
    <strong>Демонстрация</strong>
    <span>Возможности, архитектура, рынки, примеры и сценарий показа проекта.</span>
  </a>
  <a class="sp-card" href="runbook/">
    <strong>Запуск и проверка</strong>
    <span>Пошаговый runbook для Windows/PowerShell, CLI, Telegram и диагностики.</span>
  </a>
  <a class="sp-card" href="telegram/">
    <strong>Telegram-запросы</strong>
    <span>Синтаксис сообщений, preset-кнопки, рынки, инвестиции, темы и готовый текст для Пульса.</span>
  </a>
  <a class="sp-card" href="docker/">
    <strong>Docker</strong>
    <span>Постоянный Telegram-бот, volume mounts, healthcheck и типовые ошибки.</span>
  </a>
  <a class="sp-card" href="reference/api/">
    <strong>API</strong>
    <span>Публичные Python-точки входа для интеграции генерации видео.</span>
  </a>
</div>

## Поддерживаемые запросы

```text
LKOH
SBER LKOH 2020 2024
SBER LKOH за 10 лет shorts
/shorts SBER LKOH за год
/draft metals
YDEX OZON за 6 месяцев shorts
YDEX OZON за полгода shorts
сделай шортс про SBER и LKOH за полгода для Пульса
сравни SBER с LKOH за год шортс
/menu
/меню
/start
/shorts SBER LKOH за год
/draft metals
/ideas
/drafts
/posts
/pack
/kits
/идеи
/черновики
посты
пакет пульса
пакеты
все черновики
все шортсы
/all_shorts
top drafts
топ черновики
top shorts
top shorts studio
top shorts aurora
variants metals
варианты металлы
/kits
пакеты
kit metals
пакет металлы
топ шортсы
топ шортсы студио
случайный шортс
random shorts
/random_shorts
случайный черновик
random draft
/random_draft
/queue
очередь
кнопка Статус очереди
статус показывает job id и короткий запрос
несколько строк одним сообщением: каждая строка - отдельная задача
Текст для Пульса после каждого MP4
post LKOH SBER 2020 2024 без рендера дает skeleton текста для Пульса
/posts открывает кнопки готовых текстовых пакетов без рендера
/shorts <запрос> ставит обычный запрос как shorts, /draft <запрос> ставит его как быстрый черновик
/pack показывает top-сценарии сразу в трех форматах: шортс, черновик, пост без рендера
/kits и пакеты открывают кнопочный список публикационных пакетов всех preset-сценариев без рендера
top shorts studio и top shorts aurora запускают всю top-серию в выбранной теме
все шортсы и /all_shorts запускают полноценные shorts-ролики по всей preset-библиотеке
variants metals и варианты металлы запускают один preset сразу в default, aurora и studio
kit metals и пакет металлы открывают action-пакет одного preset: шортс, черновик, все темы, 12s, пост
кнопки /menu открывают помощь, top-shorts сценарии, идеи, примеры, draft-прогоны и очередь
кнопки /ideas подписаны по-русски
follow-up кнопки после preset/custom-видео: черновик 4s / шортс 16s / вариант 12s / Aurora / Studio; после preset-видео еще Все темы
металлы
металлы студио
металлы студио 12с
studio metals
variants metals
варианты металлы
/kits
пакеты
kit metals
пакет металлы
черновик металлы
госы
экспортёры
черновик угольщики
банки
дивиденды
стройка студио
preset metals
пресет металлы
preset neweconomy duration=12 theme=studio
preset metals draft
AAPL global USD gradient
SBER LKOH shorts
gold 2018-2026 USD gradient
BTC-USD global crypto close
gold silver palladium RUB capital invest initial=0 monthly=30000 gradient theme=aurora
золото серебро палладий в рублях капитал каждый месяц 30к шортс
SiH4 futures 2024 close
USD000UTSTOM selt 2024 close
```

## Как устроено

```mermaid
flowchart TD
  User["Telegram / CLI / Python API"] --> Request["VideoRequest"]
  Request --> Sources{"Источник данных"}
  Sources --> Moex["MOEX: акции, фьючерсы, валюта"]
  Sources --> Global["Глобальные акции и ETF"]
  Sources --> Crypto["Криптовалюты, металлы, FX"]
  Moex --> Dataset["Единый датасет"]
  Global --> Dataset
  Crypto --> Dataset
  Dataset --> Render["Стильный график Matplotlib"]
  Render --> Video["MP4 через ffmpeg"]
  Video --> Output["Файл или ответ Telegram"]
```
