from __future__ import annotations

from pathlib import Path


ROADMAP_DOC = Path("docs/roadmap.md")


def test_roadmap_is_localized_and_current_for_product_docs() -> None:
    roadmap = ROADMAP_DOC.read_text(encoding="utf-8")

    assert "ближайшие инженерные улучшения" in roadmap
    assert "Docker smoke" in roadmap
    assert "Add a Docker build smoke check to CI" not in roadmap
    assert "This roadmap tracks production hardening" not in roadmap
