"""An optional CaseSpec `meta` carries the case title and the table's own names.

Live PVT 2026-11-16 (hr01): every compiled case said TITLE="CaseSpec v3", and a table
name that cannot be an OLGA label (Korean, for one) became FP_001 in the case, the
results and the assistant's answers. `meta` keeps the title and those names; the .genkey
stays ASCII (JSON escapes in `! META` comment lines) and recovers byte for byte. A spec
without `meta` compiles exactly as before.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from olga_companion.case_compiler import render_case_spec
from olga_companion.case_spec import normalize_case_spec
from olga_companion.case_spec_recovery import recover_case_spec

_FIXTURES = Path(__file__).parent / "fixtures"


def _base() -> dict:
    return json.loads((_FIXTURES / "casespec_outputs.json").read_text(encoding="utf-8"))


def _labels(spec: dict) -> list[str]:
    return [flowpath["label"] for flowpath in spec["flowpaths"]] + [node["label"] for node in spec["nodes"]]


def _round_trip(tmp_path: Path, spec: dict) -> tuple[bytes, dict]:
    content = render_case_spec(spec)
    path = tmp_path / "case.genkey"
    path.write_bytes(content)
    return content, recover_case_spec(path).model_dump(mode="json", by_alias=True, exclude_none=True)


def test_no_meta_compiles_to_the_same_golden_bytes() -> None:
    golden = (_FIXTURES / "casespec_outputs.golden.genkey").read_bytes()
    assert render_case_spec(_base()) == golden


def test_an_ascii_title_reaches_the_case_line_and_round_trips(tmp_path: Path) -> None:
    spec = _base()
    spec["meta"] = {"title": "hr01 gathering network"}
    content, recovered = _round_trip(tmp_path, spec)
    assert b'TITLE="hr01 gathering network"' in content
    assert recovered["meta"] == {"title": "hr01 gathering network"}


def test_korean_names_stay_out_of_the_genkey_bytes_and_come_back(tmp_path: Path) -> None:
    spec = _base()
    flowpath, node = spec["flowpaths"][0]["label"], spec["nodes"][0]["label"]
    spec["meta"] = {"title": "집유 배관망", "display_names": {flowpath: "1번 유정 라인", node: "분리기"}}
    content, recovered = _round_trip(tmp_path, spec)
    assert content.isascii()
    assert b'TITLE="CaseSpec v3"' in content or b'TITLE="CaseSpec v2"' in content
    assert recovered["meta"] == spec["meta"]


def test_a_korean_table_keeps_its_names_and_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from olga_companion import case_draft_store
    from olga_companion.agent import tools

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "집유망.csv").write_text(
        "라인,시작점,끝점,길이 (m),고도차 (m),내경 (mm),조도 (mm)\n1번 라인,유정A,분리기,500,0,150,0.045\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setenv("OLGA_CASE_DRAFT_DIR", str(tmp_path / "drafts"))
    result = tools.dispatch("pipe_table_import", {
        "path": "집유망.csv", "pvt_reference": "fluid.tab", "fluid_label": "FLUID-A",
        "thermal": {"model": "adiabatic"}, "end_time_s": 600,
        "boundaries": [
            {"node": "유정A", "kind": "source", "pressure_pa": 1.2e6, "temperature_c": 40, "gas_fraction": 1, "water_fraction": 0.5},
            {"node": "분리기", "kind": "sink", "pressure_pa": 8e5, "temperature_c": 30, "gas_fraction": 1, "water_fraction": 0.5},
        ],
    })
    assert result["created"] is True, result
    spec = case_draft_store.get_draft(result["draft_id"], context_generation=0).spec
    assert spec["meta"]["title"] == "집유망"
    assert sorted(spec["meta"]["display_names"].values()) == ["1번 라인", "분리기", "유정A"]
    assert render_case_spec(spec).isascii()


@pytest.mark.parametrize("meta", [
    {"title": 'say "hi"'},
    {"title": "two\nlines"},
    {"title": ""},
    {"display_names": {"NOT_A_LABEL_HERE": "x"}},
    {"display_names": {"lower": "x"}},
    {"unknown": 1},
])
def test_bad_meta_is_refused(meta: dict) -> None:
    spec = _base()
    if "display_names" in meta and "NOT_A_LABEL_HERE" in meta["display_names"]:
        assert "NOT_A_LABEL_HERE" not in _labels(spec)
    spec["meta"] = meta
    with pytest.raises((ValidationError, ValueError)):
        normalize_case_spec(spec)
