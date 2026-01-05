"""
Модуль для валидации данных
"""

from typing import Optional


def validate_float_value(quote: dict, key: str) -> bool:
    """
    Проверка, что значение в котировке является допустимым числом

    Args:
        quote: Словарь с котировкой
        key: Ключ для проверки

    Returns:
        True, если значение допустимо
    """
    val = quote.get(key)
    return val is not None and isinstance(val, (int, float)) and val > 0


def validate_quote_structure(quote: dict, engine: str, market: str) -> bool:
    """
    Проверка структуры котировки на основе движка и рынка

    Args:
        quote: Словарь с котировкой
        engine: Движок торгов
        market: Рынок

    Returns:
        True, если котировка валидна
    """
    if engine == "currency" and market == "selt":
        return (
            validate_float_value(quote, "VOLRUR")
            or validate_float_value(quote, "NUMTRADES")
            or validate_float_value(quote, "CLOSE")
        )
    elif engine == "stock" and market in ["bonds", "shares"]:
        return (
            validate_float_value(quote, "VOLUME")
            or validate_float_value(quote, "NUMTRADES")
            or validate_float_value(quote, "CLOSE")
        )
    elif engine == "stock" and market == "index":
        return validate_float_value(quote, "CLOSE")

    raise ValueError(f"Неизвестный тип котировки: {engine}/{market}")