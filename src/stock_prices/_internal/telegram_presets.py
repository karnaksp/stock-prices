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
    music_tracks: tuple[str, ...] = ()
    cover_texts: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    button_label: str = ""


PRESETS: tuple[TelegramPreset, ...] = (
    TelegramPreset(
        name="neweconomy",
        aliases=("new", "growth", "2021", "новая", "новая экономика", "ipo"),
        title="Новая экономика 2021-2026",
        description="SMLT / SGZH / POSI: IPO-эйфория, ставка, длинный откат.",
        request=(
            "SMLT SGZH POSI from=2021-12-17 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 shorts theme=studio title=New_Economy"
        ),
        hook="Если бы вы каждый месяц покупали новую экономику с IPO-эйфорией, чем бы это закончилось?",
        post_text=(
            "Взял три ярких истории роста: SMLT, SGZH и POSI. На графике видно, как ожидания 2021 года "
            "сталкиваются со ставками, переоценкой и реальностью бизнеса. Хороший ролик про то, почему "
            "красивая история не всегда равна спокойной доходности."
        ),
        tags=("#пульс", "#инвестиции", "#акции", "#новаяэкономика"),
        music_mood="напряженный synthwave или быстрый электронный бит",
        music_tracks=("Kavinsky - Nightcall", "Carpenter Brut - Turbo Killer", "The Weeknd - Blinding Lights"),
        cover_texts=("IPO-эйфория vs реальность", "30 000 ₽/мес в новую экономику", "Ростовые акции после хайпа"),
        button_label="Новая экономика",
    ),
    TelegramPreset(
        name="metals",
        aliases=("gold", "palladium", "metal", "металлы", "металл", "палладий", "золото"),
        title="Металлы с ежемесячным взносом",
        description="Золото / серебро / палладий в RUB: наглядный долгий DCA-сюжет.",
        request=(
            "gold silver palladium from=2010-01-01 to=2026-05-27 RUB capital invest "
            "initial=0 monthly=30000 shorts theme=aurora title=Metals_DCA"
        ),
        hook="Что было бы, если 16 лет подряд каждый месяц покупать золото, серебро и палладий на 30 000 ₽?",
        post_text=(
            "Металлы часто воспринимают как защиту, но траектории у них совсем разные. Здесь DCA в рублях: "
            "каждый месяц одинаковый взнос, а итог показывает, где защита превратилась в рост, а где волатильность "
            "забрала часть ожиданий."
        ),
        tags=("#пульс", "#металлы", "#золото", "#инвестиции"),
        music_mood="ровный cinematic beat с нарастающим финалом",
        music_tracks=("M83 - Outro", "Hans Zimmer - Time", "ODESZA - A Moment Apart"),
        cover_texts=("30 000 ₽/мес в металлы", "Золото vs серебро vs палладий", "Какие металлы спасли рубли?"),
        button_label="Металлы",
    ),
    TelegramPreset(
        name="vodka",
        aliases=("belu", "abrd", "alcohol", "водка", "алкоголь", "белуга", "абрау"),
        title="Алкогольные акции",
        description="BELU / ABRD / KLVZ: менее хайповая, но зрелищная история.",
        request=(
            "BELU ABRD KLVZ from=2024-02-22 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 shorts theme=aurora title=Alcohol_Stocks"
        ),
        hook="Не только IT умеет устраивать американские горки. Алкогольные акции тоже могут удивить.",
        post_text=(
            "BELU, ABRD и KLVZ выглядят как нишевая история, но именно такие графики часто цепляют: бизнес понятный, "
            "движения резкие, ожидания меняются быстро. Хороший пример, почему менее хайповые бумаги иногда дают "
            "самые зрелищные ролики."
        ),
        tags=("#пульс", "#акции", "#российскийрынок", "#идеядляграфика"),
        music_mood="ироничный funk / disco beat без тяжелого драматизма",
        music_tracks=("ABBA - Money, Money, Money", "Boney M. - Rasputin", "Parov Stelar - Booty Swing"),
        cover_texts=("Алкогольные акции удивили", "Водка против рынка", "Не IT, а график резкий"),
        button_label="Алкоголь",
    ),
    TelegramPreset(
        name="mechel",
        aliases=("coal", "mtlr", "мечел", "уголь"),
        title="Мечел: драма циклической акции",
        description="MTLR / MTLRP: резкие движения и понятный риск циклического бизнеса.",
        request=(
            "MTLR MTLRP from=2014-01-01 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 shorts theme=studio title=Mechel_Drama"
        ),
        hook="Мечел — акция, где слово 'волатильность' выглядит слишком мягко.",
        post_text=(
            "Сравнил MTLR и MTLRP на длинном периоде с ежемесячными взносами. Здесь хорошо видно, как циклический "
            "бизнес может дарить мощные рывки и одновременно проверять инвестора на терпение. Это не история про "
            "спокойный график, а история про риск."
        ),
        tags=("#пульс", "#мечел", "#акции", "#риск"),
        music_mood="тяжелый industrial beat или драматичный trailer percussion",
        music_tracks=("The Prodigy - Firestarter", "Gesaffelstein - Pursuit", "Nine Inch Nails - The Hand That Feeds"),
        cover_texts=("Мечел: боль или шанс?", "Циклическая акция без жалости", "30 000 ₽/мес в Мечел"),
        button_label="Мечел",
    ),
    TelegramPreset(
        name="wagons",
        aliases=("uwgn", "ovk", "вагоны", "овк"),
        title="Вагоны и ожидания",
        description="UWGN против индекса Мосбиржи: история хайпа, ожиданий и просадки.",
        request=(
            "UWGN IMOEX from=2015-01-01 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 shorts theme=default title=Wagons_vs_Market"
        ),
        hook="Вагоны против индекса: что осталось от большой истории ожиданий?",
        post_text=(
            "UWGN хорошо подходит для ролика про ожидания и реальность. На графике рядом стоит индекс Мосбиржи, "
            "поэтому видно не только движение одной бумаги, но и цену выбора конкретной идеи вместо широкого рынка."
        ),
        tags=("#пульс", "#uwgn", "#IMOEX", "#российскиеакции"),
        music_mood="медленный dark beat с резким акцентом на просадках",
        music_tracks=("Depeche Mode - Wrong", "Massive Attack - Angel", "Woodkid - Run Boy Run"),
        cover_texts=("Вагоны против индекса", "Хайп, ожидания, просадка", "Что осталось от истории ОВК?"),
        button_label="Вагоны",
    ),
    TelegramPreset(
        name="stateowned",
        aliases=("госы", "госкомпании", "state", "stateowned"),
        title="Госкомпании: длинная дистанция ожиданий",
        description="GAZP / AFLT / SNGS: знакомые имена, разные циклы и тяжелые просадки.",
        request=(
            "GAZP AFLT SNGS from=2010-01-01 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 shorts theme=studio title=State_Owned"
        ),
        hook="Что было бы, если много лет подряд покупать самые узнаваемые госистории рынка?",
        post_text=(
            "GAZP, AFLT и SNGS хорошо подходят для ролика про ожидания и реальность. Компании знакомые, новости громкие, "
            "но путь инвестора получается совсем не ровным: сырьевой цикл, санкции, дивиденды, переоценка рисков и длинные периоды ожидания."
        ),
        tags=("#пульс", "#газпром", "#аэрофлот", "#российскиеакции"),
        music_mood="сдержанный драматичный beat с ощущением длинного ожидания",
        music_tracks=("Кино - Группа крови", "Сплин - Выхода нет", "Moby - Extreme Ways"),
        cover_texts=("Госкомпании на длинной дистанции", "Знакомые имена, тяжелый график", "Газпром / Аэрофлот / Сургут"),
        button_label="Госкомпании",
    ),
    TelegramPreset(
        name="exporters",
        aliases=("экспортеры", "экспортёры", "exporters", "сырье"),
        title="Экспортеры: рубль, сырье и циклы",
        description="LKOH / PHOR / NLMK: сильные бизнесы, но разная цена входа и цикличность.",
        request=(
            "LKOH PHOR NLMK from=2011-07-18 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 shorts theme=aurora title=Exporters"
        ),
        hook="Экспортеры часто кажутся защитой от слабого рубля. Но кто реально вытянул регулярные покупки?",
        post_text=(
            "LKOH, PHOR и NLMK дают понятное сравнение для Пульса: нефть, удобрения и металлургия. "
            "На графике видно не только влияние валюты, но и то, насколько цикличные истории требуют терпения."
        ),
        tags=("#пульс", "#лукойл", "#фосагро", "#нлмк"),
        music_mood="энергичный electronic groove с акцентами на смене лидера",
        music_tracks=("The Chemical Brothers - Galvanize", "Justice - Genesis", "Daft Punk - Harder, Better, Faster, Stronger"),
        cover_texts=("Экспортеры против слабого рубля", "Кто вытянул регулярные покупки?", "Нефть, удобрения, металл"),
        button_label="Экспортёры",
    ),
    TelegramPreset(
        name="coalminers",
        aliases=("угольщики", "уголь", "coalminers", "rasp"),
        title="Угольщики: циклическая ставка без спокойствия",
        description="MTLR / RASP: резкие фазы роста, откаты и проверка терпения.",
        request=(
            "MTLR RASP from=2014-06-09 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 shorts theme=studio title=Coal_Minors"
        ),
        hook="Угольщики умеют выглядеть как ракета, но только если забыть, что у ракеты бывают обратные рейсы.",
        post_text=(
            "MTLR и RASP - история для тех, кто любит циклические активы. Такой ролик хорошо показывает, как быстро меняется настроение "
            "в сырьевых бумагах и почему регулярные покупки не отменяют риск длинных просадок."
        ),
        tags=("#пульс", "#мечел", "#распадская", "#циклическиеакции"),
        music_mood="жесткий industrial / breakbeat с резкими паузами на просадках",
        music_tracks=("The Prodigy - Breathe", "Royal Blood - Out of the Black", "The White Stripes - Seven Nation Army"),
        cover_texts=("Угольщики: ракета или ловушка?", "Сырьевой цикл без спокойствия", "MTLR vs RASP"),
        button_label="Угольщики",
    ),
    TelegramPreset(
        name="bluechips",
        aliases=("sber-lkoh", "classic", "голубые", "голубые фишки", "классика"),
        title="Голубые фишки: скучно или эффективно",
        description="SBER / LKOH / MGNT: понятное сравнение для широкой аудитории.",
        request=(
            "SBER LKOH MGNT from=2014-01-01 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 shorts theme=default title=Blue_Chips"
        ),
        hook="Скучные голубые фишки против желания найти 'ракету'. Кто выглядит сильнее на длинной дистанции?",
        post_text=(
            "SBER, LKOH и MGNT — понятные имена, которые многие держали или хотя бы рассматривали. Такой график "
            "хорош для широкой аудитории: без экзотики, зато видно, как регулярные покупки меняют восприятие "
            "доходности и просадок."
        ),
        tags=("#пульс", "#сбер", "#лукойл", "#долгосрок"),
        music_mood="уверенный pop / corporate beat с чистым ритмом",
        music_tracks=("Daft Punk - One More Time", "Phoenix - Lisztomania", "Queen - Don't Stop Me Now"),
        cover_texts=("Скучные акции победили?", "SBER / LKOH / MGNT", "Голубые фишки без хайпа"),
        button_label="Голубые фишки",
    ),
    TelegramPreset(
        name="techru",
        aliases=("tech", "rutech", "тех", "технологии", "российский тех"),
        title="Российский технологический сюжет",
        description="YDEX / OZON / VKCO: новый рынок, разные траектории и много споров.",
        request=(
            "YDEX OZON VKCO from=2024-07-24 to=2026-06-01 RUB capital invest "
            "initial=0 monthly=30000 shorts theme=studio title=Russian_Tech"
        ),
        hook="Российский tech: мечта о росте или слишком нервная ставка?",
        post_text=(
            "YDEX, OZON и VKCO хорошо работают как спорный ролик: знакомые бренды, разные бизнес-модели и много "
            "ожиданий. На таком сравнении удобно обсуждать, где инвестор покупает бизнес, а где просто красивую "
            "идею будущего."
        ),
        tags=("#пульс", "#технологии", "#ydex", "#ozon"),
        music_mood="быстрый tech house или clean electronic groove",
        music_tracks=("Daft Punk - Technologic", "The Chemical Brothers - Go", "Disclosure - When a Fire Starts to Burn"),
        cover_texts=("Российский tech: мечта или риск?", "YDEX / OZON / VKCO", "Технологии после перезапуска"),
        button_label="Российский тех",
    ),
)


_PRESET_COMMANDS = {"preset", "idea", "story", "scenario", "пресет", "идея", "история", "сценарий"}
_PRESET_EQUALS_PREFIXES = ("preset=", "idea=", "story=", "scenario=", "пресет=", "идея=", "история=", "сценарий=")
_DIRECT_PRESET_ALIASES = {
    "neweconomy": "neweconomy",
    "новая": "neweconomy",
    "новая экономика": "neweconomy",
    "metals": "metals",
    "металлы": "metals",
    "металл": "metals",
    "vodka": "vodka",
    "водка": "vodka",
    "алкоголь": "vodka",
    "mechel": "mechel",
    "мечел": "mechel",
    "wagons": "wagons",
    "вагоны": "wagons",
    "stateowned": "stateowned",
    "госы": "stateowned",
    "госкомпании": "stateowned",
    "exporters": "exporters",
    "экспортеры": "exporters",
    "экспортёры": "exporters",
    "coalminers": "coalminers",
    "угольщики": "coalminers",
    "bluechips": "bluechips",
    "голубые": "bluechips",
    "голубые фишки": "bluechips",
    "techru": "techru",
    "российский тех": "techru",
    "технологии": "techru",
}
_DIRECT_MODE_PREFIXES = {
    "short": "shorts",
    "shorts": "shorts",
    "reels": "shorts",
    "шорт": "shorts",
    "шортс": "shorts",
    "шортсы": "shorts",
    "draft": "draft",
    "preview": "draft",
    "черновик": "draft",
    "превью": "draft",
}


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace("-", "").replace("_", "").replace(" ", "")


_PRESET_BY_NAME = {_normalize_name(preset.name): preset for preset in PRESETS}
for _preset in PRESETS:
    for _alias in _preset.aliases:
        _PRESET_BY_NAME[_normalize_name(_alias)] = _preset
_DIRECT_PRESET_BY_NAME = {
    _normalize_name(alias): _PRESET_BY_NAME[_normalize_name(preset_name)]
    for alias, preset_name in _DIRECT_PRESET_ALIASES.items()
}


def get_preset(name: str) -> TelegramPreset:
    normalized = _normalize_name(name)
    if normalized in _PRESET_BY_NAME:
        return _PRESET_BY_NAME[normalized]
    options = ", ".join(preset.name for preset in PRESETS)
    raise ValueError(f"Unknown preset: {name}. Use one of: {options}.")


def _match_preset_tokens(tokens: list[str]) -> tuple[TelegramPreset, list[str]]:
    if not tokens:
        options = ", ".join(preset.name for preset in PRESETS)
        raise ValueError(f"Send preset name, for example: preset metals. Options: {options}.")
    for end in range(len(tokens), 0, -1):
        normalized = _normalize_name(" ".join(tokens[:end]))
        if normalized in _PRESET_BY_NAME:
            return _PRESET_BY_NAME[normalized], tokens[end:]
    options = ", ".join(preset.name for preset in PRESETS)
    raise ValueError(f"Unknown preset: {' '.join(tokens)}. Use one of: {options}.")


def _match_direct_preset_tokens(tokens: list[str]) -> tuple[TelegramPreset, list[str]] | None:
    if not tokens:
        return None

    rest_prefix: list[str] = []
    candidate_tokens = tokens
    first = tokens[0].lstrip("/").lower()
    if first in _DIRECT_MODE_PREFIXES:
        rest_prefix = [_DIRECT_MODE_PREFIXES[first]]
        candidate_tokens = tokens[1:]
    if not candidate_tokens:
        return None

    for end in range(len(candidate_tokens), 0, -1):
        normalized = _normalize_name(" ".join(candidate_tokens[:end]))
        if normalized in _DIRECT_PRESET_BY_NAME:
            return _DIRECT_PRESET_BY_NAME[normalized], [*rest_prefix, *candidate_tokens[end:]]
    return None


def expand_preset_text(text: str) -> tuple[str, TelegramPreset | None]:
    tokens = text.strip().split()
    if not tokens:
        return text, None

    first = tokens[0].lstrip("/").lower()
    rest: list[str] = []
    if first in _PRESET_COMMANDS:
        preset, rest = _match_preset_tokens(tokens[1:])
    elif any(first.startswith(prefix) for prefix in _PRESET_EQUALS_PREFIXES):
        preset = get_preset(first.split("=", 1)[1])
        rest = tokens[1:]
    else:
        direct_match = _match_direct_preset_tokens(tokens)
        if direct_match is None:
            return text, None
        preset, rest = direct_match

    expanded = " ".join([preset.request, *rest]).strip()
    return expanded, preset


def format_preset_list(mode: str = "shorts") -> str:
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
    lines.append("Коротко: металлы, черновик металлы, голубые фишки duration=12")
    lines.append("Для отбора идей: все черновики - поставить в очередь draft-прогоны всех сценариев.")
    lines.append("Статус очереди: /queue или очередь.")
    lines.append("После preset-видео бот покажет кнопки: черновик 4s, шортс 16s и вариант 12s.")
    if mode == "draft":
        lines.append("Draft-кнопки ниже запустят быстрый черновик: duration=4 fps=8 без gradient.")
        lines.append("Текстом: preset metals draft")
    return "\n".join(lines).strip()


def format_music_list() -> str:
    lines = [
        "Музыкальные референсы для Пульса:",
        "",
    ]
    for preset in PRESETS:
        tracks = ", ".join(preset.music_tracks)
        lines.append(f"{preset.title}: {tracks}")
    lines.append("")
    lines.append("Это идеи для монтажа; права на треки нужно проверять отдельно перед публикацией.")
    return "\n".join(lines).strip()


def format_cover_list() -> str:
    lines = [
        "Тексты для обложек Пульса:",
        "",
    ]
    for preset in PRESETS:
        covers = " / ".join(preset.cover_texts)
        lines.append(f"{preset.title}: {covers}")
    lines.append("")
    lines.append("Короткие варианты рассчитаны на титр или первый кадр вертикального ролика.")
    return "\n".join(lines).strip()


def format_pulse_post(preset: TelegramPreset) -> str:
    tags = " ".join(preset.tags)
    music_tracks = ""
    if preset.music_tracks:
        music_tracks = f"Треки-референсы (права проверять отдельно): {', '.join(preset.music_tracks)}.\n"
    cover_texts = ""
    if preset.cover_texts:
        cover_texts = f"Текст на обложку: {' / '.join(preset.cover_texts)}.\n"
    return (
        "Текст для Пульса:\n"
        f"{preset.hook}\n\n"
        f"{preset.post_text}\n\n"
        f"{cover_texts}"
        f"Музыка/монтаж: {preset.music_mood}.\n"
        f"{music_tracks}"
        f"{tags}\n\n"
        "Не является индивидуальной инвестиционной рекомендацией."
    )


def preset_button_label(preset: TelegramPreset) -> str:
    return preset.button_label or preset.name


def preset_followup_keyboard(preset_name: str) -> dict[str, list[list[dict[str, str]]]]:
    preset = get_preset(preset_name)
    return {
        "inline_keyboard": [
            [
                {"text": "Черновик 4s", "callback_data": f"preset:{preset.name}:draft"},
                {"text": "Шортс 16s", "callback_data": f"preset:{preset.name}:shorts"},
            ],
            [
                {"text": "Вариант 12s", "callback_data": f"preset:{preset.name}:12s"},
            ],
        ]
    }


def preset_inline_keyboard(columns: int = 2, mode: str = "shorts") -> dict[str, list[list[dict[str, str]]]]:
    if mode not in {"shorts", "draft"}:
        msg = f"Unknown preset keyboard mode: {mode}."
        raise ValueError(msg)
    suffix = ":draft" if mode == "draft" else ""
    buttons = [{"text": preset_button_label(preset), "callback_data": f"preset:{preset.name}{suffix}"} for preset in PRESETS]
    rows = [buttons[index : index + columns] for index in range(0, len(buttons), columns)]
    return {"inline_keyboard": rows}
