from __future__ import annotations

from datetime import date, datetime
from typing import Any

import apimoex
import requests

from stock_prices._internal.content_universe import TickerUniverseEntry

MOEX_SHARE_BOARD = "TQBR"
MOEX_SHARE_COLUMNS = (
    "SECID",
    "SHORTNAME",
    "SECNAME",
    "ISIN",
    "SECTYPE",
    "LISTLEVEL",
)


def _parse_moex_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def _moex_period_from_candle_borders(rows: list[dict[str, Any]], today: date) -> tuple[date, date | None] | None:
    starts: list[date] = []
    ends: list[date] = []
    for row in rows:
        start = _parse_moex_date(row.get("begin") or row.get("from") or row.get("start"))
        end = _parse_moex_date(row.get("end") or row.get("till") or row.get("finish"))
        if start is not None:
            starts.append(start)
        if end is not None:
            ends.append(end)
    if not starts:
        return None
    return min(starts), min(max(ends), today) if ends else None


def _classify_moex_share(secid: str, title: str) -> tuple[str, ...]:
    text = f"{secid} {title}".lower()
    categories = ["ru", "moex", "stocks"]
    if any(word in text for word in ("банк", "сбер", "втб", "финанс", "bank")):
        categories.append("banks")
    if any(word in text for word in ("нефт", "газ", "лукойл", "роснефт", "сургут", "oil", "gaz")):
        categories.extend(("oil", "commodities"))
    if any(word in text for word in ("метал", "сталь", "никель", "золото", "уголь", "мечел", "steel", "gold")):
        categories.extend(("metals", "commodities"))
    if any(word in text for word in ("ритейл", "магнит", "x5", "ozon", "fix", "retail")):
        categories.append("retail")
    if any(word in text for word in ("самолет", "пик", "лср", "стро", "developer")):
        categories.append("builders")
    if any(word in text for word in ("технолог", "софт", "positive", "ozon", "astra", "tech")):
        categories.extend(("growth", "new_economy"))
    if any(word in text for word in ("водк", "белуг", "абрау", "кристалл", "alcohol")):
        categories.append("alcohol")
    if any(word in text for word in ("овк", "вагон", "аэрофлот", "транс", "transport")):
        categories.append("transport")
    if any(word in text for word in ("ростелеком", "мтс", "телеком", "telecom")):
        categories.append("telecom")
    if any(word in text for word in ("интер рао", "русгидро", "фск", "электро", "энерг")):
        categories.append("utilities")
    if any(word in text for word in ("преф", "-п", "preferred")) or secid.endswith("P"):
        categories.append("dividends")
    if any(word in text for word in ("овк", "мечел", "втб", "аэрофлот", "сегеж")):
        categories.append("drama")
    if len(categories) == 3:
        categories.append("quiet")
    return tuple(dict.fromkeys(categories))


def collect_moex_share_universe(
    session: requests.Session | None = None,
    *,
    board: str = MOEX_SHARE_BOARD,
    today: date | None = None,
    max_entries: int | None = None,
    include_periods: bool = True,
) -> tuple[TickerUniverseEntry, ...]:
    active_today = today or date.today()
    owns_session = session is None
    active_session = session or requests.Session()
    try:
        rows = apimoex.get_board_securities(
            active_session,
            columns=MOEX_SHARE_COLUMNS,
            board=board,
            market="shares",
            engine="stock",
        )
        entries: list[TickerUniverseEntry] = []
        seen: set[str] = set()
        for row in rows:
            secid = str(row.get("SECID") or row.get("secid") or "").strip().upper()
            if not secid or secid in seen:
                continue
            seen.add(secid)
            title = str(row.get("SHORTNAME") or row.get("SECNAME") or secid).strip()
            start_date = date(2010, 1, 1)
            end_date: date | None = None
            if include_periods:
                try:
                    period = _moex_period_from_candle_borders(
                        apimoex.get_market_candle_borders(active_session, secid, market="shares", engine="stock"),
                        active_today,
                    )
                except Exception:
                    period = None
                if period is not None:
                    start_date, end_date = period
            entries.append(
                TickerUniverseEntry(
                    secid,
                    "stock",
                    "shares",
                    title,
                    start_date,
                    end_date,
                    _classify_moex_share(secid, title),
                    tags=(f"board:{board}",),
                )
            )
            if max_entries is not None and len(entries) >= max_entries:
                break
        return tuple(entries)
    finally:
        if owns_session:
            active_session.close()
