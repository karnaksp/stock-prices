from __future__ import annotations


def validate_float_value(quote: dict, key: str) -> bool:
    value = quote.get(key)
    return value is not None and isinstance(value, (int, float)) and value > 0


def validate_quote_structure(quote: dict, engine: str, market: str) -> bool:
    if engine == "currency" and market == "selt":
        return (
            validate_float_value(quote, "VOLRUR")
            or validate_float_value(quote, "NUMTRADES")
            or validate_float_value(quote, "CLOSE")
        )
    if engine == "stock" and market in {"bonds", "shares"}:
        return (
            validate_float_value(quote, "VOLUME")
            or validate_float_value(quote, "NUMTRADES")
            or validate_float_value(quote, "CLOSE")
        )
    if engine == "stock" and market == "index":
        return validate_float_value(quote, "CLOSE")
    if engine == "futures" and market == "forts":
        return (
            validate_float_value(quote, "VOLUME")
            or validate_float_value(quote, "NUMTRADES")
            or validate_float_value(quote, "CLOSE")
        )

    raise ValueError(f"Unknown quote type: {engine}/{market}")
