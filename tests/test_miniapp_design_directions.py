from __future__ import annotations

from pathlib import Path


MINIAPP_DIR = Path("docs/miniapp")


def test_miniapp_design_directions_are_static_review_artifact() -> None:
    html = (MINIAPP_DIR / "directions.html").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="./directions.css">' in html
    assert "app.js" not in html
    assert "Три направления интерфейса" in html
    assert "Вывод дизайнера" in html
    assert "Ticker Composer + Mini Studio Preview" in html
    assert "Studio Console" in html
    assert "Creator Deck" in html
    assert "Market Ledger" in html


def test_miniapp_design_directions_css_is_self_contained() -> None:
    css = (MINIAPP_DIR / "directions.css").read_text(encoding="utf-8")

    assert ".phone-frame--studio" in css
    assert ".phone-frame--creator" in css
    assert ".phone-frame--ledger" in css
    assert ".designer-verdict" in css
    assert "@media (max-width: 860px)" in css
