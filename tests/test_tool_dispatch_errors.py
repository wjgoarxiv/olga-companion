"""An unknown run id is reported as one, not as a missing argument (review 2026-11-27)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from olga_companion import headless_mcp
from olga_companion.agent import tools

UNKNOWN = "20260101-000000-abcdef"


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "ws").mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(tmp_path / "appdata"))


def _error_text(name: str, arguments: dict) -> str:
    result = headless_mcp.call(name, arguments)
    assert result["isError"] is True, result
    wrapped = result["content"][0]["text"]  # <<<OLGA DATA ...\n{json}\nOLGA DATA>>>
    return json.loads(wrapped.split("\n", 1)[1].rsplit("\n", 1)[0])["error"]


@pytest.mark.parametrize("name", ["run_status", "run_cancel"])
def test_an_unknown_run_id_says_so(name: str):
    text = _error_text(name, {"run_id": UNKNOWN})
    assert text == f"Unknown run id: {UNKNOWN}"
    assert "Missing required argument" not in text


def test_a_handler_that_misses_a_key_still_reports_it(monkeypatch: pytest.MonkeyPatch):
    def needs_more(_args: dict) -> dict:
        raise KeyError("series")

    monkeypatch.setattr(tools.TOOLS["olga_glossary"], "handler", needs_more)
    with pytest.raises(tools.ToolError, match="Missing required argument: 'series'"):
        tools.dispatch("olga_glossary", {"term": "PT"})
