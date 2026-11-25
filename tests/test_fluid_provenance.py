"""N1: a table made by the app carries a record of its .mfl, so the run preview can say
whether the table is fresh, stale or of unknown origin.

Unknown never reads as fresh or stale: a table made elsewhere has no record, and the
preview says so rather than guessing.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from olga_companion import fluid_provenance as fp
from olga_companion import multiflash_direct as md
from olga_companion.genkey_static import file_sha256

FIX = Path(__file__).parent / "fixtures" / "multiflash"


def _engine(request: dict[str, Any]) -> dict[str, Any]:
    table = (FIX / "handwritten_3x3.tab").read_text(encoding="utf-8")
    Path(request["tab_path"]).write_text(table.replace("LABEL = probe", f"LABEL = {request['title']}", 1), encoding="utf-8")
    return {"ok": True, "errors": []}


def _made(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    case_dir = tmp_path / "ws"
    case_dir.mkdir()
    mfl = case_dir / "gas_water.mfl"
    shutil.copy(FIX / "gas_water.mfl", mfl)
    result = md.make_tab(str(mfl), "case_fluid.tab", engine=_engine)
    return mfl, case_dir / "case_fluid.tab", result


def test_make_tab_writes_a_record_next_to_the_table(tmp_path: Path) -> None:
    mfl, tab, result = _made(tmp_path)
    record_path = tab.with_name("case_fluid.tab.made-from.json")
    assert result["provenance"] == record_path.name
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["schema"] == 1
    assert record["mfl"] == "gas_water.mfl"
    assert record["mfl_sha256"] == file_sha256(mfl)
    assert record["tab_sha256"] == file_sha256(tab)
    assert record["grid"] == {"temperatures_k": [260.0, 300.0, 340.0], "pressures_pa": [50000.0, 1000000.0, 5000000.0]}
    assert record["grid_source"] == "mfl"


def test_a_fresh_table_is_fresh(tmp_path: Path) -> None:
    _, tab, _ = _made(tmp_path)
    assert fp.fluid_freshness(tab) == {"state": "fresh", "reason": "matches", "mfl": "gas_water.mfl"}


def test_editing_the_mfl_makes_the_table_stale(tmp_path: Path) -> None:
    mfl, tab, _ = _made(tmp_path)
    mfl.write_text(mfl.read_text(encoding="utf-8").replace("amounts .8 .1 .1;", "amounts .7 .2 .1;"), encoding="utf-8")
    assert fp.fluid_freshness(tab) == {"state": "stale", "reason": "mfl_changed", "mfl": "gas_water.mfl"}


def test_a_table_without_a_record_is_unknown(tmp_path: Path) -> None:
    tab = tmp_path / "other.tab"
    shutil.copy(FIX / "handwritten_3x3.tab", tab)
    assert fp.fluid_freshness(tab) == {"state": "unknown", "reason": "no_record", "mfl": None}


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        ("tab", "table_changed"),
        ("mfl_gone", "mfl_missing"),
        ("record", "bad_record"),
    ],
)
def test_a_record_that_no_longer_describes_the_table_is_unknown(tmp_path: Path, damage: str, reason: str) -> None:
    mfl, tab, _ = _made(tmp_path)
    if damage == "tab":
        tab.write_bytes(tab.read_bytes() + b"\n")
    elif damage == "mfl_gone":
        mfl.unlink()
    else:
        tab.with_name(tab.name + ".made-from.json").write_text("{not json", encoding="utf-8")
    state = fp.fluid_freshness(tab)
    assert state["state"] == "unknown"
    assert state["reason"] == reason


def test_a_record_naming_an_mfl_outside_the_folder_is_refused(tmp_path: Path) -> None:
    _, tab, _ = _made(tmp_path)
    record_path = tab.with_name(tab.name + ".made-from.json")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["mfl"] = "../outside.mfl"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert fp.fluid_freshness(tab) == {"state": "unknown", "reason": "bad_record", "mfl": None}


def test_a_left_over_record_without_its_table_is_replaced(tmp_path: Path) -> None:
    case_dir = tmp_path / "ws"
    case_dir.mkdir()
    shutil.copy(FIX / "gas_water.mfl", case_dir / "gas_water.mfl")
    (case_dir / "case_fluid.tab.made-from.json").write_text('{"schema": 1, "mfl": "old.mfl"}', encoding="utf-8")
    md.make_tab(str(case_dir / "gas_water.mfl"), "case_fluid.tab", engine=_engine)
    assert fp.fluid_freshness(case_dir / "case_fluid.tab")["state"] == "fresh"


def test_a_failed_make_leaves_no_record(tmp_path: Path) -> None:
    case_dir = tmp_path / "ws"
    case_dir.mkdir()
    shutil.copy(FIX / "gas_water.mfl", case_dir / "gas_water.mfl")
    with pytest.raises(Exception):
        md.make_tab(str(case_dir / "gas_water.mfl"), "case_fluid.tab", engine=lambda _r: {"ok": False, "errors": [1]}, error_file=FIX / "mini.err")
    assert sorted(p.name for p in case_dir.iterdir()) == ["gas_water.mfl"]


def test_preview_freshness_lists_found_pvt_tables_only(tmp_path: Path) -> None:
    _, tab, _ = _made(tmp_path)
    companions = [
        {"kind": "pvt", "reference": "case_fluid.tab", "resolved_path": str(tab), "found": True},
        {"kind": "pvt", "reference": "missing.tab", "resolved_path": str(tab.with_name("missing.tab")), "found": False},
        {"kind": "restart", "reference": "r.rsw", "resolved_path": str(tab.with_name("r.rsw")), "found": True},
    ]
    assert fp.preview_freshness(companions) == [
        {"reference": "case_fluid.tab", "state": "fresh", "reason": "matches", "mfl": "gas_water.mfl"},
    ]



def test_the_run_preview_carries_freshness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from olga_companion import runner
    from olga_runtime_test_support import _installed_release

    _, tab, _ = _made(tmp_path)
    case = tab.with_name("case.genkey")
    case.write_text('CASE LABEL=case\nFILES PVTFILE="case_fluid.tab"\nENDCASE\n', encoding="utf-8")
    installs = tmp_path / "installs"
    _installed_release(installs, "2025.1.0", opi=False)
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(runner, "OLGA_EXE_GLOBS", [str(installs / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe")])
    monkeypatch.setattr(runner, "_validate_case", lambda _path: {"valid": True, "command": {}})
    monkeypatch.setattr(runner, "ensure_broker", lambda: SimpleNamespace(to_dict=lambda: {"protocol": "test", "sha256": "b" * 64}))

    fresh = runner.preview_run(str(case))
    assert fresh["fluid_freshness"] == [
        {"reference": "case_fluid.tab", "state": "fresh", "reason": "matches", "mfl": "gas_water.mfl"},
    ]
    mfl = tab.with_name("gas_water.mfl")
    mfl.write_bytes(mfl.read_bytes() + b"\n")
    stale = runner.preview_run(str(case))
    assert stale["fluid_freshness"][0]["state"] == "stale"
    assert stale["selection_id"] == fresh["selection_id"]


def test_a_record_that_cannot_be_written_leaves_the_table_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review: the table is already in place, so a failed record write is not a failed make."""
    def refuse(*_args: Any, **_kwargs: Any) -> Path:
        raise PermissionError("folder is read-only")

    monkeypatch.setattr(fp, "write_record", refuse)
    _, tab, result = _made(tmp_path)
    assert tab.is_file()
    assert result["provenance"] is None
    assert result["provenance_error"] == "record_not_written"
    assert fp.fluid_freshness(tab) == {"state": "unknown", "reason": "no_record", "mfl": None}
