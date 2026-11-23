"""0.1.20 row 9: a sweep preview flags points outside the case's own fluid table; it never blocks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from olga_companion import pvt_range, sweep_selection

_HELPER_PATH = Path(__file__).with_name("test_pvt_range_precheck.py")
_spec = importlib.util.spec_from_file_location("pvt_range_precheck_helpers_r9", _HELPER_PATH)
assert _spec is not None and _spec.loader is not None
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)


def _base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inlet: str) -> Path:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / _helpers.TAB_NAME).write_text(_helpers.make_tab([1_000_000.0, 6_000_000.0], [10.0, 30.0]), encoding="utf-8")
    case = tmp_path / "case.genkey"
    case.write_text(_helpers.make_case(inlet_pressure=inlet), encoding="utf-8")
    return case


def test_an_out_of_table_point_is_flagged_with_where_and_which_way(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _base(tmp_path, monkeypatch, "80 bara")
    flags = pvt_range.range_flags(case)
    outside = [flag for flag in flags if flag["status"] == "outside"]
    assert outside and outside[0]["quantity"] == "pressure" and outside[0]["relation"] == "above"
    assert outside[0]["value"] == "80 bara"
    assert {"origin", "kind", "quantity", "value", "status", "relation"} <= set(outside[0])


def test_a_point_inside_the_table_is_not_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _base(tmp_path, monkeypatch, "40 bara")
    assert [flag for flag in pvt_range.range_flags(case) if flag["status"] == "outside"] == []


def test_a_generated_case_reads_the_base_case_table_and_stays_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The generated copy lives in its own folder without the .tab; the flags use the base case's table.
    base = _base(tmp_path, monkeypatch, "40 bara")
    generated = tmp_path / "_sweep" / "case_001" / "case_001.genkey"
    generated.parent.mkdir(parents=True)
    generated.write_text(_helpers.make_case(inlet_pressure="80 bara"), encoding="utf-8")
    state = sweep_selection.case_from_entry({"index": 1, "path": str(generated), "valid": True, "params": []}, base)
    assert state.valid is True, "a range flag is a warning, never a block"
    assert [flag["status"] for flag in state.range_flags if flag["quantity"] == "pressure"] == ["outside"]


def test_the_preview_status_carries_the_flags() -> None:
    from olga_companion.sweep_monitor import case_status

    state = sweep_selection.SweepCaseState(
        index=0, path=Path("c.genkey"), valid=True, validation_errors=[], params=[], source_sha256="0" * 64,
        companions=[], range_flags=[{"origin": "INLET", "kind": "node", "quantity": "pressure", "value": "80 bara",
                                     "status": "outside", "relation": "above"}],
    )
    assert case_status(state, False)["range_flags"][0]["origin"] == "INLET"
