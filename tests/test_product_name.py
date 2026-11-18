"""The product is OLGA Companion; the earlier working name must not reach users or the public repo.

The token folder ``~/.olga_copilot`` keeps its name on purpose (renaming it would sign every
existing user out), so the underscore spelling is not matched here.
"""

from __future__ import annotations

import re
from pathlib import Path

from olga_companion.agent import runtime

ROOT = Path(__file__).resolve().parents[1]
OLD_NAME = re.compile(r"olga[ -]?co" r"pilot", re.IGNORECASE)
SHIPPED = ["README.md", "PRODUCT.md", "DESIGN.md", "docs", "src", "scripts", "resources", "frontend/src", "frontend/tests", "tests/fixtures"]
# The glossary generator reads the maintainer's reference folder, whose path keeps the old name.
ALLOWED = {"scripts/build_olga_glossary.py"}
TEXT_SUFFIXES = {".md", ".py", ".json", ".ts", ".tsx", ".mjs", ".html", ".css", ".genkey", ".txt", ""}


def test_the_assistant_introduces_itself_as_olga_companion() -> None:
    prompt = runtime._PROMPT_TEMPLATE
    assert prompt.startswith("You are OLGA Companion")
    assert not OLD_NAME.search(prompt)


def test_no_shipped_file_uses_the_old_product_name() -> None:
    hits: list[str] = []
    for entry in SHIPPED:
        base = ROOT / entry
        files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
        for path in files:
            if path.suffix.lower() not in TEXT_SUFFIXES or "__pycache__" in path.parts or "node_modules" in path.parts:
                continue
            if path.relative_to(ROOT).as_posix() in ALLOWED:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if OLD_NAME.search(line):
                    hits.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    assert hits == []


def test_compiled_cases_name_olga_companion_as_author() -> None:
    source = (ROOT / "src" / "olga_companion" / "case_compiler.py").read_text(encoding="utf-8")
    assert "CASE AUTHOR=OLGACOMPANION" in source
