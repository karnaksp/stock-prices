from __future__ import annotations

from pathlib import Path


MINIAPP_DIR = Path("docs/miniapp")


def test_miniapp_static_entrypoint_exists() -> None:
    html = (MINIAPP_DIR / "index.html").read_text(encoding="utf-8")

    assert "https://telegram.org/js/telegram-web-app.js" in html
    assert '<link rel="stylesheet" href="./app.css">' in html
    assert '<script src="./app.js"></script>' in html
    assert "Market Motion Mini App" in html


def test_miniapp_sends_supported_telegram_payload() -> None:
    script = (MINIAPP_DIR / "app.js").read_text(encoding="utf-8")

    assert "stock_prices.video_request.v1" in script
    assert "tg.sendData(payload)" in script
    assert "from=${els.startDate.value}" in script
    assert "to=${els.endDate.value}" in script
    assert "duration=${duration}" in script
    assert "fps=${fps}" in script
    assert "theme=${els.theme.value}" in script
    assert "monthly=${Math.max(0, readPositiveInt(els.monthly, 0))}" in script


def test_miniapp_css_keeps_mobile_layout_stable() -> None:
    css = (MINIAPP_DIR / "app.css").read_text(encoding="utf-8")

    assert "box-sizing: border-box" in css
    assert "[hidden]" in css
    assert "grid-template-columns" in css
    assert "@media (max-width: 520px)" in css
    assert "min-height: 52px" in css
