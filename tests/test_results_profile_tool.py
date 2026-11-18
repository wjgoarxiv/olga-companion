"""results_profile reads one variable along a branch at one time from a .ppl result.

Hyper-real round 4 (2026-11-11): asked where water collects in a pipe with a low dip, the
model had no tool that returns values along the pipe. results_series only reads trends
("Could not read a series for 'HOL' from case.ppl.") and it retried until the turn budget
ran out. results.variable_profile already served the Results view.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from olga_companion.agent import result_tools, tool_read_tools, tools
from olga_companion.agent.tool_validation import PathBindings, ToolError, validate_tool_arguments


def _paths(source: Path) -> PathBindings:
    return PathBindings(
        input_file=lambda value, _suffixes: value,
        result_file=lambda _value: str(source),
        set_active_case=lambda _value: None,
    )


@pytest.fixture
def ppl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[tuple]]:
    source = tmp_path / "case.ppl"
    source.write_bytes(b"stable profile source")
    calls: list[tuple] = []

    def fake_profile(path: str, variable: str, branch: str, timestep: float | None = None) -> dict[str, Any]:
        calls.append((path, variable, branch, timestep))
        return {
            "path": path,
            "variable": variable,
            "branch": branch,
            "timestep": 3600.069 if timestep is None else timestep,
            "timestep_unit": "s",
            "positions": [5.0, 105.0, 125.0, 135.0, 195.0],
            "values": [0.21, 0.22, 0.48, 0.52, 0.20],
            "unit": "-",
        }

    monkeypatch.setattr(result_tools.results, "variable_profile", fake_profile)
    monkeypatch.setattr(result_tools.results, "load_result", lambda _p: {"timesteps": [3600.069]})
    return source, calls


def test_a_profile_comes_back_as_position_rows_with_its_maximum(ppl) -> None:
    source, calls = ppl
    result = tool_read_tools.results_profile(
        {"result_id": "run:abc123/case.ppl", "variable": "HOL", "branch": "MAIN"}, _paths(source)
    )
    assert calls == [(str(source), "HOL", "MAIN", None)]
    assert result["rows"][2] == {"position": 125.0, "value": 0.48}
    assert result["timestep"] == 3600.069
    assert result["units"] == {"position": "m", "value": "-"}
    assert result["maximum"] == {"position": 135.0, "value": 0.52}
    assert result["minimum"] == {"position": 195.0, "value": 0.20}
    assert result["lineage"] == {"source_kind": "run", "source_id": "run:abc123/case.ppl"}


def test_undefined_sections_are_skipped_and_counted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Review of R4-4: the parser turns NaN into null, and one null used to refuse the read.
    source = tmp_path / "case.ppl"
    source.write_bytes(b"profile with a gap")
    monkeypatch.setattr(
        result_tools.results,
        "variable_profile",
        lambda *_a, **_k: {
            "timestep": 600.0,
            "positions": [1.0, 3.0, 5.0, 7.0],
            "values": [0.3, None, 0.8, 0.2],
            "unit": "-",
        },
    )
    monkeypatch.setattr(result_tools.results, "load_result", lambda _p: {"timesteps": [600.0]})
    result = tool_read_tools.results_profile(
        {"result_id": "run:abc123/case.ppl", "variable": "HOL", "branch": "MAIN"}, _paths(source)
    )
    assert [row["position"] for row in result["rows"]] == [1.0, 5.0, 7.0]
    assert result["skipped_rows"] == 1
    assert result["maximum"] == {"position": 5.0, "value": 0.8}


def test_the_change_since_the_previous_saved_time_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Round 5 (build F): at 600 s a liquid front was still crossing the outlet (HOL 0.82),
    # and the model told a novice that the outlet is where water collects. The profile
    # one save earlier differed by 0.5 there; reporting that change lets the model see it.
    source = tmp_path / "case.ppl"
    source.write_bytes(b"developing profile")
    frames = {
        450.0: [0.27, 0.07, 0.30],
        600.0: [0.27, 0.07, 0.82],
    }

    def fake_profile(_path, _variable, _branch, timestep=None):
        chosen = 600.0 if timestep is None else timestep
        return {"timestep": chosen, "positions": [10.0, 110.0, 199.0], "values": frames[chosen], "unit": "-"}

    monkeypatch.setattr(result_tools.results, "variable_profile", fake_profile)
    monkeypatch.setattr(
        result_tools.results, "load_result", lambda _p: {"timesteps": [0.0, 150.0, 300.0, 450.0, 600.0]}
    )
    result = tool_read_tools.results_profile(
        {"result_id": "run:abc123/case.ppl", "variable": "HOL", "branch": "MAIN"}, _paths(source)
    )
    change = result["change_since_previous"]
    assert change["previous_timestep"] == 450.0
    assert change["max_change"] == pytest.approx(0.52)
    assert change["at_position"] == 199.0
    assert result["timesteps"] == [0.0, 150.0, 300.0, 450.0, 600.0]


def test_many_saved_times_list_only_the_newest_and_the_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Review of R5-2: 600 saved times overflow the 16 KB result cap, and the cap keeps the
    # first 50 list items, which drops the latest times the model needs.
    source = tmp_path / "case.ppl"
    source.write_bytes(b"long run")
    times = [float(t) for t in range(0, 6000, 10)]
    monkeypatch.setattr(
        result_tools.results,
        "variable_profile",
        lambda _p, _v, _b, timestep=None: {
            "timestep": times[-1] if timestep is None else timestep,
            "positions": [1.0, 2.0],
            "values": [0.4, 0.5],
            "unit": "-",
        },
    )
    monkeypatch.setattr(result_tools.results, "load_result", lambda _p: {"timesteps": times})
    result = tool_read_tools.results_profile(
        {"result_id": "run:abc123/case.ppl", "variable": "HOL", "branch": "MAIN"}, _paths(source)
    )
    assert result["timestep_count"] == 600
    assert len(result["timesteps"]) <= 20
    assert result["timesteps"][-1] == times[-1]
    assert result["timesteps"][0] == times[0]


def test_a_time_with_no_defined_value_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "case.ppl"
    source.write_bytes(b"all undefined")
    monkeypatch.setattr(
        result_tools.results,
        "variable_profile",
        lambda *_a, **_k: {"timestep": 0.0, "positions": [1.0, 2.0], "values": [None, None], "unit": "-"},
    )
    monkeypatch.setattr(result_tools.results, "load_result", lambda _p: {"timesteps": [0.0]})
    with pytest.raises(ToolError, match="no defined values"):
        tool_read_tools.results_profile(
            {"result_id": "run:abc123/case.ppl", "variable": "HOL", "branch": "MAIN"}, _paths(source)
        )


def test_an_unreadable_previous_profile_keeps_the_current_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "case.ppl"
    source.write_bytes(b"previous frame unreadable")

    def fake_profile(_path, _variable, _branch, timestep=None):
        if timestep is not None:
            raise ValueError("frame 450 is damaged")
        return {"timestep": 600.0, "positions": [1.0], "values": [0.5], "unit": "-"}

    monkeypatch.setattr(result_tools.results, "variable_profile", fake_profile)
    monkeypatch.setattr(result_tools.results, "load_result", lambda _p: {"timesteps": [450.0, 600.0]})
    result = tool_read_tools.results_profile(
        {"result_id": "run:abc123/case.ppl", "variable": "HOL", "branch": "MAIN"}, _paths(source)
    )
    assert result["rows"] == [{"position": 1.0, "value": 0.5}]
    assert result["change_since_previous"] is None


def test_the_first_saved_time_has_no_previous_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "case.ppl"
    source.write_bytes(b"first frame")
    monkeypatch.setattr(
        result_tools.results,
        "variable_profile",
        lambda *_a, **_k: {"timestep": 0.0, "positions": [1.0], "values": [0.5], "unit": "-"},
    )
    monkeypatch.setattr(result_tools.results, "load_result", lambda _p: {"timesteps": [0.0, 600.0]})
    result = tool_read_tools.results_profile(
        {"result_id": "run:abc123/case.ppl", "variable": "HOL", "branch": "MAIN", "timestep": 0},
        _paths(source),
    )
    assert result["change_since_previous"] is None


def test_a_chosen_timestep_is_passed_on(ppl) -> None:
    source, calls = ppl
    tool_read_tools.results_profile(
        {"result_id": "run:abc123/case.ppl", "variable": "HOL", "branch": "MAIN", "timestep": 900},
        _paths(source),
    )
    assert calls[0][3] == 900


def test_a_trend_file_is_refused_with_the_right_tool_named(tmp_path: Path) -> None:
    source = tmp_path / "case.tpl"
    source.write_bytes(b"trend")
    with pytest.raises(ToolError, match="results_series"):
        tool_read_tools.results_profile(
            {"result_id": "run:abc123/case.tpl", "variable": "HOL", "branch": "MAIN"}, _paths(source)
        )


def test_the_tool_is_offered_and_needs_a_branch() -> None:
    tool = tools.TOOLS["results_profile"]
    assert not tool.side_effect
    with pytest.raises(ToolError):
        validate_tool_arguments(
            "results_profile", {"result_id": "run:abc123/case.ppl", "variable": "HOL"}, tool.parameters
        )
