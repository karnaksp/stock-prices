from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from stock_prices._internal.market_data.universe_discovery import collect_moex_share_universe


def _entry_to_json(entry) -> dict[str, object]:
    payload = asdict(entry)
    payload["available_from"] = entry.available_from.isoformat()
    payload["available_to"] = entry.available_to.isoformat() if entry.available_to is not None else None
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect MOEX ticker metadata for random content universe.")
    parser.add_argument("--output", default="config/moex_universe.json", help="Path to write JSON metadata.")
    parser.add_argument("--max_entries", type=int, default=None, help="Limit entries for tests or quick checks.")
    parser.add_argument("--no_periods", action="store_true", help="Skip per-ticker candle border requests.")
    args = parser.parse_args()

    entries = collect_moex_share_universe(
        max_entries=args.max_entries,
        today=date.today(),
        include_periods=not args.no_periods,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([_entry_to_json(entry) for entry in entries], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(entries)} ticker metadata entries to {output_path}")


if __name__ == "__main__":
    main()
