"""Re-edit reuses a recovered CaseSpec and changes only the fields the user named."""

from __future__ import annotations

import json
from pathlib import Path

from olga_companion import case_compiler, workspace
from olga_companion.agent import tools
from olga_companion.agent.runtime import SYSTEM_PROMPT
from olga_companion.case_transactions import case_spec_hash, plan_case_edits, plan_case_edits_from_source

FIXTURE = Path(__file__).parent / "fixtures" / "casespec_source_massflow.json"
OWNER = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"


def _spec() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _massflow_required() -> list[str]:
    operation = tools.TOOLS["case_edit_plan"].parameters["properties"]["operations"]["items"]
    for branch in operation["allOf"]:
        if branch["if"]["properties"]["op"]["const"] == "set_source_massflow":
            return list(branch["then"]["required"])
    raise AssertionError("set_source_massflow schema branch is missing")


def test_massflow_edit_requires_only_the_named_flow() -> None:
    required = _massflow_required()

    assert "label" in required
    assert "mass_flow_kg_s" in required
    assert "temperature_c" not in required
    assert "gas_fraction" not in required
    assert "total_water_fraction" not in required


def test_massflow_only_keeps_recovered_temperature_and_fractions(tmp_path: Path) -> None:
    raw = _spec()
    (tmp_path / "fluid.tab").write_text('PVTTABLE LABEL="TEST_FLUID"\n', encoding="utf-8")

    updated = plan_case_edits(
        raw,
        [{"op": "set_source_massflow", "label": "FEED", "mass_flow_kg_s": 2.5}],
        expected_hash=case_spec_hash(raw),
        workspace_root=tmp_path,
    )

    assert updated.publishable is True, getattr(updated, "errors", updated)
    text = updated.compiled_bytes.decode()
    assert "MASSFLOW=(2.5) kg/s" in text
    assert "TEMPERATURE=(40) C" in text
    assert "GASFRACTION=(0.25)" in text
    assert "TOTALWATERFRACTION=(0)" in text
    assert not (tmp_path / "published.genkey").exists()


def test_massflow_only_keeps_a_series_shape(tmp_path: Path) -> None:
    raw = _spec()
    raw["massflow_sources"][0]["series"] = [
        {
            "time_s": 0,
            "mass_flow_kg_s": 1,
            "temperature_c": 40,
            "gas_fraction": 0.25,
            "total_water_fraction": 0.0,
        },
        {
            "time_s": 5,
            "mass_flow_kg_s": 2,
            "temperature_c": 15,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
        },
    ]
    source = tmp_path / "series.genkey"
    source.write_bytes(case_compiler.render_case_spec(raw))
    (tmp_path / "fluid.tab").write_text('PVTTABLE LABEL="TEST_FLUID"\n', encoding="utf-8")

    updated = plan_case_edits_from_source(
        source,
        [{"op": "set_source_massflow", "label": "FEED", "mass_flow_kg_s": 3.0}],
        expected_hash=__import__("hashlib").sha256(source.read_bytes()).hexdigest(),
        workspace_root=tmp_path,
    )

    assert updated.publishable is True, getattr(updated, "errors", updated)
    text = updated.compiled_bytes.decode()
    assert "TIME=(0, 5) s" in text
    assert "MASSFLOW=(3, 3) kg/s" in text
    assert "TEMPERATURE=(40, 15) C" in text
    assert "GASFRACTION=(0.25, 0.1)" in text
    assert "TOTALWATERFRACTION=(0, 0.4)" in text


def test_review_returns_the_recovered_case_spec(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    case = root / "current.genkey"
    case.write_bytes(case_compiler.render_case_spec(_spec()))
    (root / "fluid.tab").write_text('PVTTABLE LABEL="TEST_FLUID"\n', encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    workspace.set_active_path(str(case))

    review = tools.dispatch("genkey_review", {})

    feed = review["case_spec"]["massflow_sources"][0]
    assert review["source_sha256"]
    assert feed["mass_flow_kg_s"] == 1.0
    assert feed["temperature_c"] == 40.0
    assert feed["gas_fraction"] == 0.25
    assert feed["total_water_fraction"] == 0.0
    assert "case_spec" in tools.TOOLS["genkey_review"].description


def test_owner_review_does_not_invent_a_case_spec(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    case = root / "owner.genkey"
    case.write_bytes(OWNER.read_bytes())
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))

    review = tools.dispatch("genkey_review", {"path": str(case)})

    assert review["source_sha256"]
    assert review["case_spec"] is None
    assert "gas_fraction" not in json.dumps(review["summary"])


def test_prompt_reuses_recovered_values_on_a_re_edit() -> None:
    prompt = SYSTEM_PROMPT

    assert "genkey_review" in prompt
    assert "case_spec" in prompt
    assert "do not ask again" in prompt.lower()
    assert "mass_flow_kg_s" in prompt
