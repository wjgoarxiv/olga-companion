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


OFFLINE = REPO / "docs" / "olga-companion-offline.html"


def _build_offline() -> str:
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_offline_site", REPO / "scripts" / "build_offline_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build()


def test_the_front_page_offers_the_offline_file() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert re.search(r'<a class="dl" href="olga-companion-offline.html" download data-online-only>', html)


def test_the_offline_file_is_current_and_holds_both_pages() -> None:
    offline = OFFLINE.read_text(encoding="utf-8")
    assert offline == _build_offline(), "run scripts/build_offline_site.py"
    assert "data-online-only" not in offline and "olga-companion-offline.html" not in offline
    assert [m for m in re.findall(r'<iframe [^>]*data-view="(\w+)"', offline)] == ["intro", "tutorial"]
    # Opened from a download folder it needs nothing beside it: no relative link, script, style or frame source.
    outer = re.sub(r'srcdoc="[^"]*"', 'srcdoc=""', offline)
    # (data-src only names the online page; the offline script shows the frames instead.)
    assert not re.findall(r'(?<![-\w])(?:src|href)="(?!#|https://|data:)[^"]*"', outer)
    import html as html_lib

    docs = [html_lib.unescape(d) for d in re.findall(r'srcdoc="([^"]*)"', offline)]
    intro = (REPO / "docs" / "intro.html").read_text(encoding="utf-8")
    assert docs[0] == intro.replace('href="./#tutorial" target="_top"', 'href="#tutorial" target="_top"')
    assert docs[1] == (REPO / "docs" / "tutorial" / "index.html").read_text(encoding="utf-8")
