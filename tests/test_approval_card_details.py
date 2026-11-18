"""Approval cards show what will be written or run, for every approval kind."""

from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import fluid_table, sweep_selection
from olga_companion.agent import approval_display
from olga_companion.agent.runtime import SYSTEM_PROMPT
from olga_companion.agent.tool_validation import ToolError


class Paths:
    def input_file(self, value, suffixes):
        return str(Path(value))


def _by_key(display, key):
    return [row for row in display["fields"] if row["key"] == key]


@pytest.fixture
def fluids_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(
        fluid_table,
        "databank_names",
        lambda *args, **kwargs: {"METHANE": "METHANE", "ETHANE": "ETHANE", "WATER": "WATER"},
    )
    return tmp_path


FLUID_ARGS = {
    "fluid_label": "SYN1",
    "components": [
        {"name": "methane", "mole_fraction": 0.85},
        {"name": "ETHANE", "mole_fraction": 0.15},
    ],
    "model": "SRK",
    "temperatures": [-10.0, 50.0, 120.0],
    "temperature_unit": "degC",
    "pressures": [1, 5, 25, 100],
    "pressure_unit": "bar",
    "mfl_rel": "fluids/synthetic.mfl",
}


def test_fluids_draft_display_lists_every_value_the_file_will_hold(fluids_workspace):
    display = approval_display.build("fluids_draft_mfl", dict(FLUID_ARGS), Paths())

    assert _by_key(display, "file")[0]["value"] == "fluids/synthetic.mfl"
    assert _by_key(display, "table_file")[0]["value"] == "fluids/synthetic.tab"
    assert _by_key(display, "label")[0]["value"] == "SYN1"
    assert _by_key(display, "model")[0]["value"] == "SRK"
    components = {row["value"] for row in _by_key(display, "component")}
    assert components == {"METHANE 0.85", "ETHANE 0.15"}, "names come from the databank, not the model text"
    assert _by_key(display, "temperature_range")[0] == {
        "key": "temperature_range",
        "value": "-10 – 120",
        "unit": "degC",
    }
    assert _by_key(display, "pressure_range")[0] == {
        "key": "pressure_range",
        "value": "1 – 100",
        "unit": "bar",
    }
    assert _by_key(display, "temperature_points")[0]["value"] == "3"
    assert _by_key(display, "pressure_points")[0]["value"] == "4"


def test_fluids_draft_display_marks_the_water_option_only_when_set(fluids_workspace):
    plain = approval_display.build("fluids_draft_mfl", dict(FLUID_ARGS), Paths())
    assert _by_key(plain, "water_option") == []
    with_water = approval_display.build("fluids_draft_mfl", {**FLUID_ARGS, "hawater": True}, Paths())
    assert _by_key(with_water, "water_option")[0]["value"] == "HAWATER"


def test_fluids_draft_display_refuses_an_invalid_draft_instead_of_inventing_text(fluids_workspace):
    with pytest.raises(ToolError):
        approval_display.build("fluids_draft_mfl", {**FLUID_ARGS, "model": "NOT_A_MODEL"}, Paths())


def test_multiflash_open_display_names_the_file(fluids_workspace):
    display = approval_display.build(
        "multiflash_open", {"mfl_path": str(fluids_workspace / "fluids" / "synthetic.mfl")}, Paths()
    )
    assert _by_key(display, "program")[0]["value"] == "Multiflash"
    assert _by_key(display, "file")[0]["value"] == "synthetic.mfl"


def test_multiflash_open_without_a_file_still_says_what_opens(fluids_workspace):
    display = approval_display.build("multiflash_open", {}, Paths())
    assert _by_key(display, "program")[0]["value"] == "Multiflash"
    assert _by_key(display, "file") == []


def test_genkey_save_display_shows_its_main_fields(fluids_workspace):
    display = approval_display.build(
        "genkey_save",
        {"save_rel": "cases/new.genkey", "topology": "single_pipe", "endtime_s": 7200, "pvtfile": "./fluid.tab"},
        Paths(),
    )
    assert _by_key(display, "file")[0]["value"] == "cases/new.genkey"
    assert _by_key(display, "topology")[0]["value"] == "single_pipe"
    assert _by_key(display, "end_time")[0] == {"key": "end_time", "value": "7200", "unit": "s"}
    assert _by_key(display, "pvt_file")[0]["value"] == "./fluid.tab"


def test_cancel_displays_show_the_id_being_cancelled(fluids_workspace):
    run = approval_display.build("run_cancel", {"run_id": "run_abc123"}, Paths())
    assert _by_key(run, "run_id")[0]["value"] == "run_abc123"
    sweep = approval_display.build("sweep_cancel", {"sweep_id": "sweep_abc123"}, Paths())
    assert _by_key(sweep, "sweep_id")[0]["value"] == "sweep_abc123"


def _stub_sweep(tmp_path, monkeypatch, plan_id="plan_exact"):
    case = sweep_selection.SweepCaseState(
        index=0,
        path=tmp_path / "base_p1.genkey",
        valid=True,
        validation_errors=[],
        params=[],
        source_sha256="0" * 64,
        companions=[],
    )
    state = sweep_selection.SweepState(
        sweep_id="sweep_stub",
        base=tmp_path / "base.genkey",
        strategy="oat",
        sweeps=["PIPE_1.diameter=0.1,0.2"],
        timeout_s=900,
        cases=[case, case],
        output_dir=str(tmp_path / "out"),
        command={},
        detection={},
        plan_id=plan_id,
        context_generation=1,
        created_monotonic=0.0,
    )
    monkeypatch.setitem(sweep_selection.SWEEPS, "sweep_stub", state)


def test_sweep_execute_display_comes_from_the_previewed_plan(fluids_workspace, monkeypatch):
    _stub_sweep(fluids_workspace, monkeypatch)
    display = approval_display.build(
        "sweep_execute", {"sweep_id": "sweep_stub", "plan_id": "plan_exact"}, Paths()
    )
    assert _by_key(display, "sweep_id")[0]["value"] == "sweep_stub"
    assert _by_key(display, "case")[0]["value"] == "base.genkey"
    assert _by_key(display, "case_count")[0]["value"] == "2"
    assert _by_key(display, "timeout")[0] == {"key": "timeout", "value": "900", "unit": "s"}
    assert _by_key(display, "plan_id")[0]["value"] == "plan_exact"


def test_sweep_execute_display_refuses_a_changed_plan(fluids_workspace, monkeypatch):
    _stub_sweep(fluids_workspace, monkeypatch)
    with pytest.raises(ToolError):
        approval_display.build(
            "sweep_execute", {"sweep_id": "sweep_stub", "plan_id": "plan_other"}, Paths()
        )
    with pytest.raises(ToolError):
        approval_display.build(
            "sweep_execute", {"sweep_id": "sweep_missing", "plan_id": "plan_exact"}, Paths()
        )


def test_run_display_keeps_the_case_file_and_timeout(tmp_path):
    source = tmp_path / "case.genkey"
    source.write_text("CASE\n", encoding="utf-8")

    def preview(value, timeout):
        return {
            "selection_id": "selection_exact",
            "runtime_id": "olga-2022.1",
            "detection": {"exe": "OLGA.exe"},
            "timeout_s": timeout,
            "context_generation": 3,
        }

    display = approval_display.build(
        "run_execute",
        {"source": str(source), "selection_id": "selection_exact", "timeout_s": 120},
        Paths(),
        preview,
    )
    assert display["case"] == "case.genkey"
    assert display["timeout_s"] == 120


@pytest.mark.parametrize("locale", ["ko", "en"])
def test_field_rows_carry_keys_and_values_only_so_labels_stay_in_the_dictionary(fluids_workspace, locale):
    display = approval_display.build("fluids_draft_mfl", dict(FLUID_ARGS), Paths(), locale=locale)
    assert display == approval_display.build("fluids_draft_mfl", dict(FLUID_ARGS), Paths(), locale="ko")
    for row in display["fields"]:
        assert set(row) <= {"key", "value", "unit"}
        assert row["value"] != ""


def test_prompt_offers_the_models_the_route_supports_by_name():
    prompt = SYSTEM_PROMPT
    anchor = prompt.index("fluid table (.tab)")
    walk_through = prompt[anchor : anchor + 3000]
    for model in fluid_table.SUPPORTED_MODELS:
        assert model in walk_through, f"{model} is missing from the fluid walk-through"
    assert "PR, PRA, SRK, RKSA, CPA" in walk_through
    assert "offer" in walk_through.casefold()


def test_prompt_never_sends_the_user_to_a_company_standard_or_picks_for_them():
    lowered = SYSTEM_PROMPT.casefold()
    assert "company standard" not in lowered
    assert "사내" not in lowered
    anchor = lowered.index("fluid table (.tab)")
    walk_through = lowered[anchor : anchor + 3000]
    assert "never choose" in walk_through or "do not choose" in walk_through
    assert "for the user" in walk_through
