from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import random
import re
from typing import Protocol


class RandomLike(Protocol):
    def choice(self, seq): ...

    def randint(self, a: int, b: int) -> int: ...

    def sample(self, population, k: int): ...


@dataclass(frozen=True)
class TickerUniverseEntry:
    ticker: str
    engine: str
    market: str
    title: str
    available_from: date
    available_to: date | None
    categories: tuple[str, ...]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class GeneratedContentIdea:
    title: str
    request: str
    tickers: tuple[str, ...]
    category: str
    start_date: date
    end_date: date
    theme: str
    cover_text: str
    music_mood: str
    music_tracks: tuple[str, ...]
    post_text: str

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", "-".join(self.tickers).lower()).strip("-")


THEMES = ("default", "aurora", "studio")

MUSIC_BY_CATEGORY: dict[str, tuple[str, tuple[str, ...]]] = {
    "drama": ("напряженный synthwave / industrial beat", ("Kavinsky - Nightcall", "Gesaffelstein - Pursuit")),
    "growth": ("быстрый electronic groove", ("The Chemical Brothers - Galvanize", "Justice - Genesis")),
    "quiet": ("ровный pop / indie beat", ("Daft Punk - Instant Crush", "Phoenix - Lisztomania")),
    "commodities": ("cinematic beat с сильным финалом", ("M83 - Outro", "ODESZA - A Moment Apart")),
    "banks": ("уверенный минималистичный beat", ("The xx - Intro", "Tame Impala - Let It Happen")),
    "weekly": ("динамичный монтажный beat", ("Daft Punk - One More Time", "Woodkid - Run Boy Run")),
}

TICKER_UNIVERSE: tuple[TickerUniverseEntry, ...] = (
    TickerUniverseEntry("SBER", "stock", "shares", "Сбербанк", date(2010, 1, 11), None, ("ru", "banks", "bluechips", "quiet", "weekly")),
    TickerUniverseEntry("SBERP", "stock", "shares", "Сбербанк-п", date(2010, 1, 11), None, ("ru", "banks", "dividends", "quiet")),
    TickerUniverseEntry("VTBR", "stock", "shares", "ВТБ", date(2010, 1, 11), None, ("ru", "banks", "quiet", "drama")),
    TickerUniverseEntry("T", "stock", "shares", "Т-Технологии", date(2021, 10, 25), None, ("ru", "banks", "growth", "new_economy")),
    TickerUniverseEntry("LKOH", "stock", "shares", "Лукойл", date(2010, 1, 11), None, ("ru", "oil", "exporters", "bluechips", "commodities", "weekly")),
    TickerUniverseEntry("GAZP", "stock", "shares", "Газпром", date(2010, 1, 11), None, ("ru", "oil", "state", "bluechips", "drama")),
    TickerUniverseEntry("ROSN", "stock", "shares", "Роснефть", date(2010, 1, 11), None, ("ru", "oil", "state", "commodities")),
    TickerUniverseEntry("NVTK", "stock", "shares", "Новатэк", date(2010, 1, 11), None, ("ru", "oil", "growth", "commodities")),
    TickerUniverseEntry("MTLR", "stock", "shares", "Мечел", date(2010, 1, 11), None, ("ru", "coal", "commodities", "drama", "weekly")),
    TickerUniverseEntry("MTLRP", "stock", "shares", "Мечел-п", date(2010, 1, 11), None, ("ru", "coal", "commodities", "drama")),
    TickerUniverseEntry("RASP", "stock", "shares", "Распадская", date(2010, 1, 11), None, ("ru", "coal", "commodities", "drama")),
    TickerUniverseEntry("NLMK", "stock", "shares", "НЛМК", date(2010, 1, 11), None, ("ru", "steel", "exporters", "commodities", "weekly")),
    TickerUniverseEntry("CHMF", "stock", "shares", "Северсталь", date(2010, 1, 11), None, ("ru", "steel", "dividends", "commodities")),
    TickerUniverseEntry("MAGN", "stock", "shares", "ММК", date(2010, 1, 11), None, ("ru", "steel", "commodities")),
    TickerUniverseEntry("GMKN", "stock", "shares", "Норникель", date(2010, 1, 11), None, ("ru", "metals", "commodities", "bluechips")),
    TickerUniverseEntry("PLZL", "stock", "shares", "Полюс", date(2010, 1, 11), None, ("ru", "metals", "gold", "commodities", "growth")),
    TickerUniverseEntry("PHOR", "stock", "shares", "ФосАгро", date(2011, 7, 18), None, ("ru", "fertilizers", "exporters", "commodities", "weekly")),
    TickerUniverseEntry("AKRN", "stock", "shares", "Акрон", date(2010, 1, 11), None, ("ru", "fertilizers", "commodities", "quiet")),
    TickerUniverseEntry("SNGS", "stock", "shares", "Сургутнефтегаз", date(2010, 1, 11), None, ("ru", "oil", "state", "quiet")),
    TickerUniverseEntry("SNGSP", "stock", "shares", "Сургутнефтегаз-п", date(2010, 1, 11), None, ("ru", "oil", "dividends", "quiet")),
    TickerUniverseEntry("MGNT", "stock", "shares", "Магнит", date(2010, 1, 11), None, ("ru", "retail", "bluechips", "quiet", "weekly")),
    TickerUniverseEntry("MVID", "stock", "shares", "М.Видео", date(2010, 1, 11), None, ("ru", "retail", "drama")),
    TickerUniverseEntry("FIXP", "stock", "shares", "Fix Price", date(2021, 3, 10), None, ("ru", "retail", "growth", "new_economy")),
    TickerUniverseEntry("FIVE", "stock", "shares", "X5", date(2018, 2, 1), None, ("ru", "retail", "quiet")),
    TickerUniverseEntry("OZON", "stock", "shares", "Ozon", date(2020, 11, 24), None, ("ru", "retail", "growth", "new_economy")),
    TickerUniverseEntry("SMLT", "stock", "shares", "Самолет", date(2020, 10, 29), None, ("ru", "builders", "growth", "drama", "new_economy", "weekly")),
    TickerUniverseEntry("PIKK", "stock", "shares", "ПИК", date(2010, 1, 11), None, ("ru", "builders", "quiet")),
    TickerUniverseEntry("LSRG", "stock", "shares", "ЛСР", date(2010, 1, 11), None, ("ru", "builders", "quiet")),
    TickerUniverseEntry("SGZH", "stock", "shares", "Сегежа", date(2021, 4, 28), None, ("ru", "new_economy", "drama", "weekly")),
    TickerUniverseEntry("POSI", "stock", "shares", "Positive Technologies", date(2021, 12, 17), None, ("ru", "new_economy", "growth", "weekly")),
    TickerUniverseEntry("ASTR", "stock", "shares", "Астра", date(2023, 10, 13), None, ("ru", "new_economy", "growth")),
    TickerUniverseEntry("DIAS", "stock", "shares", "Диасофт", date(2024, 2, 13), None, ("ru", "new_economy", "growth")),
    TickerUniverseEntry("BELU", "stock", "shares", "Белуга", date(2010, 1, 11), None, ("ru", "alcohol", "quiet", "drama")),
    TickerUniverseEntry("ABRD", "stock", "shares", "Абрау-Дюрсо", date(2012, 4, 11), None, ("ru", "alcohol", "quiet")),
    TickerUniverseEntry("KLVZ", "stock", "shares", "Кристалл", date(2024, 2, 22), None, ("ru", "alcohol", "drama")),
    TickerUniverseEntry("UWGN", "stock", "shares", "ОВК", date(2015, 4, 30), None, ("ru", "transport", "drama", "growth")),
    TickerUniverseEntry("AFLT", "stock", "shares", "Аэрофлот", date(2010, 1, 11), None, ("ru", "transport", "state", "drama")),
    TickerUniverseEntry("TRNFP", "stock", "shares", "Транснефть-п", date(2010, 1, 11), None, ("ru", "transport", "dividends", "quiet")),
    TickerUniverseEntry("MTSS", "stock", "shares", "МТС", date(2010, 1, 11), None, ("ru", "telecom", "dividends", "quiet")),
    TickerUniverseEntry("RTKM", "stock", "shares", "Ростелеком", date(2010, 1, 11), None, ("ru", "telecom", "quiet")),
    TickerUniverseEntry("IRAO", "stock", "shares", "Интер РАО", date(2010, 1, 11), None, ("ru", "utilities", "quiet")),
    TickerUniverseEntry("HYDR", "stock", "shares", "РусГидро", date(2010, 1, 11), None, ("ru", "utilities", "quiet")),
    TickerUniverseEntry("FEES", "stock", "shares", "ФСК", date(2010, 1, 11), None, ("ru", "utilities", "quiet")),
    TickerUniverseEntry("GC=F", "global", "metals", "Золото", date(2000, 8, 30), None, ("global", "metals", "commodities", "weekly")),
    TickerUniverseEntry("SI=F", "global", "metals", "Серебро", date(2000, 8, 30), None, ("global", "metals", "commodities")),
    TickerUniverseEntry("PA=F", "global", "metals", "Палладий", date(2000, 1, 4), None, ("global", "metals", "commodities", "drama")),
    TickerUniverseEntry("PL=F", "global", "metals", "Платина", date(2000, 1, 4), None, ("global", "metals", "commodities")),
    TickerUniverseEntry("CL=F", "global", "commodities", "Нефть WTI", date(2000, 8, 23), None, ("global", "oil", "commodities", "drama")),
    TickerUniverseEntry("AAPL", "global", "stocks", "Apple", date(2010, 1, 4), None, ("global", "stocks", "growth", "weekly")),
    TickerUniverseEntry("MSFT", "global", "stocks", "Microsoft", date(2010, 1, 4), None, ("global", "stocks", "growth")),
    TickerUniverseEntry("NVDA", "global", "stocks", "NVIDIA", date(2010, 1, 4), None, ("global", "stocks", "growth", "drama")),
    TickerUniverseEntry("TSLA", "global", "stocks", "Tesla", date(2010, 6, 29), None, ("global", "stocks", "growth", "drama")),
    TickerUniverseEntry("BTC-USD", "global", "crypto", "Bitcoin", date(2014, 9, 17), None, ("global", "crypto", "growth", "drama")),
    TickerUniverseEntry("ETH-USD", "global", "crypto", "Ethereum", date(2017, 11, 9), None, ("global", "crypto", "growth", "drama")),
)


def entries_for_category(category: str | None = None) -> tuple[TickerUniverseEntry, ...]:
    if category is None:
        return TICKER_UNIVERSE
    normalized = category.lower().replace("-", "_")
    return tuple(entry for entry in TICKER_UNIVERSE if normalized in entry.categories)


def _entry_end(entry: TickerUniverseEntry, today: date) -> date:
    if entry.available_to is None:
        return today
    return min(entry.available_to, today)


def _common_period(entries: tuple[TickerUniverseEntry, ...], today: date) -> tuple[date, date]:
    return max(entry.available_from for entry in entries), min(_entry_end(entry, today) for entry in entries)


def _has_min_years(entries: tuple[TickerUniverseEntry, ...], today: date, min_years: int) -> bool:
    start, end = _common_period(entries, today)
    return (end - start).days >= min_years * 365


def _pick_entries(
    category: str | None,
    count: int | None,
    rng: RandomLike,
    today: date,
    min_years: int,
) -> tuple[TickerUniverseEntry, ...]:
    candidates = tuple(
        entry for entry in entries_for_category(category) if entry.available_from <= today and _entry_end(entry, today) >= entry.available_from
    )
    if not candidates:
        candidates = tuple(
            entry for entry in entries_for_category(None) if entry.available_from <= today and _entry_end(entry, today) >= entry.available_from
        )
    max_count = min(count or rng.randint(1, 3), len(candidates))
    for years in (min_years, 5, 2, 0):
        for _attempt in range(120):
            sample_size = min(max_count, len(candidates))
            selected = tuple(rng.sample(candidates, sample_size))
            if _has_min_years(selected, today, years):
                return selected
    return tuple(rng.sample(candidates, min(max_count, len(candidates))))


def _idea_title(entries: tuple[TickerUniverseEntry, ...], category: str) -> str:
    if len(entries) == 1:
        return f"{entries[0].ticker}: одиночная история"
    readable = " / ".join(entry.ticker for entry in entries)
    return f"{readable}: случайное сравнение"


def _build_request(
    entries: tuple[TickerUniverseEntry, ...],
    start_date: date,
    end_date: date,
    theme: str,
    mode: str,
    monthly: int,
) -> str:
    tickers = " ".join(
        entry.ticker if (entry.engine, entry.market) == ("stock", "shares") else f"{entry.ticker}|{entry.engine}|{entry.market}"
        for entry in entries
    )
    title = "_".join(entry.ticker.replace("=", "").replace("-", "") for entry in entries)
    visual_mode = f"gradient {mode}" if mode == "shorts" else mode
    return (
        f"{tickers} from={start_date.isoformat()} to={end_date.isoformat()} RUB capital invest "
        f"initial=0 monthly={monthly} {visual_mode} theme={theme} title={title}"
    )


def build_random_content_idea(
    category: str | None = None,
    *,
    count: int | None = None,
    rng: RandomLike | None = None,
    today: date | None = None,
    mode: str = "shorts",
    theme: str | None = None,
    monthly: int = 30_000,
    min_years: int = 10,
) -> GeneratedContentIdea:
    active_rng = rng or random.SystemRandom()
    active_today = today or date.today()
    selected = _pick_entries(category, count, active_rng, active_today, min_years)
    start_date, end_date = _common_period(selected, active_today)
    active_theme = theme or active_rng.choice(THEMES)
    active_category = category or active_rng.choice(selected[0].categories)
    title = _idea_title(selected, active_category)
    music_mood, music_tracks = MUSIC_BY_CATEGORY.get(active_category, MUSIC_BY_CATEGORY["weekly"])
    tickers = tuple(entry.ticker for entry in selected)
    request = _build_request(selected, start_date, end_date, active_theme, mode, monthly)
    cover = f"{' / '.join(tickers)}: что сделал DCA?"
    post = (
        f"Случайная подборка из тикерной вселенной: {' / '.join(entry.title for entry in selected)}. "
        f"Период выбран по пересечению доступной истории: {start_date:%d.%m.%Y} - {end_date:%d.%m.%Y}. "
        f"Сценарий считает регулярные покупки по {monthly:,} ₽ в месяц."
    ).replace(",", " ")
    return GeneratedContentIdea(
        title=title,
        request=request,
        tickers=tickers,
        category=active_category,
        start_date=start_date,
        end_date=end_date,
        theme=active_theme,
        cover_text=cover,
        music_mood=music_mood,
        music_tracks=music_tracks,
        post_text=post,
    )


def build_weekly_content_plan(today: date | None = None) -> tuple[GeneratedContentIdea, ...]:
    active_today = today or date.today()
    year, week, _day = active_today.isocalendar()
    plan_date = date.fromisocalendar(year, week, 1)
    rng = random.Random(f"{year}-W{week}")
    categories = ("banks", "commodities", "quiet", "drama", "growth", "retail", "new_economy")
    return tuple(
        build_random_content_idea(category, rng=rng, today=plan_date, theme=rng.choice(THEMES))
        for category in categories
    )
