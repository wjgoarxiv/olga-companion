"""Stage 1 (plans/tab-generation.md T1–T4): draft .mfl, open Multiflash, pick up .tab.

RED-first backend contract. All compositions are synthetic fixtures
(methane/ethane/propane/n-butane/water); no customer data, no guessed physics.
"""
from __future__ import annotations

import glob
import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import fluid_table
from olga_companion.agent import tools
from olga_companion.agent.runtime import SYSTEM_PROMPT
from olga_companion.sidecar import app

FIX = Path(__file__).parent / "fixtures" / "fluids"
VALID_TAB = FIX / "fluid.tab"


def _names() -> dict[str, str]:
    return {
        "METHANE": "METHANE", "CH4": "METHANE", "C1": "METHANE",
        "ETHANE": "ETHANE", "C2": "ETHANE",
        "PROPANE": "PROPANE", "C3": "PROPANE",
        "BUTANE": "BUTANE", "N-BUTANE": "BUTANE", "NC4": "BUTANE",
        "WATER": "WATER", "H2O": "WATER",
    }


def _good_components():
    return [
        {"name": "METHANE", "mole_fraction": 0.7},
        {"name": "ETHANE", "mole_fraction": 0.2},
        {"name": "PROPANE", "mole_fraction": 0.08},
        {"name": "BUTANE", "mole_fraction": 0.02},
    ]


# --- T1: composition validation -------------------------------------------

def test_composition_must_sum_to_one_within_1e_6() -> None:
    ok = fluid_table.validate_composition(_good_components(), _names())
    assert [c["name"] for c in ok] == ["METHANE", "ETHANE", "PROPANE", "BUTANE"]
    assert sum(c["mole_fraction"] for c in ok) == pytest.approx(1.0, abs=1e-6)

    bad = [
        {"name": "METHANE", "mole_fraction": 0.7},
        {"name": "ETHANE", "mole_fraction": 0.2},
    ]
    with pytest.raises(fluid_table.FluidTableError, match="sum"):
        fluid_table.validate_composition(bad, _names())


def test_composition_tolerance_boundary() -> None:
    # Plan budget is ±1e-6: the edge input must pass, the 2e-3 input must fail.
    edge = [
        {"name": "METHANE", "mole_fraction": 0.5},
        {"name": "ETHANE", "mole_fraction": 0.5 - 1e-6},
    ]
    assert fluid_table.validate_composition(edge, _names())
    over = [
        {"name": "METHANE", "mole_fraction": 0.5},
        {"name": "ETHANE", "mole_fraction": 0.5 - 2e-3},
    ]
    with pytest.raises(fluid_table.FluidTableError, match="sum"):
        fluid_table.validate_composition(over, _names())


def test_unknown_component_rejected_with_closest_suggestions() -> None:
    with pytest.raises(fluid_table.UnknownComponentError) as exc:
        fluid_table.validate_composition(
            [{"name": "METANE", "mole_fraction": 1.0}], _names()
        )
    assert "METHANE" in exc.value.suggestions


def test_synonym_canonicalization_has_no_guessed_physics() -> None:
    got = fluid_table.validate_composition(
        [
            {"name": "C1", "mole_fraction": 0.5},
            {"name": "n-butane", "mole_fraction": 0.3},
            {"name": "H2O", "mole_fraction": 0.2},
        ],
        _names(),
    )
    assert [c["name"] for c in got] == ["METHANE", "BUTANE", "WATER"]


def test_model_is_an_explicit_documented_choice() -> None:
    with pytest.raises(fluid_table.FluidTableError, match="model"):
        fluid_table.validate_model("", fluid_table.SUPPORTED_MODELS)
    with pytest.raises(fluid_table.FluidTableError, match="model"):
        fluid_table.validate_model("MADEUP-EOS", fluid_table.SUPPORTED_MODELS)
    assert fluid_table.validate_model("SRK", fluid_table.SUPPORTED_MODELS) == "SRK"


def test_supported_models_come_from_documented_manuals() -> None:
    assert set(fluid_table.SUPPORTED_MODELS) == {"PR", "PRA", "SRK", "RKSA", "CPA"}
    with pytest.raises(fluid_table.FluidTableError, match="model"):
        fluid_table.validate_model("GERG-2008", fluid_table.SUPPORTED_MODELS)
    with pytest.raises(fluid_table.FluidTableError, match="model"):
        fluid_table.validate_model("PC-SAFT", fluid_table.SUPPORTED_MODELS)


# --- T1: exact table Olga text per mfcmd p.80 ------------------------------

def test_table_command_exact_text_per_manual(tmp_path: Path) -> None:
    tab = tmp_path / "synthetic.tab"
    command = fluid_table.build_table_command(
        tab_abs_path=str(tab),
        fluid_label="SYN1",
        temperatures=[-10.0, 0.0, 50.0],
        temperature_unit="degC",
        pressures=[0.0, 2.5, 5.0],
        pressure_unit="barg",
    )
    assert command == (
        f'table Olga "{tab}" title "SYN1" '
        "temperatures degC -10 0 50; pressures barg 0 2.5 5; ;"
    )


def test_table_command_units_are_explicit_and_hawater_opt_in(tmp_path: Path) -> None:
    tab = tmp_path / "synthetic.tab"
    plain = fluid_table.build_table_command(
        tab_abs_path=str(tab), fluid_label="SYN1",
        temperatures=[0.0, 10.0], temperature_unit="degC",
        pressures=[1.0, 2.0], pressure_unit="bar",
    )
    assert "HAWATER" not in plain
    wet = fluid_table.build_table_command(
        tab_abs_path=str(tab), fluid_label="SYN1",
        temperatures=[0.0, 10.0], temperature_unit="degC",
        pressures=[1.0, 2.0], pressure_unit="bar", hawater=True,
    )
    assert "HAWATER" in wet
    assert wet.index("HAWATER") < wet.index("temperatures")


_ORIG_CPA_TABLE = """table olga "M:\\MFL\\42\\Examp\\MFOlga1.tab" info hydratefile
"M:\\MFL\\42\\Examp\\MFOlgaHyd1.hyd" title * temperatures   245.0000   255.0000
  265.0000   275.0000   285.0000   295.0000   305.0000   315.0000   325.0000
  335.0000   345.0000   355.0000   365.0000   375.0000   385.0000   395.0000
  405.0000   415.0000   425.0000   435.0000   445.0000   455.0000   465.0000
  475.0000   485.0000   495.0000   505.0000   515.0000   525.0000   535.0000
  545.0000   555.0000   565.0000   575.0000   585.0000   595.0000   605.0000
  615.0000   625.0000   635.0000   645.0000   655.0000   665.0000   675.0000
  685.0000   695.0000   705.0000   715.0000   725.0000   735.0000 ; pressures
  10000.00   510000.0   1010000.   1510000.   2010000.   2510000.   3010000.
  3510000.   4010000.   4510000.   5010000.   5510000.   6010000.   6510000.
  7010000.   7510000.   8010000.   8510000.   9010000.   9510000.
 1.0010000E+07  1.0510000E+07  1.1010000E+07  1.1510000E+07  1.2010000E+07
 1.2510000E+07  1.3010000E+07  1.3510000E+07  1.4010000E+07  1.4510000E+07
 1.5010000E+07  1.5510000E+07  1.6010000E+07  1.6510000E+07  1.7010000E+07
 1.7510000E+07  1.8010000E+07  1.8510000E+07  1.9010000E+07  1.9510000E+07
 2.0010000E+07  2.0510000E+07  2.1010000E+07  2.1510000E+07  2.2010000E+07
 2.2510000E+07  2.3010000E+07  2.3510000E+07  2.4010000E+07  2.4510000E+07 ; ;"""
_ORIG_CPA_UNITS = (
    "units temperature K pressure bar enthalpy J/mol entropy J/mol/K volume m3/mol"
)


_GOLDEN_COMPONENTS = [
    {"name": "METHANE", "mole_fraction": 0.85},
    {"name": "ETHANE", "mole_fraction": 0.08},
    {"name": "PROPANE", "mole_fraction": 0.05},
    {"name": "BUTANE", "mole_fraction": 0.02},
]
def _require_templates() -> None:
    try:
        fluid_table.template_text("PR")
    except fluid_table.FluidTableError:
        pytest.skip("Multiflash samples are unavailable here")


_GOLDEN_BLOCK = """Components overwrite
1 METHANE
2 ETHANE
3 PROPANE
4 BUTANE ;
amounts 0.85 0.08 0.05 0.02;
Temperature 293.15;
Pressure 101325;
units temperature degC pressure bar enthalpy J/mol entropy J/mol/K volume m3/mol amounts mole viscosity Pas thcond W/m/K surten N/m diffusion m2/s GOR sm3/sm3;
table Olga "/tmp/syntest.tab" title "SYNTEST" temperatures degC 0 20 40 60 80; pressures bar 1 20 50 100 150; ;"""


@pytest.mark.parametrize(
    ("choice", "model_line"),
    [
        ("PR", "model MPR PR PRBIP;"),
        ("PRA", "model MPRA PRA PSAT LDEN VDW PRABIP;"),
        ("SRK", "model MRKS RKS RKS RKSBIP;"),
        ("RKSA", "model MRKSA RKSA PSAT LDEN VDW RKSABIP;"),
    ],
)
def test_config_template_draft_is_template_plus_substitution_block(
    choice: str, model_line: str
) -> None:
    """Golden: config drafts append only the user block to the vendor file."""
    _require_templates()
    draft = fluid_table.build_mfl_text(
        fluid_label="SYNTEST",
        components=_GOLDEN_COMPONENTS,
        model=choice,
        temperatures=[0.0, 20.0, 40.0, 60.0, 80.0],
        temperature_unit="C",
        pressures=[1.0, 20.0, 50.0, 100.0, 150.0],
        pressure_unit="bar",
        tab_abs_path="/tmp/syntest.tab",
        databank_names=_names(),
    )
    template = fluid_table.template_text(choice)
    assert model_line in template  # the vendor EOS line itself
    assert draft == template.rstrip("\n") + "\n" + _GOLDEN_BLOCK + "\n"


def test_cpa_template_draft_substitutes_only_user_fields() -> None:
    """Golden: OLGA.MFL copy with components/amounts/table/units replaced."""
    _require_templates()
    draft = fluid_table.build_mfl_text(
        fluid_label="SYN-CPA",
        components=[
            {"name": "METHANE", "mole_fraction": 0.7},
            {"name": "ETHANE", "mole_fraction": 0.15},
            {"name": "PROPANE", "mole_fraction": 0.08},
            {"name": "BUTANE", "mole_fraction": 0.05},
            {"name": "WATER", "mole_fraction": 0.02},
        ],
        model="CPA",
        temperatures=[0.0, 20.0, 40.0, 60.0, 80.0],
        temperature_unit="C",
        pressures=[1.0, 20.0, 50.0, 100.0, 150.0],
        pressure_unit="bar",
        tab_abs_path="/tmp/synth_cpa.tab",
        databank_names=_names(),
    )
    expected_components = "components overwrite\n1 METHANE\n2 ETHANE\n3 PROPANE\n4 BUTANE\n5 WATER ;"
    expected_amounts = "amounts 0.7 0.15 0.08 0.05 0.02;"
    expected_table = (
        'table olga "/tmp/synth_cpa.tab" title "SYN-CPA" temperatures 0 20 40 60 80 ; pressures\n'
        "  1 20 50 100 150 ; ;"
    )
    expected_units = (
        "units temperature degC pressure bar enthalpy J/mol entropy J/mol/K volume m3/mol"
    )
    for region in (expected_components, expected_amounts, expected_table, expected_units):
        assert region in draft
    assert "M:\\MFL\\42\\Examp\\MFOlga1.tab" not in draft
    assert "title *" not in draft
    template = fluid_table.template_text("CPA")
    # Rebuild the expected draft from the vendor file by the stated edits only:
    # user components/amounts/units, the vendor table block and the hydrate/ice
    # lines removed, the user table command appended last. Everything else is
    # vendor-verbatim, compared exactly.
    vendor_components = (
        "components overwrite 1 METHANE  \n2 ETHANE  \n3 PROPANE  \n4 BUTANE  \n"
        "5 HEXANE  \n6 DECANE  \n7 WATER ;"
    )
    assert template.count(vendor_components) == 1
    assert template.count("amounts .45 .2 .1 .1 .1 .05 10.;") == 1
    assert template.count(_ORIG_CPA_TABLE + "\n") == 1
    assert template.count(_ORIG_CPA_UNITS) == 1
    expected = template.replace(vendor_components, expected_components, 1)
    expected = expected.replace("amounts .45 .2 .1 .1 .1 .05 10.;", expected_amounts, 1)
    expected = expected.replace(_ORIG_CPA_TABLE + "\n", "", 1)
    expected = expected.replace(_ORIG_CPA_UNITS, expected_units, 1)
    for line in _CPA_HYDRATE_ICE_LINES:
        assert template.count(line + "\n") == 1, line
        expected = expected.replace(line + "\n", "", 1)
    # The vendor file ends with a line holding one space; the draft drops it and
    # ends with the table command.
    assert template.endswith("set physprops 1VCS;\n \n")
    expected = expected[: -len(" \n")] + expected_table + "\n"
    assert draft == expected


_CPA_HYDRATE_ICE_LINES = (
    "model MHYD2MASSOC HYDRATE II MASSOC;",
    "model MICEMASSOC FREEZEOUT 007732-18-5#WATER# MASSOC;",
    "pd HYDRATE2 hydrate MHYD2MASSOC;",
    "pd ICE condensed MICEMASSOC;",
)


def _air_water_cpa_draft() -> str:
    return fluid_table.build_mfl_text(
        fluid_label="AIR_WATER",
        components=[
            {"name": "WATER", "mole_fraction": 0.5},
            {"name": "NITROGEN", "mole_fraction": 0.395},
            {"name": "OXYGEN", "mole_fraction": 0.105},
        ],
        model="CPA",
        temperatures=[0.0, 10.0, 20.0, 25.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0],
        temperature_unit="C",
        pressures=[0.5, 0.8, 1.01325, 1.2, 1.5, 2.0, 3.0, 5.0, 8.0, 12.0, 16.0, 20.0],
        pressure_unit="bar",
        tab_abs_path="/tmp/air_water_cpa.tab",
        databank_names={"WATER": "WATER", "NITROGEN": "NITROGEN", "OXYGEN": "OXYGEN"},
    )


def test_cpa_draft_carries_no_hydrate_or_ice_phase() -> None:
    """Owner decision: CPA drafts drop the hydrate and ice set, as the
    GUI-made air_water_cpa.mfl does."""
    _require_templates()
    draft = _air_water_cpa_draft()
    for word in ("HYDRATE", "MHYD2MASSOC", "MICEMASSOC", "FREEZEOUT", "pd ICE", "hydratefile", ".hyd"):
        assert word not in draft, word


def _statement_heads(text: str) -> list[str]:
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    heads = []
    for statement in body.split(";"):
        words = statement.split()
        if words:
            heads.append(" ".join(words[:2]).lower())
    return heads


def test_air_water_cpa_draft_follows_the_owner_made_file_order() -> None:
    """Command order matches resources/fluids/air_water_cpa.mfl, except the
    vendor-only LIQUID2 phase and pseudo-component property line kept by design."""
    _require_templates()
    owner = (Path(__file__).resolve().parents[1] / "resources" / "fluids" / "air_water_cpa.mfl").read_text(
        encoding="utf-8"
    )
    allow = {"properties pfc6plusmw", "pd liquid2", "key liquid2"}
    draft_heads = [head for head in _statement_heads(_air_water_cpa_draft()) if head not in allow]
    owner_heads = _statement_heads(owner)
    assert draft_heads == owner_heads


def test_cpa_draft_runs_table_after_model_components_and_user_units() -> None:
    """Multiflash executes top to bottom: the table command needs the system
    defined and the user's degC/bar units active (air_water_cpa.mfl order)."""
    _require_templates()
    draft = fluid_table.build_mfl_text(
        fluid_label="SYN-CPA",
        components=[
            {"name": "METHANE", "mole_fraction": 0.9},
            {"name": "WATER", "mole_fraction": 0.1},
        ],
        model="CPA",
        temperatures=[0.0, 20.0],
        temperature_unit="C",
        pressures=[1.0, 20.0],
        pressure_unit="bar",
        tab_abs_path="/tmp/synth_cpa.tab",
        databank_names=_names(),
    )
    assert draft.count("table olga") == 1
    table_at = draft.index("table olga")
    for earlier in ("components overwrite", "model MASSOC", "pd GAS", "amounts 0.9 0.1;"):
        assert draft.index(earlier) < table_at, f"{earlier!r} must precede the table command"
    user_units = "units temperature degC pressure bar"
    assert draft.rindex("units temperature") < table_at
    assert draft.rindex("units temperature") == draft.index(user_units)
    assert draft.index("set physprops") < table_at


def test_cpa_template_rejects_hawater_without_a_slot() -> None:
    _require_templates()
    with pytest.raises(fluid_table.FluidTableError, match="HAWATER"):
        fluid_table.build_mfl_text(
            fluid_label="SYN-CPA",
            components=[{"name": "METHANE", "mole_fraction": 1.0}],
            model="CPA",
            temperatures=[0.0, 50.0], temperature_unit="C",
            pressures=[1.0, 150.0], pressure_unit="bar",
            tab_abs_path="/tmp/synth_cpa.tab",
            databank_names=_names(),
            hawater=True,
        )


def test_aqueous_compositions_allowed_on_all_templates() -> None:
    _require_templates()
    wet = [
        {"name": "METHANE", "mole_fraction": 0.8},
        {"name": "WATER", "mole_fraction": 0.2},
    ]
    for choice in fluid_table.SUPPORTED_MODELS:
        draft = fluid_table.build_mfl_text(
            fluid_label="SYNWET",
            components=wet,
            model=choice,
            temperatures=[0.0, 50.0], temperature_unit="C",
            pressures=[1.0, 150.0], pressure_unit="bar",
            tab_abs_path="/tmp/synwet.tab",
            databank_names=_names(),
        )
        assert "WATER" in draft


def test_template_loader_reads_cited_vendor_samples() -> None:
    """The runtime loader returns the cited sample files verbatim.

    Registry (MFL files\\ sample, full-file line ranges): PR.MFL 1-62,
    PRA.MFL 1-65, RKS.MFL 1-62, RKSA.MFL 1-66, OLGA.MFL 1-58.
    """
    from olga_companion.fluid_table import _MODEL_TEMPLATES, _sample_dir

    try:
        sample_dir = _sample_dir()
    except fluid_table.FluidTableError:
        pytest.skip("OLGA is not installed here")
    assert set(_MODEL_TEMPLATES) == set(fluid_table.SUPPORTED_MODELS)
    markers = {
        "PR": ["model MPR PR PRBIP;", "pd WATER liquid MPR", "key WATER 007732-18-5;"],
        "PRA": ["model MPRA PRA PSAT LDEN VDW PRABIP;", "pd WATER liquid MPRA", "key WATER 007732-18-5;"],
        "SRK": ["model MRKS RKS RKS RKSBIP;", "pd WATER liquid MRKS", "key WATER 007732-18-5;"],
        "RKSA": ["model MRKSA RKSA PSAT LDEN VDW RKSABIP;", "pd WATER liquid MRKSA", "key WATER 007732-18-5;"],
        "CPA": ["model MASSOC ASSOC PSAT ASSOCBIP ASSOCBIP-2;", "table olga", "7 WATER ;"],
    }
    for choice, entry in _MODEL_TEMPLATES.items():
        raw = (sample_dir / str(entry["file"])).read_bytes()
        assert raw, str(entry["file"])
        text = fluid_table.template_text(choice)
        assert text == raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
        line_count = len(raw.decode("utf-8", errors="replace").splitlines())
        assert line_count == int(str(entry["sample_lines"]).split("-")[1]), str(entry["file"])
        for marker in markers[choice]:
            assert marker in text, (choice, marker)


def test_unit_keywords_map_to_the_manual_table() -> None:
    assert fluid_table.canonical_temperature_unit("C") == "degC"
    assert fluid_table.canonical_temperature_unit("degF") == "degF"
    assert fluid_table.canonical_pressure_unit("MPa") == "Mpa"
    assert fluid_table.canonical_pressure_unit("barg") == "barg"
    for bad in ("bara", "psia", "celsius", "R", ""):
        with pytest.raises(fluid_table.FluidTableError, match="[Uu]nit"):
            fluid_table.canonical_temperature_unit(bad)
    for bad in ("bara", "psia", "C", "mm", ""):
        with pytest.raises(fluid_table.FluidTableError, match="[Uu]nit"):
            fluid_table.canonical_pressure_unit(bad)
    command = fluid_table.build_table_command(
        "/tmp/s.tab", "SYN1", [0.0, 10.0], "C", [1.0, 2.0], "MPa",
    )
    assert "temperatures degC" in command and "pressures Mpa" in command


def test_wsl_paths_become_windows_paths_in_drafts() -> None:
    _require_templates()
    assert fluid_table.multiflash_path("/mnt/c/Users/Woojin/x/s.tab") == "C:\\Users\\Woojin\\x\\s.tab"
    assert fluid_table.multiflash_path("C:\\Work\\s.tab") == "C:\\Work\\s.tab"
    assert fluid_table.multiflash_path("/tmp/s.tab") == "/tmp/s.tab"
    draft = fluid_table.build_mfl_text(
        fluid_label="SYNTEST",
        components=_GOLDEN_COMPONENTS,
        model="PR",
        temperatures=[0.0, 50.0], temperature_unit="degC",
        pressures=[1.0, 150.0], pressure_unit="bar",
        tab_abs_path="/mnt/c/Users/Woojin/x/syntest.tab",
        databank_names=_names(),
    )
    assert "/mnt/c" not in draft
    assert "C:\\Users\\Woojin\\x\\syntest.tab" in draft


# --- T1: new files only through the approval path, never overwrite --------

def test_draft_write_refuses_existing_file_and_preserves_originals(tmp_path: Path) -> None:
    target = tmp_path / "fluid.mfl"
    target.write_text("original", encoding="utf-8")
    with pytest.raises(fluid_table.FluidTableError, match="exists"):
        fluid_table.write_draft_mfl(str(target), "new content")
    assert target.read_text(encoding="utf-8") == "original"


def test_draft_side_effect_tool_is_approval_gated() -> None:
    tool = tools.TOOLS["fluids_draft_mfl"]
    assert tool.side_effect is True
    props = tool.parameters["properties"]
    assert "approval_token" in props and "idempotency_key" in props
    assert "approval_token" in tool.parameters["required"]
    with pytest.raises(tools.ToolError, match="approval"):
        tools.dispatch("fluids_draft_mfl", {
            "fluid_label": "SYN1",
            "components": [{"name": "METHANE", "mole_fraction": 1.0}],
            "model": "SRK",
            "temperatures": [-10.0, 50.0],
            "temperature_unit": "degC",
            "pressures": [0.0, 5.0],
            "pressure_unit": "barg",
            "mfl_rel": "synthetic.mfl",
        })


def test_draft_preview_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_templates()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    before = {p.name for p in tmp_path.iterdir()}
    result = tools.dispatch("fluids_draft_preview", {
        "fluid_label": "SYN1",
        "components": [{"name": "METHANE", "mole_fraction": 1.0}],
        "model": "SRK",
        "temperatures": [-10.0, 50.0],
        "temperature_unit": "degC",
        "pressures": [0.0, 5.0],
        "pressure_unit": "barg",
        "mfl_rel": "synthetic.mfl",
    })
    assert result["table_command"].startswith('table Olga "')
    assert {p.name for p in tmp_path.iterdir()} == before


# --- T2: MFBJ01 discovery + explicit-action launch -------------------------

def test_multiflash_discovery_reports_present_and_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "MFBJ01.exe"
    exe.write_bytes(b"fake")
    monkeypatch.setenv("MULTIFLASH_HOME", str(tmp_path))
    found = fluid_table.find_multiflash()
    assert found["found"] is True
    assert Path(found["exe"]).name == "MFBJ01.exe"

    monkeypatch.delenv("MULTIFLASH_HOME")
    monkeypatch.setattr(fluid_table, "_install_globs", lambda: ["C:/nonexistent-xyz/*"])
    missing = fluid_table.find_multiflash()
    assert missing["found"] is False
    assert "Multiflash" in missing["message"]


def test_multiflash_open_tool_is_approval_gated_and_reports_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = tools.TOOLS["multiflash_open"]
    assert tool.side_effect is True
    with pytest.raises(tools.ToolError, match="approval"):
        tools.dispatch("multiflash_open", {})
    monkeypatch.setattr(fluid_table, "_install_globs", lambda: ["C:/nonexistent-xyz/*"])
    monkeypatch.delenv("MULTIFLASH_HOME", raising=False)
    from olga_companion import workspace
    from olga_companion.agent import approvals

    payload = tools.approval_payload("multiflash_open", {})
    token = approvals.mint(
        "multiflash_open", payload,
        context_generation=workspace.context_generation(),
    )["token"]
    with pytest.raises(tools.ToolError, match="[Mm]ultiflash"):
        tools.dispatch("multiflash_open", {
            "approval_token": token, "idempotency_key": "k" * 32,
        })


# --- T3: pickup + validation + label match ---------------------------------

def test_pickup_tab_validates_and_matches_label(tmp_path: Path) -> None:
    from olga_companion import fluids as fluids_module

    if not fluids_module.fluids_toolkit_status()["available"]:
        pytest.skip("fluid toolkit scripts unavailable")
    result = fluid_table.pickup_tab(str(VALID_TAB), fluid_label="FLUID-A")
    assert result["found"] is True
    assert result["valid"] is True
    assert result["label_match"] is True
    assert result["declared_label"] == "FLUID-A"
    assert result["link_proposal"]["fluid_label"] == "FLUID-A"


def test_pickup_tab_label_mismatch_is_reported_not_linked(tmp_path: Path) -> None:
    from olga_companion import fluids as fluids_module

    if not fluids_module.fluids_toolkit_status()["available"]:
        pytest.skip("fluid toolkit scripts unavailable")
    result = fluid_table.pickup_tab(str(VALID_TAB), fluid_label="OTHER")
    assert result["found"] is True
    assert result["label_match"] is False
    assert result["link_proposal"] is None


def test_pickup_tab_missing_file_is_reported() -> None:
    result = fluid_table.pickup_tab("/nonexistent-xyz/missing.tab", fluid_label="FLUID-A")
    assert result["found"] is False
    assert result["valid"] is False


def test_expected_tab_extracted_from_mfl(tmp_path: Path) -> None:
    mfl = tmp_path / "case.mfl"
    mfl.write_text(
        'remove all;\ntable Olga "C:/work/synthetic.tab" title "SYN1" '
        "temperatures degC -10 50; pressures barg 0 5; ;\n",
        encoding="utf-8",
    )
    assert fluid_table.expected_tab_for_mfl(str(mfl)) == "C:/work/synthetic.tab"


# --- T4: assistant ----------------------------------------------------------

def test_agent_tool_belt_covers_draft_open_pickup() -> None:
    for name in ("fluids_draft_mfl", "fluids_draft_preview", "multiflash_open", "fluids_pickup_tab"):
        assert name in tools.TOOLS, name
    specs = {spec["name"]: spec for spec in tools.tool_specs()}
    for name in ("fluids_draft_mfl", "multiflash_open", "fluids_pickup_tab"):
        assert name in specs, name


def test_system_prompt_walks_through_fluid_table_flow() -> None:
    assert "cannot make a .tab" not in SYSTEM_PROMPT
    lowered = SYSTEM_PROMPT.lower()
    assert "fluids_draft_mfl" in SYSTEM_PROMPT
    assert "multiflash_open" in SYSTEM_PROMPT
    assert "fluids_pickup_tab" in SYSTEM_PROMPT
    assert "composition" in lowered


def test_fluid_http_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_templates()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    shutil.copy2(VALID_TAB, tmp_path / "fluid.tab")
    client = TestClient(app)

    draft = {
        "fluid_label": "SYN1",
        "components": [{"name": "METHANE", "mole_fraction": 1.0}],
        "model": "SRK",
        "temperatures": [-10.0, 50.0],
        "temperature_unit": "degC",
        "pressures": [0.0, 5.0],
        "pressure_unit": "barg",
        "mfl_rel": "synthetic.mfl",
    }
    preview = client.post("/api/fluids/draft-preview", json=draft)
    assert preview.status_code == 200
    assert preview.json()["table_command"].startswith('table Olga "')
    assert not (tmp_path / "synthetic.mfl").exists()

    unapproved = client.post("/api/fluids/open-multiflash", json={"approved": False})
    assert unapproved.status_code == 400

    monkeypatch.setattr(fluid_table, "_install_globs", lambda: ["C:/nonexistent-xyz/*"])
    monkeypatch.delenv("MULTIFLASH_HOME", raising=False)
    missing = client.post("/api/fluids/open-multiflash", json={"approved": True})
    assert missing.status_code == 404

    pickup = client.post(
        "/api/fluids/pickup-tab",
        json={"path": str(tmp_path / "fluid.tab"), "fluid_label": "FLUID-A"},
    )
    assert pickup.status_code == 200
    assert pickup.json()["valid"] is True
    assert pickup.json()["declared_label"] == "FLUID-A"


def test_approval_payload_canonicalizes_unit_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion.agent import tool_side_effects

    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(fluid_table, "databank_names", lambda *args, **kwargs: _names())
    payload = tool_side_effects.approval_payload("fluids_draft_mfl", {
        "fluid_label": "SYN1",
        "components": [{"name": "METHANE", "mole_fraction": 1.0}],
        "model": "SRK",
        "temperatures": [-10.0, 50.0],
        "temperature_unit": "C",
        "pressures": [0.0, 5.0],
        "pressure_unit": "MPa",
        "mfl_rel": "synthetic.mfl",
    })
    assert payload["temperature_unit"] == "degC"
    assert payload["pressure_unit"] == "Mpa"


@pytest.mark.parametrize(
    ("temperature_unit", "pressure_unit", "want_temperature", "want_pressure"),
    [
        ("C", "MPa", "degC", "Mpa"),
        ("c", "kpa", "degC", "kPa"),
        ("degc", "BAR", "degC", "bar"),
        ("K", "psig", "K", "psig"),
    ],
)
def test_approval_payload_canonicalizes_unit_alias_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    temperature_unit: str,
    pressure_unit: str,
    want_temperature: str,
    want_pressure: str,
) -> None:
    from olga_companion.agent import tool_side_effects

    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(fluid_table, "databank_names", lambda *args, **kwargs: _names())
    payload = tool_side_effects.approval_payload("fluids_draft_mfl", {
        "fluid_label": "SYN1",
        "components": [{"name": "METHANE", "mole_fraction": 1.0}],
        "model": "SRK",
        "temperatures": [-10.0, 50.0],
        "temperature_unit": temperature_unit,
        "pressures": [0.0, 5.0],
        "pressure_unit": pressure_unit,
        "mfl_rel": "synthetic.mfl",
    })
    assert payload["temperature_unit"] == want_temperature
    assert payload["pressure_unit"] == want_pressure


@pytest.mark.parametrize("temperature_unit,pressure_unit", [
    ("°C", "bar"),
    ("celsius", "bar"),
    ("degC", "bara"),
    ("C", "bara"),
    ("celsius", "celsius"),
])
def test_approval_payload_rejects_non_keyword_unit_spellings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    temperature_unit: str,
    pressure_unit: str,
) -> None:
    from olga_companion.agent import tool_side_effects
    from olga_companion.agent.tool_validation import ToolError

    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(fluid_table, "databank_names", lambda *args, **kwargs: _names())
    with pytest.raises(ToolError, match="[Uu]nit"):
        tool_side_effects.approval_payload("fluids_draft_mfl", {
            "fluid_label": "SYN1",
            "components": [{"name": "METHANE", "mole_fraction": 1.0}],
            "model": "SRK",
            "temperatures": [-10.0, 50.0],
            "temperature_unit": temperature_unit,
            "pressures": [0.0, 5.0],
            "pressure_unit": pressure_unit,
            "mfl_rel": "synthetic.mfl",
        })


def test_databank_lookup_is_read_only(tmp_path: Path) -> None:
    db = tmp_path / "infodata.db"
    source = sqlite3.connect(str(db))
    source.execute("CREATE TABLE Components (ID INTEGER, COMPONENTName TEXT)")
    source.execute("INSERT INTO Components VALUES (1, 'METHANE')")
    source.execute("CREATE TABLE Synonyms (ID INTEGER, Synonyms TEXT)")
    source.execute("INSERT INTO Synonyms VALUES (1, 'C1')")
    source.commit()
    source.close()
    before = db.stat().st_mtime_ns
    names = fluid_table.databank_names(str(db))
    assert names["C1"] == "METHANE"
    assert db.stat().st_mtime_ns == before


# --- Multiflash comparison findings (2026-10-31): the draft must load in MFBJ01 ---

def _co2_c3_names() -> dict[str, str]:
    return {
        "CARBON DIOXIDE": "CARBON DIOXIDE", "CO2": "CARBON DIOXIDE",
        "PROPANE": "PROPANE", "C3": "PROPANE",
        "ACETIC ACID": "ACETIC ACID",
        "METHYL DIETHANOLAMINE": "METHYL DIETHANOLAMINE", "MDEA": "METHYL DIETHANOLAMINE",
    }


_CO2_C3 = [
    {"name": "CO2", "mole_fraction": 0.9},
    {"name": "PROPANE", "mole_fraction": 0.1},
]


def _draft(model: str, components, names=None) -> str:
    return fluid_table.build_mfl_text(
        fluid_label="CO2C3MF",
        components=components,
        model=model,
        temperatures=[0.0, 50.0], temperature_unit="C",
        pressures=[1.0, 100.0], pressure_unit="bar",
        tab_abs_path="/tmp/co2c3.tab",
        databank_names=names or _co2_c3_names(),
    )


@pytest.mark.parametrize("model", ["PR", "PRA", "SRK", "RKSA", "CPA"])
def test_draft_names_co2_by_its_short_databank_id(model: str) -> None:
    _require_templates()
    draft = _draft(model, _CO2_C3)
    assert "1 CO2" in draft
    assert "CARBON DIOXIDE" not in draft
    assert "2 PROPANE ;" in draft


def test_config_draft_last_component_has_a_space_before_the_semicolon() -> None:
    _require_templates()
    draft = _draft("PR", _CO2_C3)
    assert "\n1 CO2\n2 PROPANE ;\namounts 0.9 0.1;" in draft
    assert "PROPANE;" not in draft


def test_long_databank_name_is_requested_by_a_short_id_when_one_exists() -> None:
    names = _co2_c3_names()
    assert fluid_table.mfl_component_name("CARBON DIOXIDE", names) == "CO2"
    assert fluid_table.mfl_component_name("METHYL DIETHANOLAMINE", names) == "MDEA"
    assert fluid_table.mfl_component_name("PROPANE", names) == "PROPANE"


def test_a_multi_word_name_without_a_short_id_is_quoted_like_the_vendor_samples() -> None:
    _require_templates()
    assert fluid_table.mfl_component_name("ACETIC ACID", _co2_c3_names()) == '"ACETIC ACID"'
    draft = _draft(
        "PR",
        [{"name": "ACETIC ACID", "mole_fraction": 0.5}, {"name": "PROPANE", "mole_fraction": 0.5}],
    )
    assert '1 "ACETIC ACID"' in draft


def test_no_unquoted_multi_word_component_name_is_emitted() -> None:
    _require_templates()
    components = [
        {"name": "CARBON DIOXIDE", "mole_fraction": 0.4},
        {"name": "ACETIC ACID", "mole_fraction": 0.3},
        {"name": "METHYL DIETHANOLAMINE", "mole_fraction": 0.2},
        {"name": "PROPANE", "mole_fraction": 0.1},
    ]
    for model in ("PR", "CPA"):
        draft = _draft(model, components)
        block = draft[draft.lower().rindex("components overwrite"):]
        listed = re.findall(r"(?m)^\d+ (.+?)(?:\s*;)?[ \t]*$", block.split("amounts", 1)[0])
        assert len(listed) == 4
        for token in listed:
            assert token.startswith('"') or " " not in token, token


def test_every_databank_component_gets_a_token_multiflash_can_read() -> None:
    try:
        names = fluid_table.databank_names()
    except fluid_table.FluidTableError:
        pytest.skip("Multiflash databank is unavailable here")
    for canonical in sorted(set(names.values())):
        token = fluid_table.mfl_component_name(canonical, names)
        assert token.startswith('"') or re.fullmatch(r"[A-Za-z0-9_]+", token), (canonical, token)
        if not token.startswith('"'):
            assert names.get(token.upper()) == canonical, (canonical, token)
    assert fluid_table.mfl_component_name("CARBON DIOXIDE", names) == "CO2"


def test_launch_starts_multiflash_in_its_own_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "MFBJ01.exe"
    exe.write_bytes(b"fake")
    mfl = tmp_path / "draft.mfl"
    mfl.write_text("remove all;\n", encoding="utf-8")
    calls: list[tuple[list[str], dict]] = []

    class FakeProcess:
        pid = 4242

    def fake_popen(args, **kwargs):
        calls.append((list(args), kwargs))
        return FakeProcess()

    monkeypatch.setattr(fluid_table.subprocess, "Popen", fake_popen)
    result = fluid_table.launch_multiflash(str(exe), str(mfl))
    assert result["pid"] == 4242
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == [str(exe), str(mfl)]
    assert Path(kwargs["cwd"]) == exe.parent

    fluid_table.launch_multiflash(str(exe))
    assert Path(calls[1][1]["cwd"]) == exe.parent
