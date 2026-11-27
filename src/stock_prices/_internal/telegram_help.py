"""Topic-based instructions shown in the MarketMotion chat."""

from __future__ import annotations


_GUIDE_URL = "https://karnaksp.github.io/stock-prices/telegram/"

_HELP_PAGES = {
    "first_video": (
        "Первое видео\n\n"
        "Выберите активы и период в Mini App, затем нажмите «Создать видео». "
        "В группе скопируйте запрос из приложения и отправьте его ответом на сообщение бота.\n\n"
        "Чтобы создать видео из чата, отправьте всю строку\n"
        "/shorts SBER LKOH за год",
        (
            (("Сравнить свои активы", "menu:mini_app"),),
            (("Показать пример ролика", "menu:demo_video"),),
        ),
    ),
    "settings": (
        "Настройки видео\n\n"
        "Откройте «Дополнительные настройки» в Mini App. Выберите рынок и валюту, "
        "покажите цены или стоимость вложений, добавьте пополнения и события на графике. "
        "Там же можно настроить тему, длину и подписи.\n\n"
        "Для быстрой проверки выберите формат «Черновик».",
        (
            (("Настроить видео", "menu:mini_app"),),
            (("Читать синтаксис команд", _GUIDE_URL),),
        ),
    ),
    "ideas": (
        "Идеи и серии\n\n"
        "Выберите категорию для случайного ролика или откройте готовые сценарии. "
        "В плане серии можно посмотреть идеи и скопировать нужный запрос. "
        "Можно также запустить подбор сразу для нескольких выпусков.\n\n"
        "Например, запрос plan metals 5 days 2 tickers предложит пять сравнений металлов по два актива.",
        (
            (("Подобрать случайный ролик", "menu:random_menu"),),
            (("Открыть сценарии", "menu:preset_categories"), ("Посмотреть план", "menu:content_plan")),
        ),
    ),
    "materials": (
        "Материалы к ролику\n\n"
        "Нажмите «Материалы и варианты» под роликом, чтобы открыть пост для Пульса или создать ещё одну версию. "
        "Чтобы получить пост отдельно от видео, отправьте запрос со своими активами\n"
        "post SBER LKOH 2020 2024",
        (
            (("Открыть материалы", "menu:reference"),),
        ),
    ),
    "queue": (
        "Очередь и ошибки\n\n"
        "В очереди видно, готовится ли ваше видео и сколько роликов перед ним. "
        "Готовое видео придёт в чат, где вы его запросили.\n\n"
        "Если бот не нашёл данные, проверьте активы и период. Рынок можно уточнить в настройках Mini App.",
        (
            (("Проверить очередь", "queue:status"),),
        ),
    ),
}
HELP_TOPICS = frozenset(_HELP_PAGES)

_INDEX_ROWS = (
    (("Первое видео", "menu:help_first_video"), ("Настройки", "menu:help_settings")),
    (("Идеи и серии", "menu:help_ideas"), ("Материалы", "menu:help_materials")),
    (("Очередь и ошибки", "menu:help_queue"),),
    (("Полное руководство", _GUIDE_URL), ("В меню", "menu:main_menu")),
)
_SECTION_NAVIGATION = (
    (("К разделам", "menu:help_index"), ("В меню", "menu:main_menu")),
)


def help_page(topic: str = "index") -> tuple[str, dict[str, list[list[dict[str, str]]]]]:
    if topic == "index":
        text, rows = "Информация\n\nВыберите, что хотите сделать.", _INDEX_ROWS
    else:
        text, rows = _HELP_PAGES[topic]
        rows += _SECTION_NAVIGATION
    keyboard = [
        [
            {"text": label, ("url" if target.startswith("https://") else "callback_data"): target}
            for label, target in row
        ]
        for row in rows
    ]
    return text, {"inline_keyboard": keyboard}
