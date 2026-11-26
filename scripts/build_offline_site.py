"""Build docs/olga-companion-offline.html: the Pages front page with both of its pages inside.

The intro slides and the tutorial already carry their fonts and images, so each goes into its
own frame as `srcdoc`. The front page's button downloads the result. Run after changing
docs/index.html, docs/intro.html or docs/tutorial/index.html:

    python scripts/build_offline_site.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
OUT = DOCS / "olga-companion-offline.html"
FRAME = '<iframe id="view" title="OLGA Companion" src="intro.html" data-shown="intro.html"></iframe>'


def build() -> str:
    page = (DOCS / "index.html").read_text(encoding="utf-8")
    # In the offline file the slides' tutorial link only changes the outer page's tab.
    intro = (DOCS / "intro.html").read_text(encoding="utf-8").replace(
        'href="./#tutorial" target="_top"', 'href="#tutorial" target="_top"'
    )
    tutorial = (DOCS / "tutorial" / "index.html").read_text(encoding="utf-8")
    frames = (
        f'<iframe data-view="intro" title="소개 슬라이드" srcdoc="{html.escape(intro)}"></iframe>\n'
        f'<iframe data-view="tutorial" title="튜토리얼" srcdoc="{html.escape(tutorial)}" hidden></iframe>'
    )
    if page.count(FRAME) != 1:
        raise SystemExit("docs/index.html: the frame line changed; update this script")
    page = page.replace(FRAME, frames)
    page, dropped = re.subn(r"\n\s*<a [^>]*data-online-only>.*?</a>", "", page)
    if dropped != 1:
        raise SystemExit("docs/index.html: the download link changed; update this script")
    return page


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8", newline="\n")
    print(f"{OUT.name}: {OUT.stat().st_size:,} bytes")
