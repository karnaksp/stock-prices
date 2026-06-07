from __future__ import annotations

import os
from pathlib import Path

RETENTION_DAYS_ENV = "STOCK_PRICES_RETENTION_DAYS"
CLEANUP_RETENTION_DAYS_ENV = "STOCK_PRICES_CLEANUP_RETENTION_DAYS"
MINI_APP_URL_ENV = "STOCK_PRICES_MINI_APP_URL"
MINI_APP_MENU_BUTTON_ENV = "STOCK_PRICES_MINI_APP_MENU_BUTTON"
DEFAULT_MINI_APP_URL = "https://karnaksp.github.io/stock-prices/miniapp/"


def load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_cleanup_retention_days(default: int = 0) -> int:
    raw_value = os.getenv(RETENTION_DAYS_ENV) or os.getenv(CLEANUP_RETENTION_DAYS_ENV)
    if raw_value is None or not raw_value.strip():
        return default

    try:
        retention_days = int(raw_value)
    except ValueError:
        msg = f"{RETENTION_DAYS_ENV} must be a non-negative integer."
        raise ValueError(msg) from None

    if retention_days < 0:
        msg = f"{RETENTION_DAYS_ENV} must be a non-negative integer."
        raise ValueError(msg)
    return retention_days


def get_mini_app_url(default: str = DEFAULT_MINI_APP_URL) -> str:
    value = os.getenv(MINI_APP_URL_ENV, "").strip()
    return value or default


def get_mini_app_menu_button_enabled(default: bool = False) -> bool:
    value = os.getenv(MINI_APP_MENU_BUTTON_ENV, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    msg = f"{MINI_APP_MENU_BUTTON_ENV} must be a boolean value."
    raise ValueError(msg)
