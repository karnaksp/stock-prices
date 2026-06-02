from __future__ import annotations

from stock_prices._internal.healthcheck import check_environment


def test_healthcheck_requires_token(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("STOCK_PRICES_OUTPUT_DIR", str(tmp_path))

    try:
        check_environment()
    except RuntimeError as exc:
        assert "TELEGRAM_BOT_TOKEN" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


def test_healthcheck_verifies_output_dir(monkeypatch, tmp_path) -> None:
    output_dir = tmp_path / "animations"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("STOCK_PRICES_OUTPUT_DIR", str(output_dir))

    check_environment()

    assert output_dir.exists()
