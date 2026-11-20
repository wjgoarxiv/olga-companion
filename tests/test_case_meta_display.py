"""The table's own names (CaseMeta) reach the screen and the assistant.

The compiler writes `! META` comment lines into the .genkey; the topology response, the
result inventory and the result tool outputs read them back. A file without those lines
(an older case) simply has no such field. OLGA labels, the genkey body and the golden
bytes never change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olga_companion import result_inventory
from olga_companion.agent import result_tools, tool_read_tools
from olga_companion.agent.tool_artifact_schemas import TOOL_RESPONSE_SCHEMAS
from olga_companion.agent.tool_validation import PathBindings, validate_tool_result
from olga_companion.case_compiler import render_case_spec
from olga_companion.sidecar import app

_FIXTURES = Path(__file__).parent / "fixtures"
_SIMPLE = _FIXTURES / "cases" / "simple_pipeline.genkey"


def _spec(with_meta: bool) -> dict[str, Any]:
    spec = json.loads((_FIXTURES / "casespec_outputs.json").read_text(encoding="utf-8"))
    if with_meta:
        flowpath, node = spec["flowpaths"][0]["label"], spec["nodes"][0]["label"]
        spec["meta"] = {"title": "집유 배관망", "display_names": {flowpath: "1번 유정 라인", node: "분리기"}}
    return spec


def _write_case(directory: Path, name: str, with_meta: bool) -> Path:
    path = directory / name
    path.write_bytes(render_case_spec(_spec(with_meta)))
    return path


def _paths(source: Path) -> PathBindings:
    return PathBindings(
        input_file=lambda value, _suffixes: value,
        result_file=lambda _value: str(source),
        set_active_case=lambda _value: None,
    )


def test_topology_response_carries_the_title_and_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_case(tmp_path, "named.genkey", True)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    body = TestClient(app).post("/api/genkey/topology", json={"rel": "named.genkey"}).json()
    assert body["meta"]["title"] == "집유 배관망"
    assert sorted(body["meta"]["display_names"].values()) == ["1번 유정 라인", "분리기"]
    labels = {node["id"] for node in body["nodes"]} | {edge["label"] for edge in body["edges"]}
    assert set(body["meta"]["display_names"]) <= labels, "names are keyed by the OLGA labels, which stay as they are"


def test_a_case_without_meta_has_no_meta_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_case(tmp_path, "plain.genkey", False)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    plain = TestClient(app).post("/api/genkey/topology", json={"rel": "plain.genkey"})
    assert plain.status_code == 200
    assert "meta" not in plain.json()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(_SIMPLE.parent))
    old = TestClient(app).post("/api/genkey/topology", json={"rel": _SIMPLE.name})
    assert old.status_code == 200
    assert "meta" not in old.json()


def test_the_golden_bytes_do_not_depend_on_this_work() -> None:
    golden = (_FIXTURES / "casespec_outputs.golden.genkey").read_bytes()
    assert render_case_spec(_spec(False)) == golden


def test_a_broken_meta_line_is_ignored_not_fatal(tmp_path: Path) -> None:
    path = tmp_path / "odd.genkey"
    path.write_text("ENDCASE\n! META TITLE not-json\n! META WHAT x\n", encoding="utf-8")
    assert result_inventory.case_meta_for_case(path) == {}


def test_run_results_carry_the_case_meta_of_the_staged_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named, plain = tmp_path / "run-a", tmp_path / "run-b"
    named.mkdir()
    plain.mkdir()
    _write_case(named, "net.genkey", True)
    _write_case(plain, "net.genkey", False)
    for run in (named, plain):
        (run / "net.tpl").write_bytes(b"a result file with bytes")
    monkeypatch.setattr(
        result_inventory,
        "load_run_record",
        lambda _dir: {
            "schema_version": 1, "state": "completed", "ok": True,
            "source": {"name": "net.genkey", "sha256": "a" * 64},
            "runtime": {"candidate_id": "r", "version": "2022.1"},
            "selection_id": "s", "outputs": [],
        },
    )
    items = {Path(item["rel"]).parts[0]: item for item in result_inventory.scan_run_results(tmp_path, list_cap=20, walk_cap=40)}
    assert items["run-a"]["case_meta"]["title"] == "집유 배관망"
    assert "case_meta" not in items["run-b"]


def _fake_series(**_view: Any) -> dict[str, Any]:
    return {"unit": "Pa", "time_unit": "s", "time": [0.0, 1.0], "values": [1.0, 2.0], "analysis": {}}


def test_result_tool_outputs_name_the_tables_beside_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _write_case(tmp_path, "net.genkey", True)
    source = tmp_path / "net.tpl"
    source.write_bytes(b"stable result source")
    monkeypatch.setattr(
        result_tools.results, "variable_series",
        lambda _path, _variable, _position=None, **view: _fake_series(**view),
    )
    result = tool_read_tools.results_series({"result_id": "workspace:net.tpl", "variable": "PT"}, _paths(source))
    assert result["case_title"] == "집유 배관망"
    assert sorted(result["display_names"].values()) == ["1번 유정 라인", "분리기"]
    assert case.name not in str(result.get("display_names"))

    lonely = tmp_path / "other" / "x.tpl"
    lonely.parent.mkdir()
    lonely.write_bytes(b"stable result source")
    plain = tool_read_tools.results_series({"result_id": "workspace:other/x.tpl", "variable": "PT"}, _paths(lonely))
    assert "display_names" not in plain and "case_title" not in plain


def test_named_result_outputs_pass_the_tool_response_schemas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # F3 hr01: results_series failed in the app with "unknown additional field 'case_title'".
    _write_case(tmp_path, "net.genkey", True)
    source = tmp_path / "net.tpl"
    source.write_bytes(b"stable result source")
    monkeypatch.setattr(
        result_tools.results, "variable_series",
        lambda _path, _variable, _position=None, **view: _fake_series(**view),
    )
    series = tool_read_tools.results_series({"result_id": "workspace:net.tpl", "variable": "PT"}, _paths(source))
    assert "case_title" in series and "display_names" in series
    validate_tool_result("results_series", series, TOOL_RESPONSE_SCHEMAS["results_series"])

    inventory = {
        "results": [{
            "result_id": "workspace:net.tpl", "name": "net.tpl", "kind": "tpl", "source_sha256": "a" * 64,
            "lineage": {"source_kind": "workspace", "source_id": "workspace:net.tpl"}, "case_title": "집유 배관망",
        }],
        "total_results": 1, "returned_results": 1, "offset": 0, "limit": 20, "truncated": False,
        "workspace_generation": 1,
    }
    validate_tool_result("results_inventory", inventory, TOOL_RESPONSE_SCHEMAS["results_inventory"])


def test_the_name_map_is_bounded(tmp_path: Path) -> None:
    names = {f"L_{index:04d}": f"이름 {index}" for index in range(200)}
    shown = result_tools.bounded_display_names(names)
    assert len(shown["display_names"]) == result_tools.MAX_DISPLAY_NAMES
    assert shown["display_names_truncated"] is True
