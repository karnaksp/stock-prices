from __future__ import annotations

import os
import tempfile
from pathlib import Path


def check_environment() -> None:
    import stock_prices  # noqa: F401

    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")

    output_dir = Path(os.getenv("STOCK_PRICES_OUTPUT_DIR", "animations"))
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".healthcheck-", dir=output_dir, delete=True):
        pass


def main() -> int:
    check_environment()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
