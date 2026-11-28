"""An edit plan lists the validator warnings of the new case, so a worse case is not called clean.

Found 2026-11-28: SEABED 1200 -> 1500 m in an app case left P008 at 6.25x (5.00x before), yet the
plan's validation carried no diagnostics and the assistant told the user there were none.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from case_spec_v2_support import PVT_TABLE_TEXT, with_v2_inputs
from test_case_edit_routes import _plan, _rows, ws  # noqa: F401

from olga_companion.case_compiler_toolkit import validator_warnings
from olga_companion.case_transaction_models import TransactionFailure
from olga_companion.case_transactions import plan_case_edits

_FIXTURE = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"

_REPORT = """Validation Report: x.genkey
========================================
ERRORS:   0
WARNINGS: 1
INFO:     1

WARNINGS
--------
[P008] Neighbouring sections in 'EXPORT' differ by 6.25x (SEABED 62.5 -> RISER 10)
       Location : EXPORT / PIPE RISER
       Suggestion: Grade the section lengths so neighbours stay within a 0.5-2 ratio

INFO
----
[I001] Something only informative
"""


def test_validator_warnings_reads_only_the_warning_section() -> None:
    assert validator_warnings(_REPORT) == (
        "[P008] Neighbouring sections in 'EXPORT' differ by 6.25x (SEABED 62.5 -> RISER 10)",
    )
    assert validator_warnings("ERRORS:   0\nWARNINGS: 0\nINFO:     0\n\nNo issues found.\n") == ()


def _spec(first_sections: int) -> dict:
    spec = with_v2_inputs({
        "version": "1",
        "nodes": [
            {"label": "SOURCE", "kind": "source", "pressure_pa": 2_000_000.0},
            {"label": "SINK", "kind": "sink", "pressure_pa": 1_000_000.0},
        ],
        "flowpaths": [{"label": "MAIN", "from": "SOURCE", "to": "SINK", "pipes": [
            {"label": "A", "length_m": 100.0, "elevation_m": 0.0, "diameter_m": 0.1, "sections": first_sections},
            {"label": "B", "length_m": 100.0, "elevation_m": 0.0, "diameter_m": 0.1, "sections": 10},
        ]}],
        "pvt_reference": "fluid.tab",
        "integration": {"end_time_s": 3600.0},
        "outputs": ["PT"],
    })
    spec["version"] = "3"
    return spec


def _owner(tmp_path: Path) -> tuple[Path, str]:
    owner = tmp_path / "owner.genkey"
    owner.write_bytes(b"CASE LABEL=owner\nENDCASE\n")
    (tmp_path / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    return owner, hashlib.sha256(owner.read_bytes()).hexdigest()


def _casespec_plan(tmp_path: Path, first_sections: int):
    owner, source_hash = _owner(tmp_path)
    return plan_case_edits(
        _spec(first_sections), [{"op": "set_integration", "end_time_s": 7200.0}],
        expected_hash=source_hash, owner_source=owner, workspace_root=tmp_path,
    )


def test_a_casespec_plan_with_a_warning_stays_publishable_and_lists_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "journal"))
    plan = _casespec_plan(tmp_path, first_sections=2)  # 50 m sections next to 10 m ones
    assert not isinstance(plan, TransactionFailure), plan
    assert plan.publishable is True
    assert any(line.startswith("[P008]") for line in plan.validation.warnings), plan.validation


def test_a_clean_casespec_plan_lists_no_warning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "journal"))
    plan = _casespec_plan(tmp_path, first_sections=10)
    assert not isinstance(plan, TransactionFailure), plan
    assert plan.validation.warnings == ()


def test_the_table_plan_of_a_hand_written_case_names_the_new_warning(ws: Path) -> None:  # noqa: F811
    case = ws / "owner.genkey"
    case.write_text(_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    rows = _rows(case)
    plan = _plan(rows, [{"op": "set_pipe_length", "flowpath": "FLOWPATH_1", "pipe": "Pipe_1", "length_m": 300.0}]).json()
    assert plan["publishable"] is True, plan
    assert any(line.startswith("[P008]") for line in plan["validation"]["warnings"]), plan["validation"]


def test_the_table_plan_of_a_clean_edit_names_no_warning(ws: Path) -> None:  # noqa: F811
    case = ws / "owner.genkey"
    case.write_text(_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    plan = _plan(_rows(case), [{"op": "set_pipe_length", "flowpath": "FLOWPATH_1", "pipe": "Pipe_1", "length_m": 110.0}]).json()
    assert plan["publishable"] is True, plan
    assert plan["validation"]["warnings"] == []
