from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime

from stock_prices._internal.models import RenderSettings, TickerSpec, VideoRequest, parse_ticker_spec


@dataclass(frozen=True)
class ParsedTelegramRequest:
    request: VideoRequest
    display_name: str


_CURRENCIES = {"RUB", "USD", "EUR", "CNY", "GBP", "JPY", "CHF"}
_ENGINES = {"stock", "global", "currency"}
_BOOL_TRUE = {"1", "true", "yes", "y", "on", "да"}
_BOOL_FALSE = {"0", "false", "no", "n", "off", "нет"}
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
    "PALLADIUM": ("PA=F", "metals"),
    "COPPER": ("HG=F", "metals"),
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


def _looks_like_ticker(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9^][A-Za-z0-9._=\-/^]{0,20}", token))


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
        elif key:
            raise ValueError(f"Unknown option: {key}")
        elif "|" in token:
            specs.append(parse_ticker_spec(token, engine, market))
        elif (parsed_date := _parse_date_token(token, end=len(positional_dates) == 1)) is not None:
            positional_dates.append(parsed_date)
        elif lowered in {"gradient", "градиент"}:
            updates["use_gradient"] = True
        elif lowered in {"nogradient", "no_gradient", "line", "линия"}:
            updates["use_gradient"] = False
        elif lowered in {"close", "price", "цена"}:
            updates["value_col"] = "CLOSE"
        elif lowered in {"capital", "reinvest", "капитал"}:
            updates["value_col"] = "CAPITAL_REINVEST"
        elif lowered in {"invest", "investments", "инвестиции"}:
            updates["with_investments"] = True
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
    return ParsedTelegramRequest(VideoRequest(specs, render), display_name)
