"""Endpoints mode through the chat import tool: codes, options, docs template."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from olga_companion.agent import approvals, tools
from olga_companion.agent.pipe_table_tools import READ_REFUSAL_CODES
from olga_companion.agent.pipe_table_tools import _issues as _tool_issues
from olga_companion.pipe_table import PipeTable, read_table
from olga_companion.pipe_table_endpoints import ENDPOINT_ISSUE_CODES, rows_from_endpoints
from olga_companion.pipe_table_import import ImportOptions, build_case_spec

_TESTS = Path(__file__).parent
_TABLES = _TESTS / "fixtures" / "pipe_tables"
ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "examples" / "pipe_table_endpoints_template.csv"
ENDPOINT_FIXTURE = ROOT / "frontend" / "tests" / "fixtures" / "pipe-endpoint-issue-codes.json"
READ_REFUSAL_FIXTURE = ROOT / "frontend" / "tests" / "fixtures" / "pipe-read-refusal-codes.json"
OPTIONS = ImportOptions(
    pvt_reference="fluid.tab", fluid_label="TEST_FLUID", thermal={"model": "adiabatic"},
    end_time_s=600.0, max_section_m=1.0,
)

PIPE_HEADER = (
    "pipe,x_start_m,y_start_m,z_start_m,x_m,y_m,z_m,"
    "inner_diameter_m,roughness_m,node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction"
)
TWO_PIPES = (
    "T1,0,0,0,10,0,0,0.05,0.00005,,,,,,\n"
    "T2,10,0,0,20,0,0,0.05,0.00005,,,,,,\n"
)


def _endpoint_table(*rows: str) -> str:
    return PIPE_HEADER + "\n" + "".join(rows)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    shutil.copyfile(_TESTS / "fixtures" / "fluids" / "fluid.tab", workspace_root / "fluid.tab")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    monkeypatch.setenv("OLGA_CASE_DRAFT_DIR", str(tmp_path / "drafts"))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    approvals.revoke_all()
    yield workspace_root
    approvals.revoke_all()


def _write(workspace: Path, name: str, text: str) -> str:
    (workspace / name).write_text(text, encoding="utf-8")
    return name


def _base_args(path: str, **override) -> dict:
    args = {
        "path": path,
        "pvt_reference": "fluid.tab",
        "fluid_label": "FLUID-A",
        "thermal": {"model": "adiabatic"},
        "end_time_s": 600,
        **override,
    }
    return args


def test_endpoints_issue_codes_registry_is_a_tuple() -> None:
    assert isinstance(ENDPOINT_ISSUE_CODES, tuple)
    assert len(ENDPOINT_ISSUE_CODES) >= 10
    assert all(isinstance(code, str) and code for code in ENDPOINT_ISSUE_CODES)
    assert all(code.startswith("endpoints_") for code in ENDPOINT_ISSUE_CODES)
    assert len(set(ENDPOINT_ISSUE_CODES)) == len(ENDPOINT_ISSUE_CODES)


def test_endpoint_fixture_matches_the_registry() -> None:
    assert ENDPOINT_FIXTURE.is_file(), f"missing endpoint fixture {ENDPOINT_FIXTURE}"
    assert json.loads(ENDPOINT_FIXTURE.read_text(encoding="utf-8")) == list(ENDPOINT_ISSUE_CODES)


def test_tool_lists_ends_then_builds_once_nodes_are_added(root: Path) -> None:
    name = _write(root, "endpoints.csv", _endpoint_table(TWO_PIPES))
    first = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert first["created"] is False
    assert first["issues"], "expected missing-boundary issues"
    assert {issue["code"] for issue in first["issues"]} <= {
        "missing_boundary_row", "missing_inlet_sink"}
    assert any(issue["code"] == "missing_boundary_row" for issue in first["issues"])
    assert [entry["name"] for entry in first["ends"]] == ["END_001", "END_002"]
    assert first["merged_rows"] == [{"flowpath": "FP_001", "rows": [2, 3], "total": 2}]

    node_rows = (
        ",,,,,,,,,END_001,source,5.0,25.0,1.0,0.0\n"
        ",,,,,,,,,END_002,sink,1.0,25.0,0.5,0.0\n"
    )
    name = _write(root, "endpoints_nodes.csv", _endpoint_table(TWO_PIPES, node_rows))
    second = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert second["created"] is True, second.get("issues")
    assert second["counts"]["flowpaths"] == 1
    assert [entry["name"] for entry in second["ends"]] == ["END_001", "END_002"]


def test_protected_workbook_refusal_carries_its_code(root: Path) -> None:
    # Neutral synthetic DRM-wrapper marker (not any real vendor tag).
    (root / "locked.xlsx").write_bytes(b"XXXDRMC\xb8" + b"\x00" * 8)
    result = tools.dispatch("pipe_table_import", _base_args("locked.xlsx"))
    assert result["created"] is False
    assert result["issue_count"] == 1
    assert result["issues"][0]["code"] == "table_encrypted"
    assert result["issues"][0]["reason"] == (
        "the file is protected (encrypted or DRM); save an unprotected copy")


def test_read_refusal_fixture_matches_the_registry() -> None:
    assert json.loads(READ_REFUSAL_FIXTURE.read_text(encoding="utf-8")) == list(READ_REFUSAL_CODES)


def test_plain_unreadable_workbook_still_raises(root: Path) -> None:
    from olga_companion.agent.tool_validation import ToolError

    name = _write(root, "junk.xlsx", "not a workbook at all\n")
    with pytest.raises(ToolError, match="could not be read"):
        tools.dispatch("pipe_table_import", _base_args(name))


def test_refused_endpoints_result_lists_only_the_missing_node_rows(
    root: Path,
) -> None:
    import json as _json

    result = tools.dispatch("pipe_table_import", _base_args(
        _write(root, "endpoints.csv", _endpoint_table(TWO_PIPES)),
        layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is False
    assert result["missing"] == {
        "node_rows": ["END_001", "END_002"],
        "node_rows_total": 2,
        "values": [],
    }
    assert "roughness_m" not in _json.dumps(result["missing"])
    assert "vertical" not in _json.dumps(result["missing"]).lower()


def test_refused_endpoints_result_lists_truly_missing_values(
    root: Path,
) -> None:
    text = (
        "pipe,x_start_m,y_start_m,z_start_m,x_m,y_m,z_m,inner_diameter_m\n"
        "P1,0,0,0,10,0,0,0.05\n"
    )
    result = tools.dispatch("pipe_table_import", _base_args(
        _write(root, "no_rough.csv", text),
        layout="endpoints", vertical_axis="y",
    ))
    assert result["created"] is False
    assert result["missing"]["values"] == [{"field": "roughness_m", "rows": [2]}]
    assert result["missing"]["node_rows"] == []
    assert result["missing"]["node_rows_total"] == 0


def test_refused_endpoints_result_caps_node_rows_at_100(
    root: Path,
) -> None:
    from olga_companion.agent.pipe_table_tools import _result_size

    pipes = "".join(
        f"P{n},0,{10 * n},0,10,{10 * n},0,0.05,0.00005,,,,,,\n" for n in range(1400)
    )
    result = tools.dispatch("pipe_table_import", _base_args(
        _write(root, "many.csv", _endpoint_table(pipes)),
        layout="endpoints", vertical_axis="y", roughness_m=5e-05,
        segmentation={"max_section_m": 100.0},
    ))
    assert result["created"] is False
    assert len(result["missing"]["node_rows"]) == 100
    assert result["missing"]["node_rows_total"] == 2800
    assert _result_size(result) <= 16384


def test_mid_segment_touch_imports_three_flowpaths_with_split_report(
    root: Path,
) -> None:
    text = _endpoint_table(
        "BAR,0,0,0,20,0,0,0.05,0.00005,,,,,,\n"
        "STEM,10,0,0,10,10,0,0.05,0.00005,,,,,,\n"
        ",,,,,,,,,END_001,source,5.0,25.0,1.0,0.0\n"
        ",,,,,,,,,END_002,sink,1.0,25.0,0.5,0.0\n"
        ",,,,,,,,,END_003,sink,1.0,25.0,0.5,0.0\n"
    )
    result = tools.dispatch("pipe_table_import", _base_args(
        _write(root, "tee.csv", text),
        layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is True, result.get("issues")
    assert result["counts"]["flowpaths"] == 3
    assert result["split_rows_total"] == 1
    assert result["split_rows"][0]["at"] == [10.0, 0.0, 0.0]
    assert result["split_rows"][0]["line"] == 2


def test_valve_at_a_split_point_is_refused_with_its_code(
    root: Path,
) -> None:
    text = (
        PIPE_HEADER + ",valve,valve_position,valve_schedule,valve_diameter_m\n"
        "BAR,0,0,0,10,0,0,0.05,0.00005,,,,,,V1,0.5,0:1,0.04\n"
        "STEM,5,0,0,5,10,0,0.05,0.00005,,,,,,,,,\n"
        ",,,,,,,,,END_001,source,5.0,25.0,1.0,0.0,,,,\n"
        ",,,,,,,,,END_002,sink,1.0,25.0,0.5,0.0,,,,\n"
        ",,,,,,,,,END_003,sink,1.0,25.0,0.5,0.0,,,,\n"
    )
    result = tools.dispatch("pipe_table_import", _base_args(
        _write(root, "tee_valve.csv", text),
        layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is False
    codes = [issue["code"] for issue in result["issues"]]
    assert "endpoints_valve_at_split" in codes


def test_skipped_split_pass_is_reported_not_silent(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import olga_companion.pipe_table_endpoints as endpoints

    monkeypatch.setattr(endpoints, "_SPLIT_MAX_TOTAL_SAMPLES", 10, raising=False)
    text = _endpoint_table(
        "BAR,0,0,0,10,0,0,0.05,0.00005,,,,,,\n"
        "STEM,5,0,0,5,10,0,0.05,0.00005,,,,,,\n"
    )
    result = tools.dispatch("pipe_table_import", _base_args(
        _write(root, "tee.csv", text),
        layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is False
    assert result["split_skipped"] is True
    assert "skipped for size" in result["split_note"]
    ends = {entry["name"]: entry for entry in result["ends"]}
    touch = next(
        name for name, entry in ends.items() if entry["x_m"] == 5.0)
    assert touch in result["missing"]["node_rows"]


def _skipped_split_result(
    root: Path, monkeypatch: pytest.MonkeyPatch, locale: str | None,
) -> dict:
    import olga_companion.pipe_table_endpoints as endpoints
    from olga_companion.agent import tool_locale

    monkeypatch.setattr(endpoints, "_SPLIT_MAX_TOTAL_SAMPLES", 10, raising=False)
    text = _endpoint_table(
        "BAR,0,0,0,10,0,0,0.05,0.00005,,,,,,\n"
        "STEM,5,0,0,5,10,0,0.05,0.00005,,,,,,\n"
    )
    args = _base_args(
        _write(root, "tee.csv", text),
        layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    )
    with tool_locale.using(locale):
        return tools.dispatch("pipe_table_import", args)


def _has_hangul(text: str) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in text)


def test_split_note_follows_the_korean_ui_locale(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _skipped_split_result(root, monkeypatch, "ko")
    note = result["split_note"]
    assert result["split_skipped"] is True
    assert _has_hangul(note)
    assert "split pass" not in note and "skipped for size" not in note
    assert "해요" in note or note.rstrip().endswith("요.")


def test_split_note_follows_the_english_ui_locale(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _skipped_split_result(root, monkeypatch, "en")
    note = result["split_note"]
    assert "skipped for size" in note
    assert not _has_hangul(note)


def test_split_note_without_a_locale_keeps_both_languages(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    note = _skipped_split_result(root, monkeypatch, None)["split_note"]
    assert "skipped for size" in note
    assert _has_hangul(note)


def test_early_endpoint_refusal_carries_split_extras(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import olga_companion.pipe_table_endpoints as endpoints

    monkeypatch.setattr(endpoints, "_SPLIT_MAX_TOTAL_SAMPLES", 10, raising=False)
    text = _endpoint_table(
        "P1,0,0,0,10,0,0,0.05,0.00005,,,,,,\n"
        "P2,10.05,0,0,20,0,0,0.05,0.00005,,,,,,\n"
    )
    result = tools.dispatch("pipe_table_import", _base_args(
        _write(root, "near.csv", text),
        layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is False
    assert {issue["code"] for issue in result["issues"]} == {"endpoints_near_miss"}
    assert result["split_skipped"] is True
    assert "skipped for size" in result["split_note"]
    assert result["ends"] == []


def test_created_response_carries_skip_flag(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import olga_companion.pipe_table_endpoints as endpoints

    monkeypatch.setattr(endpoints, "_SPLIT_MAX_TOTAL_SAMPLES", 10, raising=False)
    text = _endpoint_table(
        TWO_PIPES
        + ",,,,,,,,,END_001,source,5.0,25.0,1.0,0.0\n"
        + ",,,,,,,,,END_002,sink,1.0,25.0,0.5,0.0\n"
    )
    result = tools.dispatch("pipe_table_import", _base_args(
        _write(root, "chain.csv", text),
        layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is True, result.get("issues")
    assert result["split_skipped"] is True
    assert "skipped for size" in result["split_note"]


def test_shrink_keeps_the_skip_flag_and_note() -> None:
    from olga_companion.agent import tool_validation
    from olga_companion.agent.pipe_table_tools import (
        _result_size,
        _shrink_to_totals,
    )

    probe: dict[str, object] = {
        "ends": [
            {"name": f"END_{n:03d}", "x_m": float(n), "y_m": 0.0, "z_m": 0.0}
            for n in range(300)
        ],
        "merged_rows": [
            {"flowpath": f"FP_{n:03d}", "rows": list(range(50)), "total": 50}
            for n in range(20)
        ],
        "split_skipped": True,
        "split_note": "The split pass was skipped for size.",
    }
    assert _result_size(probe) > tool_validation.MAX_RESULT_BYTES
    _shrink_to_totals(probe)
    assert _result_size(probe) <= tool_validation.MAX_RESULT_BYTES
    assert probe["split_skipped"] is True
    assert probe["split_note"] == "The split pass was skipped for size."


def test_refused_endpoints_result_names_file_rows_for_end_nodes(
    root: Path,
) -> None:
    result = tools.dispatch("pipe_table_import", _base_args(
        _write(root, "endpoints.csv", _endpoint_table(TWO_PIPES)),
        layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is False
    assert result["missing"]["node_rows"] == ["END_001", "END_002"]
    assert "node, node_kind" in result["next_step"]
    assert "table file" in result["next_step"]
    assert "in chat" in result["next_step"]


def test_tool_endpoints_options_are_validated(root: Path) -> None:
    from olga_companion.agent.tool_validation import ToolError
    from olga_companion.agent.tools import ToolPreDispatchError

    name = _write(root, "endpoints.csv", _endpoint_table(TWO_PIPES))
    with pytest.raises(ToolError, match="vertical_axis"):
        tools.dispatch("pipe_table_import", _base_args(name, layout="endpoints"))
    with pytest.raises(ToolPreDispatchError, match="roughness"):
        tools.dispatch("pipe_table_import", _base_args(
            name, layout="endpoints", vertical_axis="y", roughness_m=-1.0,
        ))
    with pytest.raises(ToolError, match="roughness"):
        tools.dispatch("pipe_table_import", _base_args(
            name, layout="endpoints", vertical_axis="y", roughness_m="much",
        ))


def test_tool_surfaces_reader_issues_with_reader_codes(root: Path) -> None:
    bad_length = (
        "pipe,x_start_m,y_start_m,z_start_m,x_m,y_m,z_m,"
        "inner_diameter_m,roughness_m,length_m\n"
        "P1,0,0,0,10,0,0,0.05,0.00005,abc\n"
    )
    name = _write(root, "bad_length.csv", bad_length)
    result = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y",
    ))
    assert result["created"] is False
    assert {(issue["row"], issue["code"]) for issue in result["issues"]} >= {
        (2, "reader_not_a_number")}
    bad_unit = (
        "pipe,x_start_m,y_start_m,z_start_m,x (furlongs),y_m,z_m,"
        "inner_diameter_m,roughness_m\n"
        "P1,0,0,0,10,0,0,0.05,0.00005\n"
    )
    name = _write(root, "bad_unit.csv", bad_unit)
    result = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y",
    ))
    assert result["created"] is False
    assert {(issue["row"], issue["code"]) for issue in result["issues"]} >= {
        (2, "reader_unknown_length_unit")}


def test_created_draft_with_122_ends_is_capped_and_single(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json as _json

    from olga_companion import case_draft_store

    pipes = ["TRUNK,0,0,0,10,0,0,0.05,0.00005,,,,,,\n"]
    for junction in range(1, 25):
        x = 10.0 * junction
        if junction > 1:
            pipes.append(
                f"J{junction - 1}J{junction},{x - 10},0,0,{x},0,0,0.05,0.00005,,,,,,\n")
        leaves = 6 if junction == 24 else 5
        for leaf in range(1, leaves + 1):
            pipes.append(
                f"L{junction}_{leaf},{x},0,0,{x},{10 + 3 * leaf},{2 * leaf},"
                "0.04,0.00005,,,,,,\n")
    name = _write(root, "many_junctions.csv", _endpoint_table("".join(pipes)))
    first = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert first["created"] is False
    assert len(first["ends"]) == 100
    assert first["ends_total"] == 122
    node_rows = ",,,,,,,,,END_001,source,5.0,25.0,1.0,0.0\n" + "".join(
        f",,,,,,,,,END_{number:03d},sink,1.0,25.0,0.5,0.0\n" for number in range(2, 123)
    )
    name = _write(root, "many_junctions_nodes.csv", _endpoint_table("".join(pipes), node_rows))
    created = []
    real_create = case_draft_store.create_draft

    def counting(*args, **kwargs):
        created.append(1)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(case_draft_store, "create_draft", counting)
    second = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert second["created"] is True, second.get("issues")
    assert created == [1]
    assert len(second["ends"]) == 100
    assert second["ends_total"] == 122
    assert len(_json.dumps(second)) < 16 * 1024


def test_refusal_with_50_long_chains_stays_under_16kib(root: Path) -> None:
    import json as _json

    pipes = "".join(
        f"C{chain}_{i},{100000.0 * chain + 10.0 * i},0,0,"
        f"{100000.0 * chain + 10.0 * i + 10},0,0,0.05,0.00005,,,,,,\n"
        for chain in range(50) for i in range(100)
    )
    name = _write(root, "many_chains.csv", _endpoint_table(pipes))
    result = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is False
    assert result["merged_rows_total"] == 50
    assert all(entry["rows"] == [] for entry in result["merged_rows"])
    assert len(_json.dumps(result)) < 16 * 1024


def test_refusal_shrink_slices_ends_but_keeps_one() -> None:
    import json as _json

    from olga_companion.agent.pipe_table_tools import _shrink_to_totals
    from olga_companion.agent.tool_validation import MAX_RESULT_BYTES

    rows = []
    for chain in range(50):
        for i in range(100):
            x = 100000.0 * chain + 10.0 * i
            rows.append(_pipe_row((x, 0, 0), (x + 10, 0, 0)))
    _out, _issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert summary["ends_total"] == 100
    assert summary["merged_rows_total"] == 50
    reason = ("the table needs a node row for every END before the case builds; " * 4)[:200]
    probe = {
        "created": False,
        "issue_count": 20,
        "issues": [
            {"row": number, "field": "f" * 64, "code": "flowpath_nodes_disagree",
             "params": {"flowpath": "F" * 48}, "reason": reason}
            for number in range(2, 22)
        ],
        "note": "No draft was made. The table needs these fixes first.",
        "ends": [dict(entry) for entry in summary["ends"]],
        "ends_total": summary["ends_total"],
        "merged_rows": [
            {"flowpath": entry["flowpath"], "rows": list(entry["rows"]),
             "total": entry["total"]}
            for entry in summary["merged_rows"]
        ],
        "merged_rows_total": summary["merged_rows_total"],
    }
    assert len(_json.dumps(probe)) > MAX_RESULT_BYTES
    before = [dict(issue) for issue in probe["issues"]]
    _shrink_to_totals(probe)
    assert len(_json.dumps(probe)) <= MAX_RESULT_BYTES
    assert 1 <= len(probe["ends"]) < 100
    assert probe["ends_total"] == 100
    assert all(entry["rows"] == [] for entry in probe["merged_rows"])
    assert probe["issues"] == before


def test_created_draft_with_long_chains_stays_under_16kib(root: Path) -> None:
    import json as _json

    pipes = ["TRUNK,0,0,0,100,0,0,0.05,0.00005,,,,,,\n"]
    for junction in range(1, 16):
        x = 100.0 * junction
        if junction > 1:
            pipes.append(
                f"J{junction - 1}J{junction},{x - 100},0,0,{x},0,0,0.05,0.00005,,,,,,\n")
        for pipe in range(200):
            pipes.append(
                f"L{junction}_{pipe},{x},{0.05 * pipe},0,{x},{0.05 * pipe + 0.05},0,"
                "0.04,0.00005,,,,,,\n")
    name = _write(root, "spool_farm.csv", _endpoint_table("".join(pipes)))
    node_rows = ",,,,,,,,,END_001,source,5.0,25.0,1.0,0.0\n" + "".join(
        f",,,,,,,,,END_{number:03d},sink,1.0,25.0,0.5,0.0\n" for number in range(2, 17)
    )
    name = _write(root, "spool_farm_nodes.csv", _endpoint_table("".join(pipes), node_rows))
    result = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is True, result.get("issues")
    assert result["merged_rows_total"] == 15
    assert len(_json.dumps(result)) < 16 * 1024


def test_long_merged_chain_lists_capped_rows(root: Path) -> None:
    import json as _json

    pipes = "".join(
        f"P{i},{10.0 * i},0,0,{10.0 * i + 10},0,0,0.05,0.00005,,,,,,\n" for i in range(300)
    )
    node_rows = (
        ",,,,,,,,,END_001,source,5.0,25.0,1.0,0.0\n"
        ",,,,,,,,,END_002,sink,1.0,25.0,0.5,0.0\n"
    )
    name = _write(root, "long_chain.csv", _endpoint_table(pipes, node_rows))
    result = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is True, result.get("issues")
    (merged,) = result["merged_rows"]
    assert merged["flowpath"] == "FP_001"
    assert len(merged["rows"]) == 200
    assert merged["total"] == 300
    assert len(_json.dumps(result)) < 16 * 1024


def test_columns_given_names_the_fix() -> None:
    rows = [{**_pipe_row((0, 0, 0), (10, 0, 0)),
             "flowpath": "Line", "from_node": "A", "to_node": "B"}]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    by_field = {i.field: i for i in issues if i.code == "endpoints_columns_given"}
    assert sorted(by_field) == ["flowpath", "from_node", "to_node"]
    for field, issue in by_field.items():
        assert issue.params == {"column": field}
        assert field in issue.reason
        assert "column_map" in issue.reason


def test_import_description_pins_the_user_given_wording() -> None:
    guidance = tools.TOOLS["pipe_table_import"].description
    assert "ask only for the missing items listed" in guidance
    assert "never invent" in guidance
    assert "split_rows" in guidance


MAIN_TEMPLATE = ROOT / "docs" / "examples" / "pipe_table_template.csv"

CLOSED_CSV = (
    "flowpath,pipe,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m,"
    "node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction,mass_flow_kg_s\n"
    ",,,,,,,,SRC,source,5.0,25.0,1.0,0.0,\n"
    ",,,,,,,,SNK,sink,1.0,25.0,0.5,0.0,\n"
    ",,,,,,,,WELL,closed,,40.0,1.0,0.0,2.5\n"
    "FP1,P1,SRC,J1,10.0,0.0,0.05,5e-05,,,,,,\n"
    "FP2,P2,J1,SNK,10.0,0.0,0.05,5e-05,,,,,,\n"
    "FP3,P3,WELL,J1,10.0,0.0,0.05,5e-05,,,,,,\n"
)


def _node_rows(text: str) -> dict[str, dict[str, str]]:
    import csv as _csv

    rows: dict[str, dict[str, str]] = {}
    for record in _csv.DictReader(text.splitlines()):
        if record["node"] and not record["pipe"]:
            rows[record["node"]] = record
    return rows


def test_created_result_lists_template_boundaries_with_node_values(root: Path) -> None:
    text = MAIN_TEMPLATE.read_text(encoding="utf-8")
    name = _write(root, "template.csv", text)
    result = tools.dispatch("pipe_table_import", _base_args(name))
    assert result["created"] is True, result.get("issues")
    assert [(entry["node"], entry["kind"]) for entry in result["boundaries"]] == [
        ("SRC", "source"), ("OUT_A", "sink"), ("OUT_B", "sink"),
    ]
    assert [entry["name"] for entry in result["boundaries"]] == [
        "SRC_001", "SNK_001", "SNK_002",
    ]
    wanted = _node_rows(text)
    for entry in result["boundaries"]:
        row = wanted[entry["node"]]
        assert entry["pressure_bar"] == float(row["pressure_bar"])
        assert entry["temperature_c"] == float(row["temperature_c"])
        assert entry["gas_fraction"] == float(row["gas_fraction"])
        assert entry["water_fraction"] == float(row["water_fraction"])
        assert "mass_flow_kg_s" not in entry


def test_created_result_lists_closed_boundary_with_mass_flow(root: Path) -> None:
    name = _write(root, "closed.csv", CLOSED_CSV)
    result = tools.dispatch("pipe_table_import", _base_args(name))
    assert result["created"] is True, result.get("issues")
    by_name = {entry["name"]: entry for entry in result["boundaries"]}
    assert by_name["SRC_001"]["node"] == "SRC"
    assert by_name["SRC_001"]["pressure_bar"] == 5.0
    well = by_name["CLS_001"]
    assert well["node"] == "WELL"
    assert well["kind"] == "closed"
    assert "pressure_bar" not in well
    assert well["temperature_c"] == 40.0
    assert well["gas_fraction"] == 1.0
    assert well["water_fraction"] == 0.0
    assert well["mass_flow_kg_s"] == 2.5


def _leaf_table(junctions: int, leaves: int, tag: str = "") -> str:
    header = (
        "flowpath,pipe,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m,"
        "node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction,mass_flow_kg_s\n"
    )
    names = [f"{tag}SRC"] + [
        f"{tag}SNK_{number:02d}" for number in range(1, junctions * leaves + 1)
    ]
    node_rows = f",,,,,,,,{tag}SRC,source,5.0,25.0,1.0,0.0,\n" + "".join(
        f",,,,,,,,{name},sink,1.0,25.0,0.5,0.0,\n" for name in names[1:]
    )
    pipes = f"TRUNK,TRUNK_P1,{tag}SRC,J1,10.0,0.0,0.05,5e-05,,,,,,\n"
    for junction in range(1, junctions + 1):
        if junction > 1:
            pipes += (
                f"J{junction - 1}J{junction},P_J{junction},J{junction - 1},J{junction},"
                "10.0,0.0,0.05,5e-05,,,,,,\n"
            )
        for leaf in range(1, leaves + 1):
            sink = f"{tag}SNK_{(junction - 1) * leaves + leaf:02d}"
            pipes += (
                f"L{junction}_{leaf},P{junction}_{leaf},J{junction},{sink},"
                "10.0,0.0,0.05,5e-05,,,,,,\n"
            )
    return header + node_rows + pipes


def test_created_result_caps_boundaries_with_a_total(root: Path) -> None:
    name = _write(root, "leaves.csv", _leaf_table(5, 5))
    result = tools.dispatch("pipe_table_import", _base_args(name))
    assert result["created"] is True, result.get("issues")
    assert len(result["boundaries"]) == 20
    assert result["boundaries_total"] == 26
    assert result["boundaries"][0]["name"] == "SRC_001"
    assert "6 more" in result["boundaries_note"]
    assert "do not ask" in result["boundaries_note"]


def test_created_result_with_a_20k_node_name_stays_bounded(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json as _json

    from olga_companion import case_draft_store

    long_name = "S" * 20000
    text = (
        "flowpath,pipe,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m,"
        "node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction,mass_flow_kg_s\n"
        f",,,,,,,,{long_name},source,5.0,25.0,1.0,0.0,\n"
        ",,,,,,,,SNK,sink,1.0,25.0,0.5,0.0,\n"
        f"FP1,P1,{long_name},J1,10.0,0.0,0.05,5e-05,,,,,,\n"
        "FP2,P2,J1,SNK,10.0,0.0,0.05,5e-05,,,,,,\n"
    )
    name = _write(root, "long_node.csv", text)
    created = []
    real_create = case_draft_store.create_draft

    def counting(*args, **kwargs):
        created.append(1)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(case_draft_store, "create_draft", counting)
    result = tools.dispatch("pipe_table_import", _base_args(name))
    assert result["created"] is True, result.get("issues")
    assert len(_json.dumps(result)) < 16 * 1024
    assert created == [1]
    assert result["boundaries"][0]["node"] == "S" * 48


def test_created_result_with_long_boundary_names_stays_bounded(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json as _json

    from olga_companion import case_draft_store

    name = _write(root, "long_names.csv", _leaf_table(5, 5, tag="N" * 2000))
    created = []
    real_create = case_draft_store.create_draft

    def counting(*args, **kwargs):
        created.append(1)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(case_draft_store, "create_draft", counting)
    result = tools.dispatch("pipe_table_import", _base_args(name))
    assert result["created"] is True, result.get("issues")
    assert len(_json.dumps(result)) < 16 * 1024
    assert created == [1]
    assert all(len(entry["node"]) <= 48 for entry in result["boundaries"])


def _just_under_cap_table() -> str:
    y, z = 2000000.123456789, 4000000.123456789
    header = (
        "pipe,x_start_m,y_start_m,z_start_m,x_m,y_m,z_m,"
        "inner_diameter_m,roughness_m,node,node_kind,pressure_bar,"
        "temperature_c,gas_fraction,water_fraction\n"
    )
    lines = [header]
    lines.append(",,,,,,,,,END_001,source,5.01325,25.123456789,1.0,0.0")
    for number in range(2, 101):
        lines.append(
            f",,,,,,,,,END_{number:03d},sink,1.01325,25.123456789,0.5,0.0")
    prev = 7000000.123456789
    for junction in range(1, 50):
        xx = 7000000.123456789 + 10.0 * junction
        lines.append(
            f"T{junction},{prev!r},{y!r},{z!r},{xx!r},{y!r},{z!r},"
            "0.05,0.00005,,,,,,")
        for leaf in (1, 2):
            y1, z1 = y + leaf, z + leaf if leaf == 1 else z - leaf
            lines.append(
                f"L{junction}_{leaf}a,{xx!r},{y!r},{z!r},{xx!r},{y1!r},{z1!r},"
                "0.05,0.00005,,,,,,")
            lines.append(
                f"L{junction}_{leaf}b,{xx!r},{y1!r},{z1!r},{xx!r},{y1 + 5!r},{z1!r},"
                "0.05,0.00005,,,,,,")
        prev = xx
    lines.append(
        f"TAIL,{prev!r},{y!r},{z!r},{prev + 10!r},{y!r},{z!r},"
        "0.05,0.00005,,,,,,")
    return "\n".join(lines) + "\n"


def test_created_response_with_note_stays_bounded_with_one_draft(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json as _json

    from olga_companion import case_draft_store

    name = _write(root, "near_cap.csv", _just_under_cap_table())
    created = []
    real_create = case_draft_store.create_draft

    def counting(*args, **kwargs):
        created.append(1)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(case_draft_store, "create_draft", counting)
    result = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is True, result.get("issues")
    assert created == [1]
    assert len(_json.dumps(result)) < 16 * 1024
    # Exactly one halving: the worst-case note in the probe tips the size
    # over the cap after merged rows are emptied; without it the probe fits
    # there and ends stay whole.
    assert len(result["ends"]) == 50
    assert all(entry["rows"] == [] for entry in result["merged_rows"])
    assert "80 more" in result["boundaries_note"]


def _korean_pipe_name(stem: str, number: int) -> str:
    """A 48-character pipe name; generated end/boundary labels stay ASCII."""
    return f"{stem * 46}{number:02d}"


def _just_under_cap_table_korean() -> str:
    y, z = 2000000.1234, 4000000.4567
    header = (
        "pipe,x_start_m,y_start_m,z_start_m,x_m,y_m,z_m,"
        "inner_diameter_m,roughness_m,node,node_kind,pressure_bar,"
        "temperature_c,gas_fraction,water_fraction\n"
    )
    lines = [header]
    lines.append(",,,,,,,,,END_001,source,5.01325123456,25.1234567890123,1.0,0.000000001")
    for number in range(2, 101):
        lines.append(
            f",,,,,,,,,END_{number:03d},sink,1.01325123456,25.1234567890123,0.50000001,0.000000001")
    prev = 7000000.123456789
    for junction in range(1, 50):
        xx = 7000000.123456789 + 10.0 * junction
        lines.append(
            f"{_korean_pipe_name(chr(0xAC00 + junction), junction)},{prev!r},{y!r},{z!r},{xx!r},{y!r},{z!r},"
            "0.05,0.00005,,,,,,")
        for leaf in (1, 2):
            y1, z1 = y + leaf, z + leaf if leaf == 1 else z - leaf
            stem = chr(0xB098 + junction)
            lines.append(
                f"{_korean_pipe_name(stem, leaf * 10 + junction % 10)},{xx!r},{y!r},{z!r},{xx!r},{y1!r},{z1!r},"
                "0.05,0.00005,,,,,,")
            lines.append(
                f"{_korean_pipe_name(chr(0xB2E4 + junction), leaf)},{xx!r},{y1!r},{z1!r},{xx!r},{y1 + 5!r},{z1!r},"
                "0.05,0.00005,,,,,,")
        prev = xx
    lines.append(
        f"{'라' * 48},{prev!r},{y!r},{z!r},{prev + 10!r},{y!r},{z!r},"
        "0.05,0.00005,,,,,,")
    return "\n".join(lines) + "\n"


def test_created_response_with_korean_names_passes_the_real_cap(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json as _json

    from olga_companion import case_draft_store
    from olga_companion.agent import tools as _tools
    from olga_companion.agent.tool_validation import MAX_RESULT_BYTES

    name = _write(root, "\uac00" * 48 + ".csv", _just_under_cap_table_korean())
    created = []
    real_create = case_draft_store.create_draft

    def counting(*args, **kwargs):
        created.append(1)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(case_draft_store, "create_draft", counting)
    result = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is True, result.get("issues")
    assert created == [1]
    # The shared size measure counts the ASCII-escaped wire form, so the
    # pre-create shrink empties merged rows and all 100 ends survive instead
    # of the wire cap silently trimming the ends list to its first 50.
    assert len(result["ends"]) == 100
    assert len(result["boundaries"]) == 20
    assert "80 more" in result["boundaries_note"]
    assert "_truncated" not in result
    assert len(_json.dumps(result, default=str)) <= MAX_RESULT_BYTES
    capped = _tools._cap(result)
    assert capped == result
    assert len(str(capped["draft_id"])) == 32


def test_capped_boundaries_keep_every_kind(root: Path) -> None:
    text = _leaf_table(5, 5) + (
        ",,,,,,,,WELL,closed,,40.0,1.0,0.0,2.5\n"
        ",,,,,,,,SNK_26,sink,1.0,25.0,0.5,0.0,\n"
        "FP_X,P_X,J5,J6,10.0,0.0,0.05,5e-05,,,,,,\n"
        "FP_C,P_C,WELL,J6,10.0,0.0,0.05,5e-05,,,,,,\n"
        "FP_L26,P_L26,J6,SNK_26,10.0,0.0,0.05,5e-05,,,,,,\n"
    )
    name = _write(root, "kinds.csv", text)
    result = tools.dispatch("pipe_table_import", _base_args(name))
    assert result["created"] is True, result.get("issues")
    assert result["boundaries_total"] == 28
    assert [entry["name"] for entry in result["boundaries"][:3]] == [
        "SRC_001", "SNK_001", "CLS_001",
    ]
    assert {entry["kind"] for entry in result["boundaries"]} == {"source", "sink", "closed"}


def test_shrink_drops_boundaries_last() -> None:
    import json as _json

    from olga_companion.agent.pipe_table_tools import _shrink_to_totals
    from olga_companion.agent.tool_validation import MAX_RESULT_BYTES

    ends = [{"name": f"END_{number:03d}", "x_m": 1.0, "y_m": 2.0, "z_m": 3.0}
            for number in range(1, 5)]
    merged = [{"flowpath": f"FP_{number:03d}", "rows": list(range(1, 51)), "total": 50}
              for number in range(1, 51)]
    reason = ("the table needs a node row for every END before the case builds; " * 4)[:200]
    probe = {
        "created": True,
        "issues": [
            {"row": number, "field": "f" * 64, "code": "flowpath_nodes_disagree",
             "params": {"flowpath": "F" * 48}, "reason": reason}
            for number in range(2, 22)
        ],
        "ends": ends,
        "ends_total": 4,
        "merged_rows": merged,
        "merged_rows_total": 50,
        # Small entries, but enough of them that only dropping them last fits.
        "boundaries": [
            {"name": f"SRC_{number:03d}", "node": f"S{number}", "kind": "source",
             "pressure_bar": 5.0, "temperature_c": 25.0,
             "gas_fraction": 1.0, "water_fraction": 0.0}
            for number in range(1, 46)
        ],
    }
    assert len(_json.dumps(probe)) > MAX_RESULT_BYTES
    before_issues = [dict(issue) for issue in probe["issues"]]
    _shrink_to_totals(probe)
    assert len(_json.dumps(probe)) <= MAX_RESULT_BYTES
    assert all(entry["rows"] == [] for entry in probe["merged_rows"])
    assert probe["ends"] == []
    assert probe["boundaries"] == []
    assert probe["issues"] == before_issues


def test_shrink_keeps_small_boundaries_while_slicing_ends() -> None:
    import json as _json

    from olga_companion.agent.pipe_table_tools import _shrink_to_totals
    from olga_companion.agent.tool_validation import MAX_RESULT_BYTES

    rows = []
    for chain in range(50):
        for i in range(100):
            x = 100000.0 * chain + 10.0 * i
            rows.append(_pipe_row((x, 0, 0), (x + 10, 0, 0)))
    _out, _issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    reason = ("the table needs a node row for every END before the case builds; " * 4)[:200]
    probe = {
        "created": False,
        "issue_count": 20,
        "issues": [
            {"row": number, "field": "f" * 64, "code": "flowpath_nodes_disagree",
             "params": {"flowpath": "F" * 48}, "reason": reason}
            for number in range(2, 22)
        ],
        "note": "No draft was made. The table needs these fixes first.",
        "ends": [dict(entry) for entry in summary["ends"]],
        "ends_total": 100,
        "merged_rows": [
            {"flowpath": entry["flowpath"], "rows": list(entry["rows"]),
             "total": entry["total"]}
            for entry in summary["merged_rows"]
        ],
        "merged_rows_total": 50,
        "boundaries": [
            {"name": "SRC_001", "node": "SRC", "kind": "source",
             "pressure_bar": 5.0, "temperature_c": 25.0,
             "gas_fraction": 1.0, "water_fraction": 0.0},
        ],
    }
    assert len(_json.dumps(probe)) > MAX_RESULT_BYTES
    _shrink_to_totals(probe)
    assert len(_json.dumps(probe)) <= MAX_RESULT_BYTES
    assert 1 <= len(probe["ends"]) < 100
    assert probe["boundaries"] != []


def _pipe_row(start, end, **extra):
    row = {
        "pipe": "P",
        "x_start_m": float(start[0]), "y_start_m": float(start[1]), "z_start_m": float(start[2]),
        "x_m": float(end[0]), "y_m": float(end[1]), "z_m": float(end[2]),
        "inner_diameter_m": 0.05, "roughness_m": 5e-05,
    }
    row.update(extra)
    return row


def test_tool_caps_ends_and_merged_rows(root: Path) -> None:
    import json as _json

    singles = "".join(
        f"P{i},{10.0 * i},0,0,{10.0 * i + 5},0,0,0.05,0.00005,,,,,,\n" for i in range(150)
    )
    name = _write(root, "many_ends.csv", _endpoint_table(singles))
    result = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is False
    assert len(result["ends"]) == 100
    assert result["ends_total"] == 300
    assert result["merged_rows"] == []
    assert result["merged_rows_total"] == 0
    assert len(_json.dumps(result)) < 16 * 1024

    chains = "".join(
        f"C{i}a,{10000.0 + 30.0 * i},0,0,{10000.0 + 30.0 * i + 10},0,0,0.05,0.00005,,,,,,\n"
        f"C{i}b,{10000.0 + 30.0 * i + 10},0,0,{10000.0 + 30.0 * i + 20},0,0,0.05,0.00005,,,,,,\n"
        for i in range(60)
    )
    name = _write(root, "many_merged.csv", _endpoint_table(chains))
    result = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y", roughness_m=5e-05,
    ))
    assert result["created"] is False
    assert len(result["merged_rows"]) == 50
    assert result["merged_rows_total"] == 60
    assert all(entry["total"] == 2 for entry in result["merged_rows"])
    assert len(_json.dumps(result)) < 16 * 1024


def test_tool_sheets_ends_keep_the_sheet_frame(root: Path) -> None:
    text = _endpoint_table("P1,1,2,3,4,6,9,0.05,0.00005,,,,,,\n")
    name = _write(root, "asymmetric.csv", text)
    result = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="z", roughness_m=5e-05,
    ))
    assert result["created"] is False
    coords = {entry["name"]: entry for entry in result["ends"]}
    assert (coords["END_001"]["x_m"], coords["END_001"]["y_m"], coords["END_001"]["z_m"]) == (1.0, 2.0, 3.0)
    assert (coords["END_002"]["x_m"], coords["END_002"]["y_m"], coords["END_002"]["z_m"]) == (4.0, 6.0, 9.0)


def test_tool_without_either_roughness_source_names_the_row(root: Path) -> None:
    text = (
        "pipe,x_start_m,y_start_m,z_start_m,x_m,y_m,z_m,inner_diameter_m\n"
        "P1,0,0,0,10,0,0,0.05\n"
    )
    name = _write(root, "no_rough.csv", text)
    result = tools.dispatch("pipe_table_import", _base_args(
        name, layout="endpoints", vertical_axis="y",
    ))
    assert result["created"] is False
    assert any(issue["field"] == "roughness_m" and issue["code"] == "value_missing"
               for issue in result["issues"])


def test_docs_endpoints_template_needs_boundaries_then_builds() -> None:
    assert TEMPLATE.is_file(), f"missing docs template {TEMPLATE}"
    table = read_table(TEMPLATE)
    assert table.issues == (), table.issues
    out, issues, summary = rows_from_endpoints(
        list(table.rows), vertical_axis="z", lines=list(table.lines),
    )
    assert issues == (), [(i.row, i.field, i.reason) for i in issues]
    stock = PipeTable(
        rows=tuple(out), issues=(), header_row=1, ignored_columns=(),
        lines=tuple(summary["row_lines"]),
    )
    result = build_case_spec(stock, OPTIONS)
    assert result.spec is None and result.issues
    assert {issue.code for issue in result.issues} <= {
        "missing_boundary_row", "missing_inlet_sink"}
    assert any(issue.code == "missing_boundary_row" for issue in result.issues)
    ends = {entry["name"] for entry in summary["ends"]}
    assert len(ends) == 3
    node_rows = [
        {"node": name, "node_kind": "source" if code == 0 else "sink",
         "pressure_pa": 500000.0 if code == 0 else 100000.0,
         "temperature_c": 25.0, "gas_fraction": 1.0 if code == 0 else 0.5,
         "water_fraction": 0.0}
        for code, name in enumerate(sorted(ends))
    ]
    stocked = PipeTable(
        rows=tuple(out) + tuple(node_rows), issues=(), header_row=1, ignored_columns=(),
        lines=tuple(list(summary["row_lines"]) + [0] * len(node_rows)),
    )
    built = build_case_spec(stocked, OPTIONS)
    assert built.issues == (), [(i.row, i.field, i.reason) for i in built.issues]
    assert built.spec is not None


def test_endpoint_synonyms_read_as_start_and_end(tmp_path: Path) -> None:
    path = tmp_path / "syn.csv"
    path.write_text(
        "Pipe,Start X (m),Start Y (m),Start Z (m),End X (m),End Y (m),End Z (m),"
        "Inner Diameter (mm),Roughness (mm)\n"
        "P1,0,0,0,10,0,0,50,0.05\n",
        encoding="utf-8",
    )
    table = read_table(path)
    assert table.issues == (), table.issues
    (row,) = table.rows
    assert row["x_start_m"] == 0.0 and row["x_m"] == 10.0
    assert row["inner_diameter_m"] == pytest.approx(0.05)
    assert row["roughness_m"] == pytest.approx(5e-05)


def test_bare_x1_is_not_a_start_coordinate(tmp_path: Path) -> None:
    path = tmp_path / "bare.csv"
    path.write_text(
        "Pipe,X1,Y1,Z1,X2,Y2,Z2,Length (m),Elevation (m),"
        "Inner Diameter (mm),Roughness (mm)\n"
        "P1,0,0,0,10,0,0,10,0,50,0.05\n",
        encoding="utf-8",
    )
    table = read_table(path)
    assert table.issues == (), table.issues
    (row,) = table.rows
    assert "x_start_m" not in row and "x_m" not in row
    out, issues, _summary = rows_from_endpoints([row], vertical_axis="y")
    assert out == []
    assert [(issue.row, issue.field) for issue in issues] == [(1, "x_start_m")]


def test_start_x_in_a_length_table_is_a_mixed_table(tmp_path: Path) -> None:
    path = tmp_path / "mixed.csv"
    path.write_text(
        "Flowpath,Pipe,From,To,Start X (m),Start Y (m),Start Z (m),"
        "X (m),Y (m),Z (m),Length (m),Inner Diameter (mm),Roughness (mm)\n"
        "FP,P1,A,B,0,0,0,10,0,0,10,50,0.05\n",
        encoding="utf-8",
    )
    table = read_table(path)
    assert table.issues == (), table.issues
    assert table.rows[0]["x_start_m"] == 0.0
    result = build_case_spec(table, OPTIONS)
    assert result.spec is None
    assert {issue.code for issue in result.issues} == {"mixed_coord_length"}


def test_tool_issue_payload_keeps_code_params_and_reason() -> None:
    rows = [
        {"pipe": "P1", "x_start_m": 0.0, "y_start_m": 0.0, "z_start_m": 0.0,
         "x_m": 10.0, "y_m": 0.0, "z_m": 0.0,
         "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"pipe": "P2", "x_start_m": 0.0, "y_start_m": 0.0, "z_start_m": 0.0,
         "x_m": 10.0, "y_m": 0.0, "z_m": 0.0,
         "inner_diameter_m": 0.05, "roughness_m": 5e-05},
    ]
    _out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues and all(issue.code for issue in issues)
    from olga_companion.pipe_table_import import ImportResult

    payload = _tool_issues(ImportResult(spec=None, issues=tuple(issues)))
    assert payload
    for item, issue in zip(payload, issues):
        assert item["code"] == issue.code
        assert item["params"] == issue.params
        assert item["reason"] == issue.reason


def test_endpoints_layout_on_an_ordinary_table_names_the_table_kind(root: Path) -> None:
    # A model that guesses layout="endpoints" for an ordinary table must be told the
    # table's kind, not asked for a vertical axis the user cannot sensibly answer.
    name = _write(root, "ordinary.csv", (
        "flowpath,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m\n"
        "FP_A,IN,OUT,10,0,0.05,0.00005\n"
    ))
    with pytest.raises(tools.ToolError) as caught:
        tools.dispatch("pipe_table_import", _base_args(name, layout="endpoints"))
    message = str(caught.value)
    assert "vertical_axis" not in message
    assert "without layout" in message
    assert "flowpath" in message
