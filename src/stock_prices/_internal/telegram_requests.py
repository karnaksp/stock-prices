from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, datetime

from stock_prices._internal.models import RenderSettings, TickerSpec, VideoRequest, parse_ticker_spec
from stock_prices._internal.rendering.theme import get_theme_names
from stock_prices._internal.telegram_presets import expand_preset_text


@dataclass(frozen=True)
class ParsedTelegramRequest:
    request: VideoRequest
    display_name: str
    preset_name: str | None = None


_CURRENCIES = {"RUB", "USD", "EUR", "CNY", "GBP", "JPY", "CHF"}
_ENGINES = {"stock", "global", "currency"}
_BOOL_TRUE = {"1", "true", "yes", "y", "on", "да"}
_BOOL_FALSE = {"0", "false", "no", "n", "off", "нет"}
_CURRENCY_WORDS = {
    "руб": "RUB",
    "рубль": "RUB",
    "рубля": "RUB",
    "рублей": "RUB",
    "рубли": "RUB",
    "рублях": "RUB",
    "₽": "RUB",
    "доллар": "USD",
    "доллара": "USD",
    "долларов": "USD",
    "доллары": "USD",
    "долларах": "USD",
    "$": "USD",
    "евро": "EUR",
    "юань": "CNY",
    "юаня": "CNY",
    "юаней": "CNY",
}
_DATE_FROM_WORDS = {"с", "от"}
_DATE_TO_WORDS = {"по", "до"}
_RELATIVE_PERIOD_WORDS = {"за", "last", "последнее", "последний", "последние", "последних", "последнюю"}
_MONTH_WORDS = {"month", "months", "месяц", "месяца", "месяцев", "мес"}
_YEAR_WORDS = {"year", "years", "год", "года", "лет"}
_SINGLE_RELATIVE_PERIODS = {
    "month": (1, "month"),
    "месяц": (1, "month"),
    "мес": (1, "month"),
    "полгода": (6, "month"),
    "полугодие": (6, "month"),
    "year": (1, "year"),
    "год": (1, "year"),
}
_MONTHLY_WORDS = {"monthly", "ежемесячно", "помесячно"}
_YEARLY_WORDS = {"yearly", "ежегодно", "ежегодный"}
_INITIAL_WORDS = {
    "initial",
    "старт",
    "стартовый",
    "начальный",
    "начальное",
    "первоначальный",
    "первоначально",
    "сначала",
}
_INVEST_WORDS = {
    "invest",
    "investments",
    "инвестиции",
    "инвестируя",
    "инвестировать",
    "вкладывать",
    "вкладывая",
    "вложения",
    "вложение",
    "вложений",
}
_IGNORED_REQUEST_WORDS = {
    "a",
    "about",
    "and",
    "an",
    "chart",
    "compare",
    "for",
    "make",
    "of",
    "show",
    "the",
    "video",
    "акции",
    "акций",
    "акция",
    "видео",
    "график",
    "для",
    "и",
    "или",
    "нарисуй",
    "покажи",
    "показать",
    "построй",
    "про",
    "пульс",
    "пульса",
    "ролик",
    "сделай",
    "сделать",
    "собери",
    "создай",
    "сравнение",
    "сравни",
    "сравнить",
    "тикер",
    "тикера",
    "тикерам",
    "тикеры",
}
SHORTS_DURATION = 16
SHORTS_FPS = 24
DRAFT_DURATION = 4
DRAFT_FPS = 8
_GLOBAL_ALIASES = {
    "BTC": ("BTC-USD", "crypto"),
    "БИТКОИН": ("BTC-USD", "crypto"),
    "ETH": ("ETH-USD", "crypto"),
    "ЭФИР": ("ETH-USD", "crypto"),
    "SOL": ("SOL-USD", "crypto"),
    "BNB": ("BNB-USD", "crypto"),
    "DOGE": ("DOGE-USD", "crypto"),
    "GOLD": ("GC=F", "metals"),
    "ЗОЛОТО": ("GC=F", "metals"),
    "XAU": ("GC=F", "metals"),
    "SILVER": ("SI=F", "metals"),
    "СЕРЕБРО": ("SI=F", "metals"),
    "XAG": ("SI=F", "metals"),
    "PLATINUM": ("PL=F", "metals"),
    "ПЛАТИНА": ("PL=F", "metals"),
    "PALLADIUM": ("PA=F", "metals"),
    "ПАЛЛАДИЙ": ("PA=F", "metals"),
    "COPPER": ("HG=F", "metals"),
    "МЕДЬ": ("HG=F", "metals"),
    "OIL": ("CL=F", "commodities"),
    "НЕФТЬ": ("CL=F", "commodities"),
    "WTI": ("CL=F", "commodities"),
    "BRENT": ("BZ=F", "commodities"),
    "EURUSD": ("EURUSD=X", "currency"),
    "ЕВРОДОЛЛАР": ("EURUSD=X", "currency"),
    "USDRUB": ("USDRUB=X", "currency"),
    "USDEUR": ("USDEUR=X", "currency"),
    "USDJPY": ("USDJPY=X", "currency"),
    "GBPUSD": ("GBPUSD=X", "currency"),
}


def _tokenize(text: str) -> list[str]:
    cleaned = re.sub(r"[,;\n]+", " ", text.strip())
    return [token for token in cleaned.split() if token]


def _parse_date_token(token: str, *, end: bool = False) -> date | None:
    if re.fullmatch(r"\d{4}", token):
        year = int(token)
        return date(year, 12, 31) if end else date(year, 1, 1)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
        return datetime.strptime(token, "%Y-%m-%d").date()
    return None


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _BOOL_TRUE:
        return True
    if normalized in _BOOL_FALSE:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def _parse_int(value: str, minimum: int, maximum: int, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    return max(minimum, min(parsed, maximum))


def _shift_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def _shift_months(value: date, months: int) -> date:
    target_month_index = value.year * 12 + value.month - 1 - months
    year = target_month_index // 12
    month = target_month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _read_amount(tokens: list[str], idx: int) -> tuple[int | None, int, str | None]:
    if idx >= len(tokens):
        return None, idx, None
    first = tokens[idx].replace("_", "")
    if not first.isdigit():
        return None, idx, None

    amount_parts = [first]
    idx += 1
    if len(first) <= 3:
        while idx < len(tokens):
            group = tokens[idx].replace("_", "")
            if not re.fullmatch(r"\d{3}", group):
                break
            amount_parts.append(group)
            idx += 1

    currency = None
    if idx < len(tokens):
        currency = _CURRENCY_WORDS.get(tokens[idx].strip().lower())
        if currency is not None:
            idx += 1

    return int("".join(amount_parts)), idx, currency


def _read_amount_after_optional_po(tokens: list[str], idx: int) -> tuple[int | None, int, str | None]:
    if idx < len(tokens) and tokens[idx].strip().lower() == "по":
        idx += 1
    return _read_amount(tokens, idx)


def _has_period_word_after_amount(tokens: list[str], idx: int, words: set[str]) -> tuple[bool, int]:
    if idx < len(tokens) and tokens[idx].strip().lower() == "в":
        idx += 1
    if idx < len(tokens) and tokens[idx].strip().lower() in words:
        return True, idx + 1
    return False, idx


def _set_investment_amount(
    updates: dict[str, object],
    field: str,
    amount: int,
    currency: str | None,
    name: str,
) -> None:
    updates[field] = _parse_int(str(amount), 0, 1_000_000_000, name)
    updates["with_investments"] = True
    if currency is not None:
        updates["currency"] = currency


def _looks_like_ticker(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9^][A-Za-z0-9._=\-/^]{0,20}", token))


def _is_ignored_request_word(token: str) -> bool:
    lowered = token.strip().lower()
    if lowered not in _IGNORED_REQUEST_WORDS:
        return False
    return not (token.isascii() and token.isupper())


def _set_relative_period(updates: dict[str, object], base_render: RenderSettings, amount: int, unit: str) -> None:
    updates["end_date"] = base_render.end_date
    if unit == "month":
        updates["start_date"] = _shift_months(base_render.end_date, amount)
    else:
        updates["start_date"] = _shift_years(base_render.end_date, amount)


def _spec_from_ticker(raw_ticker: str, engine: str, market: str) -> TickerSpec:
    normalized = raw_ticker.upper().replace("/", "")
    if normalized in _GLOBAL_ALIASES:
        alias_ticker, alias_market = _GLOBAL_ALIASES[normalized]
        return TickerSpec(alias_ticker, "global", alias_market)
    if raw_ticker.startswith("^") or "=" in raw_ticker or normalized.endswith("-USD"):
        inferred_market = "crypto" if normalized.endswith("-USD") else "futures" if normalized.endswith("=F") else "currency"
        return TickerSpec(raw_ticker, "global", inferred_market)
    return TickerSpec(raw_ticker, engine, market)


def parse_telegram_video_request(
    text: str,
    base_render: RenderSettings,
    default_engine: str = "stock",
    default_market: str = "shares",
) -> ParsedTelegramRequest:
    text, preset = expand_preset_text(text)
    tokens = _tokenize(text)
    if tokens and tokens[0].startswith("/"):
        tokens = tokens[1:]

    engine = default_engine
    market = default_market
    raw_tickers: list[str] = []
    specs: list[TickerSpec] = []
    positional_dates: list[date] = []
    updates: dict[str, object] = {}
    title: str | None = None

    idx = 0
    while idx < len(tokens):
        token = tokens[idx].strip()
        lowered = token.lower()
        key = ""
        value = ""

        year_range = re.fullmatch(r"(\d{4})[-:](\d{4})", token)
        if year_range:
            positional_dates.append(date(int(year_range.group(1)), 1, 1))
            positional_dates.append(date(int(year_range.group(2)), 12, 31))
            idx += 1
            continue

        if "=" in token:
            possible_key, possible_value = token.split("=", 1)
            possible_key = possible_key.strip().lower().replace("-", "_")
            if possible_key in {
                "from",
                "start",
                "start_date",
                "s",
                "to",
                "end",
                "end_date",
                "t",
                "duration",
                "seconds",
                "d",
                "fps",
                "currency",
                "cur",
                "value",
                "value_col",
                "metric",
                "engine",
                "market",
                "initial",
                "initial_investment",
                "monthly",
                "monthly_investment",
                "month",
                "yearly",
                "yearly_investment",
                "year",
                "gradient",
                "legend",
                "show_legend",
                "title",
                "theme",
            }:
                key = possible_key
                value = possible_value.strip()

        if key in {"from", "start", "start_date", "s"}:
            parsed_date = _parse_date_token(value)
            if parsed_date is None:
                raise ValueError(f"Invalid start date: {value}")
            updates["start_date"] = parsed_date
        elif key in {"to", "end", "end_date", "t"}:
            parsed_date = _parse_date_token(value, end=True)
            if parsed_date is None:
                raise ValueError(f"Invalid end date: {value}")
            updates["end_date"] = parsed_date
        elif key in {"duration", "seconds", "d"}:
            updates["duration"] = _parse_int(value, 1, 90, "duration")
        elif key == "fps":
            updates["fps"] = _parse_int(value, 1, 30, "fps")
        elif key in {"currency", "cur"}:
            updates["currency"] = value.upper()
        elif key in {"value", "value_col", "metric"}:
            updates["value_col"] = value.upper()
        elif key == "engine":
            engine = value.lower()
        elif key == "market":
            market = value.lower()
        elif key in {"initial", "initial_investment"}:
            updates["initial_investment"] = _parse_int(value, 0, 1_000_000_000, "initial")
        elif key in {"monthly", "monthly_investment", "month"}:
            updates["monthly_investment"] = _parse_int(value, 0, 1_000_000_000, "monthly")
        elif key in {"yearly", "yearly_investment", "year"}:
            updates["yearly_investment"] = _parse_int(value, 0, 1_000_000_000, "yearly")
        elif key == "gradient":
            updates["use_gradient"] = _parse_bool(value)
        elif key in {"legend", "show_legend"}:
            updates["show_legend"] = _parse_bool(value)
        elif key == "title":
            title = value.replace("_", " ")
        elif key == "theme":
            theme = value.lower()
            if theme not in get_theme_names():
                raise ValueError(f"Unknown theme: {value}")
            updates["theme"] = theme
        elif key:
            raise ValueError(f"Unknown option: {key}")
        elif "|" in token:
            specs.append(parse_ticker_spec(token, engine, market))
        elif lowered in _DATE_FROM_WORDS and idx + 1 < len(tokens):
            parsed_date = _parse_date_token(tokens[idx + 1])
            if parsed_date is None:
                if lowered == "с":
                    pass
                else:
                    raise ValueError(f"Invalid start date: {tokens[idx + 1]}")
            else:
                updates["start_date"] = parsed_date
                idx += 1
        elif lowered in _DATE_TO_WORDS and idx + 1 < len(tokens):
            parsed_date = _parse_date_token(tokens[idx + 1], end=True)
            if parsed_date is not None:
                updates["end_date"] = parsed_date
                idx += 1
            else:
                amount, next_idx, amount_currency = _read_amount(tokens, idx + 1)
                has_month, final_idx = _has_period_word_after_amount(tokens, next_idx, _MONTH_WORDS)
                has_year = False
                if not has_month:
                    has_year, final_idx = _has_period_word_after_amount(tokens, next_idx, _YEAR_WORDS)
                if amount is None or not (has_month or has_year):
                    raise ValueError(f"Cannot parse token: {token}")
                if has_month:
                    _set_investment_amount(updates, "monthly_investment", amount, amount_currency, "monthly")
                else:
                    _set_investment_amount(updates, "yearly_investment", amount, amount_currency, "yearly")
                idx = final_idx - 1
        elif lowered in _RELATIVE_PERIOD_WORDS and idx + 1 < len(tokens):
            next_word = tokens[idx + 1].strip().lower()
            single_period = _SINGLE_RELATIVE_PERIODS.get(next_word)
            if single_period is not None:
                amount, unit = single_period
                _set_relative_period(updates, base_render, amount, unit)
                idx += 2
                continue
            if idx + 2 >= len(tokens):
                raise ValueError(f"Cannot parse token: {token}")
            amount = tokens[idx + 1].strip().replace("_", "")
            period_word = tokens[idx + 2].strip().lower()
            if not amount.isdigit() or period_word not in _MONTH_WORDS | _YEAR_WORDS:
                raise ValueError(f"Cannot parse token: {token}")
            if period_word in _MONTH_WORDS:
                months = _parse_int(amount, 1, 1200, "months")
                _set_relative_period(updates, base_render, months, "month")
            else:
                years = _parse_int(amount, 1, 100, "years")
                _set_relative_period(updates, base_render, years, "year")
            idx += 2
        elif (parsed_date := _parse_date_token(token, end=len(positional_dates) == 1)) is not None:
            positional_dates.append(parsed_date)
        elif lowered in {"gradient", "градиент"}:
            updates["use_gradient"] = True
        elif lowered in {"nogradient", "no_gradient", "line", "линия"}:
            updates["use_gradient"] = False
        elif lowered in {"short", "shorts", "reels", "шорт", "шортс", "шортсы"}:
            updates["duration"] = SHORTS_DURATION
            updates["fps"] = SHORTS_FPS
            updates["use_gradient"] = True
        elif lowered in {"draft", "preview", "черновик", "превью"}:
            updates["duration"] = DRAFT_DURATION
            updates["fps"] = DRAFT_FPS
            updates["use_gradient"] = False
        elif lowered in {"close", "price", "цена"}:
            updates["value_col"] = "CLOSE"
        elif lowered in {"capital", "reinvest", "капитал", "капитала", "капитализация"}:
            updates["value_col"] = "CAPITAL_REINVEST"
        elif lowered in _INVEST_WORDS:
            updates["with_investments"] = True
        elif lowered in _MONTHLY_WORDS:
            amount, next_idx, amount_currency = _read_amount_after_optional_po(tokens, idx + 1)
            if amount is None:
                raise ValueError("monthly must be an integer.")
            _set_investment_amount(updates, "monthly_investment", amount, amount_currency, "monthly")
            idx = next_idx - 1
        elif lowered in _YEARLY_WORDS:
            amount, next_idx, amount_currency = _read_amount_after_optional_po(tokens, idx + 1)
            if amount is None:
                raise ValueError("yearly must be an integer.")
            _set_investment_amount(updates, "yearly_investment", amount, amount_currency, "yearly")
            idx = next_idx - 1
        elif lowered in _INITIAL_WORDS:
            amount, next_idx, amount_currency = _read_amount_after_optional_po(tokens, idx + 1)
            if amount is None:
                raise ValueError("initial must be an integer.")
            _set_investment_amount(updates, "initial_investment", amount, amount_currency, "initial")
            idx = next_idx - 1
        elif lowered in {"каждый", "каждую"} and idx + 1 < len(tokens):
            period_word = tokens[idx + 1].strip().lower()
            if period_word not in _MONTH_WORDS | _YEAR_WORDS:
                raise ValueError(f"Cannot parse token: {token}")
            amount, next_idx, amount_currency = _read_amount_after_optional_po(tokens, idx + 2)
            if amount is None:
                raise ValueError("Investment amount is missing.")
            if period_word in _MONTH_WORDS:
                _set_investment_amount(updates, "monthly_investment", amount, amount_currency, "monthly")
            else:
                _set_investment_amount(updates, "yearly_investment", amount, amount_currency, "yearly")
            idx = next_idx - 1
        elif lowered == "в" and idx + 1 < len(tokens) and tokens[idx + 1].strip().lower() in _CURRENCY_WORDS:
            updates["currency"] = _CURRENCY_WORDS[tokens[idx + 1].strip().lower()]
            idx += 1
        elif lowered == "в" and idx + 1 < len(tokens) and tokens[idx + 1].strip().lower() in _MONTH_WORDS | _YEAR_WORDS:
            idx += 1
        elif lowered in _CURRENCY_WORDS:
            updates["currency"] = _CURRENCY_WORDS[lowered]
        elif lowered in {"nolegend", "no_legend"}:
            updates["show_legend"] = False
        elif token.upper() in _CURRENCIES:
            updates["currency"] = token.upper()
        elif lowered in {"future", "futures", "forts", "фьючерс", "фьючерсы"}:
            engine = "futures"
            market = "forts"
        elif lowered in {"crypto", "metals", "commodities"}:
            engine = "global"
            market = lowered
        elif lowered == "selt":
            engine = "currency"
            market = "selt"
        elif lowered in {"shares", "bonds", "index"}:
            engine = "stock"
            market = lowered
        elif lowered in _ENGINES:
            engine = lowered
        elif _is_ignored_request_word(token):
            pass
        elif token.upper().replace("/", "") in _GLOBAL_ALIASES:
            raw_tickers.append(token)
        elif _looks_like_ticker(token):
            raw_tickers.append(token)
        else:
            raise ValueError(f"Cannot parse token: {token}")
        idx += 1

    if positional_dates:
        updates["start_date"] = positional_dates[0]
    if len(positional_dates) >= 2:
        updates["end_date"] = positional_dates[1]

    specs.extend(_spec_from_ticker(ticker, engine, market) for ticker in raw_tickers)
    if not specs:
        raise ValueError("Send at least one ticker, for example: LKOH")

    render = replace(base_render, **updates)
    display_name = " / ".join(spec.ticker for spec in specs)
    render = replace(render, title=title or render.title or display_name)
    return ParsedTelegramRequest(VideoRequest(specs, render), display_name, preset.name if preset else None)
