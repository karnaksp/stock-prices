from __future__ import annotations

from pathlib import Path


MINIAPP_DIR = Path("docs/miniapp")


def test_miniapp_static_entrypoint_exists() -> None:
    html = (MINIAPP_DIR / "index.html").read_text(encoding="utf-8")

    assert "https://telegram.org/js/telegram-web-app.js" in html
    assert '<link rel="stylesheet" href="./app.css?v=20260614">' in html
    assert '<script src="./app.js?v=20260614"></script>' in html
    assert "Mini App рыночных видео" in html
    assert "Собрать видео" in html
    assert 'id="mode-status"' in html
    assert 'id="story-title"' in html
    assert 'id="ticker-summary"' in html
    assert 'id="dock-title"' in html
    assert 'id="send-button"' in html
    assert 'id="copy-button"' in html
    assert "Отправить в бот" in html
    assert "Скопировать" in html
    assert 'data-mode="shorts"' in html
    assert 'data-metric="capital"' in html
    assert '<option value="selt">Валютный рынок</option>' in html
    assert "Техно США" in html
    assert "Градиент" in html
    assert "Легенда" in html
    assert "US tech" not in html
    assert ">Copy<" not in html
    assert "Creator Deck" not in html


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
    assert 'setActiveButtons("[data-mode]"' in script
    assert "els.modeStatus.textContent" in script
    assert "formatTickersForTitle" in script
    assert "renderTickerSummary" in script
    assert "isTelegramLaunch" in script
    assert "canSendToTelegram" in script
    assert "открой Mini App через /app" in script
    assert "Чтобы отправить напрямую" in script
    assert 'els.send.textContent = "Скопировать запрос"' not in script
    assert "tg.close()" not in script
    assert "РѕС‚РєСЂРѕР№" not in script


def test_miniapp_css_keeps_mobile_layout_stable() -> None:
    css = (MINIAPP_DIR / "app.css").read_text(encoding="utf-8")

    assert "box-sizing: border-box" in css
    assert "[hidden]" in css
    assert "grid-template-columns" in css
    assert "@media (max-width: 520px)" in css
    assert "min-height: 56px" in css
    assert ".story-card" in css
    assert ".steps-grid" in css
    assert ".send-dock" in css
    assert ".dock-actions" in css
    assert ".secondary-button--dock" in css
    assert "position: sticky" in css
