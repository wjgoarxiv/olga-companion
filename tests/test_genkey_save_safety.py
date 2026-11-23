"""A new case never overwrites a file, and PVTFILE cannot inject GENKEY lines (security review B3, B4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from olga_companion import genkey_mutations, genkey_static
from olga_companion.agent import tool_side_effects, tools


def _target(save_rel: str, pvtfile: str = "./fluid.tab") -> Any:
    return lambda *_a: {"save_rel": save_rel, "topology": "simple_pipeline", "endtime_s": 3600, "pvtfile": pvtfile}


@pytest.fixture
def ran(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(tool_side_effects, "_consume", lambda *_a: None)
    monkeypatch.setattr(tool_side_effects.workspace, "contained", lambda rel: tmp_path / rel)
    monkeypatch.setattr(genkey_static, "run_tool", lambda *a, **_k: calls.append(a[0]))
    return calls


def test_save_over_an_existing_case_is_refused_and_the_file_is_kept(tmp_path: Path, ran: list[str]) -> None:
    (tmp_path / "old.genkey").write_bytes(b"CASE kept\n")
    with pytest.raises(tools.ToolRefusedError, match="already exists"):
        tool_side_effects.genkey_save({}, _target("old.genkey"))
    assert (tmp_path / "old.genkey").read_bytes() == b"CASE kept\n"
    assert ran == []


@pytest.mark.parametrize(
    "pvtfile",
    [
        "fluid.tab\nCASE INJECTED",
        "fluid.tab\rX",
        'fluid".tab',
        "fluid.tab ! hidden",
        "../outside/fluid.tab",
        "C:\\fluids\\fluid.tab",
        "/abs/fluid.tab",
        "\\\\host\\share\\fluid.tab",
        "",
        "a" * 300 + ".tab",
    ],
)
def test_unsafe_pvtfile_is_refused_before_the_builder(tmp_path: Path, ran: list[str], pvtfile: str) -> None:
    with pytest.raises(tools.ToolRefusedError, match="PVTFILE"):
        tool_side_effects.genkey_save({}, _target("new.genkey", pvtfile))
    assert ran == []
    assert not (tmp_path / "new.genkey").exists()


@pytest.mark.parametrize("pvtfile", ["./fluid.tab", "fluid.tab", "fluids/air_water.tab", "fluids\\x.tab"])
def test_ordinary_pvtfile_is_accepted(pvtfile: str) -> None:
    assert genkey_mutations.require_safe_pvtfile(pvtfile) == pvtfile


def test_preview_refuses_unsafe_pvtfile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(genkey_static, "run_tool", lambda *a, **_k: pytest.fail("builder ran"))
    with pytest.raises(genkey_static.OlgaInputError, match="PVTFILE"):
        genkey_static.create_preview("simple_pipeline", 3600, "fluid.tab\nCASE X")


def test_approval_payload_refuses_an_existing_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "old.genkey").write_text("kept", encoding="utf-8")
    monkeypatch.setattr(tool_side_effects.workspace, "contained", lambda rel: tmp_path / rel)
    monkeypatch.setattr(tool_side_effects.workspace, "context_identity", lambda: (tmp_path, 1))
    with pytest.raises(tools.ToolError, match="already exists"):
        tool_side_effects.approval_payload(
            "genkey_save", {"save_rel": "old.genkey", "topology": "simple_pipeline"}
        )
