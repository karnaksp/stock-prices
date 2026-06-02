from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramPreset:
    name: str
    title: str
    description: str
    request: str
    aliases: tuple[str, ...] = ()


PRESETS: tuple[TelegramPreset, ...] = (
    TelegramPreset(
        name="neweconomy",
        aliases=("new", "growth", "2021"),
        title="Новая экономика 2021-2026",
        description="SMLT / SGZH / POSI: IPO-эйфория, ставка, длинный откат.",
        request=(
            "SMLT SGZH POSI from=2021-12-17 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 gradient theme=studio title=New_Economy"
        ),
    ),
    TelegramPreset(
        name="metals",
        aliases=("gold", "palladium", "metal"),
        title="Металлы с ежемесячным взносом",
        description="Золото / серебро / палладий в RUB: наглядный долгий DCA-сюжет.",
        request=(
            "gold silver palladium from=2010-01-01 to=2026-05-27 RUB capital invest "
            "initial=0 monthly=30000 gradient theme=aurora title=Metals_DCA"
        ),
    ),
    TelegramPreset(
        name="vodka",
        aliases=("belu", "abrd", "alcohol"),
        title="Алкогольные акции",
        description="BELU / ABRD / KLVZ: менее хайповая, но зрелищная история.",
        request=(
            "BELU ABRD KLVZ from=2024-02-22 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 gradient theme=aurora title=Alcohol_Stocks"
        ),
    ),
    TelegramPreset(
        name="mechel",
        aliases=("coal", "mtlr"),
        title="Мечел: драма циклической акции",
        description="MTLR / MTLRP: резкие движения и понятный риск циклического бизнеса.",
        request=(
            "MTLR MTLRP from=2014-01-01 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 gradient theme=studio title=Mechel_Drama"
        ),
    ),
    TelegramPreset(
        name="wagons",
        aliases=("uwgn", "ovk"),
        title="Вагоны и ожидания",
        description="UWGN против индекса Мосбиржи: история хайпа, ожиданий и просадки.",
        request=(
            "UWGN IMOEX from=2015-01-01 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 gradient theme=default title=Wagons_vs_Market"
        ),
    ),
    TelegramPreset(
        name="bluechips",
        aliases=("sber-lkoh", "classic"),
        title="Голубые фишки: скучно или эффективно",
        description="SBER / LKOH / MGNT: понятное сравнение для широкой аудитории.",
        request=(
            "SBER LKOH MGNT from=2014-01-01 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 gradient theme=default title=Blue_Chips"
        ),
    ),
    TelegramPreset(
        name="techru",
        aliases=("tech", "rutech"),
        title="Российский технологический сюжет",
        description="YDEX / OZON / VKCO: новый рынок, разные траектории и много споров.",
        request=(
            "YDEX OZON VKCO from=2024-07-24 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 gradient theme=studio title=Russian_Tech"
        ),
    ),
)


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace("-", "").replace("_", "")


_PRESET_BY_NAME = {_normalize_name(preset.name): preset for preset in PRESETS}
for _preset in PRESETS:
    for _alias in _preset.aliases:
        _PRESET_BY_NAME[_normalize_name(_alias)] = _preset


def get_preset(name: str) -> TelegramPreset:
    normalized = _normalize_name(name)
    if normalized in _PRESET_BY_NAME:
        return _PRESET_BY_NAME[normalized]
    options = ", ".join(preset.name for preset in PRESETS)
    raise ValueError(f"Unknown preset: {name}. Use one of: {options}.")


def expand_preset_text(text: str) -> tuple[str, TelegramPreset | None]:
    tokens = text.strip().split()
    if not tokens:
        return text, None

    first = tokens[0].lstrip("/").lower()
    preset_name = ""
    rest: list[str] = []
    if first in {"preset", "idea", "story", "scenario"}:
        if len(tokens) < 2:
            options = ", ".join(preset.name for preset in PRESETS)
            raise ValueError(f"Send preset name, for example: preset metals. Options: {options}.")
        preset_name = tokens[1]
        rest = tokens[2:]
    elif first.startswith("preset="):
        preset_name = first.split("=", 1)[1]
        rest = tokens[1:]
    else:
        return text, None

    preset = get_preset(preset_name)
    expanded = " ".join([preset.request, *rest]).strip()
    return expanded, preset


def format_preset_list() -> str:
    lines = [
        "Готовые сценарии для Пульса:",
        "",
    ]
    for preset in PRESETS:
        aliases = f" ({', '.join(preset.aliases[:2])})" if preset.aliases else ""
        lines.append(f"preset {preset.name}{aliases}")
        lines.append(f"{preset.title} — {preset.description}")
        lines.append("")
    lines.append("Можно дописать параметры: preset metals duration=12 theme=studio")
    return "\n".join(lines).strip()
