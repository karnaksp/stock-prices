from __future__ import annotations

import re
from pathlib import Path


MINIAPP_DIR = Path("docs/miniapp")


def test_miniapp_static_entrypoint_exists() -> None:
    html = (MINIAPP_DIR / "index.html").read_text(encoding="utf-8")

    assert '<script id="telegram-sdk" async src="https://telegram.org/js/telegram-web-app.js">' in html
    versions = re.findall(r'\./app\.(?:js|css)\?v=([0-9a-z]+)', html)
    assert len(versions) == 2 and versions[0] == versions[1]
    assert "MarketMotion" in html
    assert 'id="video-form"' in html
    assert 'id="tickers"' in html
    assert 'id="selected-assets"' in html
    assert 'id="asset-suggestions"' in html
    assert f'./catalog.js?v={versions[0]}' in html
    assert html.index("Смотреть пример") < html.index('id="video-form"')
    assert html.index('id="send-button"') < html.index("Дополнительные настройки")
    assert 'data-period="1" aria-pressed="true"' in html
    assert 'id="custom-dates" hidden' in html
    assert '<details class="disclosure settings">' in html
    assert '<option value="selt">Валютный рынок</option>' in html
    assert 'id="send-button"' in html
    assert "../assets/demo-sber-lkoh.mp4" in html


def test_miniapp_sends_supported_telegram_payload() -> None:
    script = (MINIAPP_DIR / "app.js").read_text(encoding="utf-8")

    assert 'get("launch")' in script
    assert 'tg && launch === "keyboard" && !tg.initData' in script
    assert "stock_prices.video_request.v1" in script
    assert "tg.sendData(payload)" in script
    assert "from=${els.startDate.value}" in script
    assert "to=${els.endDate.value}" in script
    assert "duration=${duration}" in script
    assert "fps=${fps}" in script
    assert "theme=${els.theme.value}" in script
    assert "monthly=${Math.max(0, readPositiveInt(els.monthly, 0))}" in script
    assert "encodeURIComponent(event.title)" in script
    assert 'addEventListener("load", initTelegram)' in script
    assert "new Blob([payload]).size <= 4096" in script
    assert "tg.close()" not in script


def test_miniapp_css_keeps_mobile_layout_stable() -> None:
    css = (MINIAPP_DIR / "app.css").read_text(encoding="utf-8")

    assert "box-sizing: border-box" in css
    assert "[hidden]" in css
    assert "env(safe-area-inset-bottom" in css
    assert "minmax(0, 1fr)" in css
    assert "min-height: 44px" in css
    assert "position: sticky" not in css
