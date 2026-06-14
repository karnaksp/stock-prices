from __future__ import annotations

from pathlib import Path


ASSETS = Path("docs/assets")
INDEX_DOC = Path("docs/index.md")
DEMO_DOC = Path("docs/demo.md")


def test_portfolio_demo_assets_are_present_and_compact() -> None:
    expected_assets = {
        "demo-sber-lkoh.gif": 2_000_000,
        "demo-sber-lkoh.mp4": 500_000,
        "demo-sber-lkoh.png": 500_000,
    }

    for filename, max_size in expected_assets.items():
        path = ASSETS / filename
        assert path.exists(), f"{path} is missing"
        assert path.stat().st_size > 10_000, f"{path} is unexpectedly small"
        assert path.stat().st_size <= max_size, f"{path} is too large for docs"


def test_docs_link_the_mp4_demo_artifact() -> None:
    index = INDEX_DOC.read_text(encoding="utf-8")
    demo = DEMO_DOC.read_text(encoding="utf-8")

    assert "assets/demo-sber-lkoh.mp4" in index
    assert "../assets/demo-sber-lkoh.mp4" in demo
    assert "<video" in index
    assert "<video" in demo
