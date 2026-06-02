from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramPreset:
    name: str
    title: str
    description: str
    request: str
    hook: str
    post_text: str
    tags: tuple[str, ...]
    music_mood: str
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
        hook="Если бы вы каждый месяц покупали новую экономику с IPO-эйфорией, чем бы это закончилось?",
        post_text=(
            "Взял три ярких истории роста: SMLT, SGZH и POSI. На графике видно, как ожидания 2021 года "
            "сталкиваются со ставками, переоценкой и реальностью бизнеса. Хороший ролик про то, почему "
            "красивая история не всегда равна спокойной доходности."
        ),
        tags=("#пульс", "#инвестиции", "#акции", "#новаяэкономика"),
        music_mood="напряженный synthwave или быстрый электронный бит",
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
        hook="Что было бы, если 16 лет подряд каждый месяц покупать золото, серебро и палладий на 30 000 ₽?",
        post_text=(
            "Металлы часто воспринимают как защиту, но траектории у них совсем разные. Здесь DCA в рублях: "
            "каждый месяц одинаковый взнос, а итог показывает, где защита превратилась в рост, а где волатильность "
            "забрала часть ожиданий."
        ),
        tags=("#пульс", "#металлы", "#золото", "#инвестиции"),
        music_mood="ровный cinematic beat с нарастающим финалом",
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
        hook="Не только IT умеет устраивать американские горки. Алкогольные акции тоже могут удивить.",
        post_text=(
            "BELU, ABRD и KLVZ выглядят как нишевая история, но именно такие графики часто цепляют: бизнес понятный, "
            "движения резкие, ожидания меняются быстро. Хороший пример, почему менее хайповые бумаги иногда дают "
            "самые зрелищные ролики."
        ),
        tags=("#пульс", "#акции", "#российскийрынок", "#идеядляграфика"),
        music_mood="ироничный funk / disco beat без тяжелого драматизма",
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
        hook="Мечел — акция, где слово 'волатильность' выглядит слишком мягко.",
        post_text=(
            "Сравнил MTLR и MTLRP на длинном периоде с ежемесячными взносами. Здесь хорошо видно, как циклический "
            "бизнес может дарить мощные рывки и одновременно проверять инвестора на терпение. Это не история про "
            "спокойный график, а история про риск."
        ),
        tags=("#пульс", "#мечел", "#акции", "#риск"),
        music_mood="тяжелый industrial beat или драматичный trailer percussion",
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
        hook="Вагоны против индекса: что осталось от большой истории ожиданий?",
        post_text=(
            "UWGN хорошо подходит для ролика про ожидания и реальность. На графике рядом стоит индекс Мосбиржи, "
            "поэтому видно не только движение одной бумаги, но и цену выбора конкретной идеи вместо широкого рынка."
        ),
        tags=("#пульс", "#uwgn", "#IMOEX", "#российскиеакции"),
        music_mood="медленный dark beat с резким акцентом на просадках",
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
        hook="Скучные голубые фишки против желания найти 'ракету'. Кто выглядит сильнее на длинной дистанции?",
        post_text=(
            "SBER, LKOH и MGNT — понятные имена, которые многие держали или хотя бы рассматривали. Такой график "
            "хорош для широкой аудитории: без экзотики, зато видно, как регулярные покупки меняют восприятие "
            "доходности и просадок."
        ),
        tags=("#пульс", "#сбер", "#лукойл", "#долгосрок"),
        music_mood="уверенный pop / corporate beat с чистым ритмом",
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
        hook="Российский tech: мечта о росте или слишком нервная ставка?",
        post_text=(
            "YDEX, OZON и VKCO хорошо работают как спорный ролик: знакомые бренды, разные бизнес-модели и много "
            "ожиданий. На таком сравнении удобно обсуждать, где инвестор покупает бизнес, а где просто красивую "
            "идею будущего."
        ),
        tags=("#пульс", "#технологии", "#ydex", "#ozon"),
        music_mood="быстрый tech house или clean electronic groove",
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


def format_pulse_post(preset: TelegramPreset) -> str:
    tags = " ".join(preset.tags)
    return (
        "Текст для Пульса:\n"
        f"{preset.hook}\n\n"
        f"{preset.post_text}\n\n"
        f"Музыка/монтаж: {preset.music_mood}.\n"
        f"{tags}\n\n"
        "Не является индивидуальной инвестиционной рекомендацией."
    )


def preset_inline_keyboard(columns: int = 2) -> dict[str, list[list[dict[str, str]]]]:
    buttons = [{"text": preset.name, "callback_data": f"preset:{preset.name}"} for preset in PRESETS]
    rows = [buttons[index : index + columns] for index in range(0, len(buttons), columns)]
    return {"inline_keyboard": rows}
