"""The GitHub Pages site: one page that holds the intro slides and the tutorial."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE = "https://wjgoarxiv.github.io/olga-companion/"
INDEX = REPO / "docs" / "index.html"


def test_the_front_page_holds_both_the_slides_and_the_tutorial() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'http-equiv="refresh"' not in html
    tabs = re.findall(r'<a class="tab" href="#(\w+)" data-src="([^"]+)"', html)
    assert tabs == [("intro", "intro.html"), ("tutorial", "tutorial/")]
    assert '<iframe id="view"' in html
    # Self-contained: no outside script, style or font.
    assert not re.search(r'<(script|link)[^>]+(src|href)="https?:', html)


def test_the_slides_open_the_tutorial_tab_of_the_same_page() -> None:
    intro = (REPO / "docs" / "intro.html").read_text(encoding="utf-8")
    assert f'href="{SITE}tutorial/"' not in intro
    assert 'href="./#tutorial" target="_top"' in intro


def test_the_readmes_send_readers_to_the_one_page() -> None:
    for name in ("README.md", "README.ko.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert f"{SITE}intro.html" not in text and f"{SITE}tutorial/" not in text, name
        assert f"{SITE}#intro" in text and f"{SITE}#tutorial" in text, name
