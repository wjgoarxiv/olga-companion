from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from olga_companion import case_compiler
from case_spec_v2_support import PVT_TABLE_TEXT, with_v2_inputs


SPEC = with_v2_inputs({
    "version": "1",
    "nodes": [
        {"label": "SOURCE_A", "kind": "source", "pressure_pa": 2_000_000.0},
        {"label": "TEE_A", "kind": "junction"},
        {"label": "SINK_A", "kind": "sink", "pressure_pa": 1_000_000.0},
        {"label": "SINK_B", "kind": "sink", "pressure_pa": 900_000.0},
    ],
    "flowpaths": [
        {
            "label": "MAIN",
            "from": "SOURCE_A",
            "to": "TEE_A",
            "pipes": [{
                "label": "PIPE_A", "centerline_m": [[0, 0, 0], [100, 0, 5]],
                "diameter_m": 0.1, "sections": 10,
            }],
        },
        {
            "label": "BRANCH",
            "from": "TEE_A",
            "to": "SINK_A",
            "pipes": [{
                "label": "PIPE_B", "centerline_m": [[100, 0, 5], [160, 25, 0]],
                "diameter_m": 0.08, "sections": 6,
            }],
        },
        {
            "label": "BRANCH_B",
            "from": "TEE_A",
            "to": "SINK_B",
            "pipes": [{
                "label": "PIPE_C", "centerline_m": [[100, 0, 5], [150, -20, 2]],
                "diameter_m": 0.06, "sections": 5,
            }],
        },
    ],
    "pvt_reference": "fluid.tab",
    "integration": {"end_time_s": 3600.0},
    "outputs": ["PT", "TM"],
})


def _clean_toolkit(text: str) -> case_compiler.ToolkitVerification:
    assert "ENDCASE" in text
    return case_compiler.ToolkitVerification(
        clean=True,
        parser_clean=True,
        validator_clean=True,
        diagnostics=(),
    )


def test_custom_branch_compile_is_byte_identical_and_read_only(tmp_path: Path) -> None:
    owner = tmp_path / "owner.genkey"
    owner.write_bytes(b"CASE LABEL=owner\nENDCASE\n")
    companion = tmp_path / "fluid.tab"
    companion.write_text(PVT_TABLE_TEXT, encoding="utf-8")
    owner_hash = hashlib.sha256(owner.read_bytes()).hexdigest()

    first = case_compiler.compile_case_spec(SPEC, owner, verify=_clean_toolkit)
    second = case_compiler.compile_case_spec(deepcopy(SPEC), owner, verify=_clean_toolkit)

    assert first.compiled_bytes == second.compiled_bytes
    assert first.sha256 == hashlib.sha256(first.compiled_bytes).hexdigest()
    assert first.sha256 == second.sha256
    assert first.topology_edges == (
        ("SOURCE_A", "TEE_A", "MAIN"),
        ("TEE_A", "SINK_A", "BRANCH"),
        ("TEE_A", "SINK_B", "BRANCH_B"),
    )
    assert b"TAG=MAIN" in first.compiled_bytes
    assert b"TAG=BRANCH_B" in first.compiled_bytes
    assert b"TYPE=JUNCTIONNODE, TAG=TEE_A" in first.compiled_bytes
    assert b"TEE_A MIXTERM, MAIN OUTLET" in first.compiled_bytes
    assert b"TEE_A FLOWTERM_1, BRANCH INLET" in first.compiled_bytes
    assert b"TEE_A FLOWTERM_2, BRANCH_B INLET" in first.compiled_bytes
    assert b"GEOMETRY LABEL=\"G-MAIN\", XSTART=0 m, YSTART=0 m, ZSTART=0 m" in first.compiled_bytes
    assert first.source_mutated is False
    assert first.companion_status == "verified"
    assert first.warnings == ()
    assert hashlib.sha256(owner.read_bytes()).hexdigest() == owner_hash
    assert set(tmp_path.iterdir()) == {owner, companion}


def test_compile_rejects_missing_contained_pvt_companion(tmp_path: Path) -> None:
    owner = tmp_path / "owner.genkey"
    owner.write_bytes(b"CASE LABEL=owner\nENDCASE\n")

    with pytest.raises(ValueError, match="PVT companion is missing"):
        case_compiler.compile_case_spec(SPEC, owner, verify=_clean_toolkit)


def test_33_sections_render_exact_positive_lsegment_lengths() -> None:
    spec = deepcopy(SPEC)
    spec["flowpaths"][0]["pipes"][0]["sections"] = 33
    spec["flowpaths"][0]["pipes"][0]["centerline_m"] = [[0, 0, 0], [99, 0, 0]]
    spec["flowpaths"][1]["pipes"][0]["centerline_m"][0] = [99, 0, 0]
    spec["flowpaths"][2]["pipes"][0]["centerline_m"][0] = [99, 0, 0]

    result = case_compiler.compile_case_spec(spec, verify=_clean_toolkit)

    assert b"NSEGMENT=33" in result.compiled_bytes
    line = next(line for line in result.text.splitlines() if "PIPE LABEL=PIPE_A" in line)
    values = line.split("LSEGMENT=(", 1)[1].split(")", 1)[0].split(",")
    assert values == ["3"] * 33
    assert result.section_count == 44


def test_compile_rejects_output_larger_than_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(case_compiler, "MAX_COMPILED_BYTES", 128)

    with pytest.raises(case_compiler.CaseCompileError, match="output limit"):
        case_compiler.compile_case_spec(SPEC, verify=_clean_toolkit)


def test_validator_or_parser_disagreement_fails_closed() -> None:
    def disagree(_text: str) -> case_compiler.ToolkitVerification:
        return case_compiler.ToolkitVerification(
            clean=False,
            parser_clean=True,
            validator_clean=False,
            diagnostics=("validator rejected candidate",),
        )

    with pytest.raises(case_compiler.CaseCompileError, match="disagreement"):
        case_compiler.compile_case_spec(SPEC, verify=disagree)


def test_renderer_rejects_pvt_delimiter_injection_even_before_toolkit() -> None:
    spec = deepcopy(SPEC)
    spec["pvt_reference"] = 'fluid".tab'

    with pytest.raises((case_compiler.CaseCompileError, ValueError)):
        case_compiler.render_case_spec(spec)


def test_real_toolkit_round_trip_preserves_topology_and_geometry() -> None:
    verification = case_compiler.compile_case_spec(SPEC).validation

    assert verification.clean is True, verification.diagnostics
    assert verification.topology_edges == (
        ("SOURCE_A", "TEE_A", "MAIN"),
        ("TEE_A", "SINK_A", "BRANCH"),
        ("TEE_A", "SINK_B", "BRANCH_B"),
    )
    assert verification.section_count == 21
    assert verification.geometry[0][2:] == (
        (100.0, 0.0, 5.0),
        (160.0, 25.0, 0.0),
        0.08,
        6,
        (10.8653373420044,) * 6,
    )


def test_compile_does_not_expose_or_publish_a_path() -> None:
    result = case_compiler.compile_case_spec(SPEC, verify=_clean_toolkit)
    public = result.to_public_dict()

    assert not hasattr(result, "path")
    assert not hasattr(result, "published")
    assert result.validation.clean is True
    assert public["compiled_hash"] == result.sha256
    assert public["source_mutated"] is False
    assert "/tmp/" not in repr(public)
    assert "C:\\" not in repr(public)


def _ambient_spec() -> dict:
    from case_spec_v2_support import AMBIENT

    return with_v2_inputs(SPEC, AMBIENT) | {"thermal": deepcopy(AMBIENT)}


@pytest.mark.parametrize("model", ["adiabatic", "ambient_h_given"])
def test_real_toolkit_accepts_each_explicit_thermal_model_without_weakened_rules(model: str) -> None:
    # Given: a spec whose thermal choice, fluid label, temperatures and roughness are stated.
    spec = SPEC if model == "adiabatic" else _ambient_spec()

    # When: the real parser and validator (X010 numeric FLUID, X011 HEATTRANSFER) check it.
    result = case_compiler.compile_case_spec(spec)

    # Then: it passes on its own merits, and the round trip carries every stated value.
    assert result.validation.clean is True, result.validation.diagnostics
    assert result.validation.fluid_labels == ("TEST_FLUID",)
    assert result.validation.thermal[0] == model
    assert result.validation.boundaries == (
        ("SINK_A", 1_000_000.0, 30.0), ("SINK_B", 900_000.0, 30.0), ("SOURCE_A", 2_000_000.0, 40.0),
    )
    assert {row[2] for row in result.validation.roughness} == {5e-5}
    text = result.text
    assert 'BRANCH FLUID="TEST_FLUID"' in text and "FLUID=1" not in text
    assert ("TEMPERATURE=ADIABATIC" in text) == (model == "adiabatic")
    assert ("HEATTRANSFER" in text) == (model == "ambient_h_given")
    assert ("CASESPEC_WALL" in text) == (model == "ambient_h_given")


def test_toolkit_still_rejects_numeric_fluid_and_missing_heat_transfer() -> None:
    # Given: the old v1 shape (numeric FLUID, nonadiabatic, no HEATTRANSFER), handcrafted.
    legacy = case_compiler.render_case_spec(SPEC).decode()
    legacy = legacy.replace('FLUID="TEST_FLUID"', "FLUID=1").replace(", TEMPERATURE=ADIABATIC", "")

    # When: the unchanged toolkit validates it.
    verdict = case_compiler.verify_with_toolkit(legacy)

    # Then: X010 and X011 still fail closed; nothing was relaxed to make CaseSpec pass.
    assert verdict.clean is False
    joined = " ".join(verdict.diagnostics)
    assert "X010" in joined and "X011" in joined


def test_compiler_never_invents_a_physical_value() -> None:
    # Given: two specs that differ only in the user's stated roughness and temperature.
    first, second = deepcopy(SPEC), deepcopy(SPEC)
    second["flowpaths"][0]["pipes"][0]["roughness_m"] = 1.5e-4
    second["nodes"][0]["temperature_c"] = 55.5

    # When: both render.
    one = case_compiler.render_case_spec(first).decode()
    two = case_compiler.render_case_spec(second).decode()

    # Then: the stated values, and only those, change the output; no exponent notation leaks.
    assert "ROUGHNESS=0.00015 m" in two and "ROUGHNESS=0.00015 m" not in one
    assert "TEMPERATURE=55.5 C" in two
    assert "e-0" not in one + two


def test_companion_with_another_fluid_label_blocks_the_compile(tmp_path: Path) -> None:
    owner = tmp_path / "owner.genkey"
    owner.write_bytes(b"CASE LABEL=owner\nENDCASE\n")
    (tmp_path / "fluid.tab").write_text('PVTTABLE LABEL = "OTHER_FLUID", PHASE = BOTH\n', encoding="utf-8")

    with pytest.raises(ValueError, match="not the requested fluid label 'TEST_FLUID'"):
        case_compiler.compile_case_spec(SPEC, owner, verify=_clean_toolkit)


def test_companion_without_a_label_blocks_the_compile(tmp_path: Path) -> None:
    owner = tmp_path / "owner.genkey"
    owner.write_bytes(b"CASE LABEL=owner\nENDCASE\n")
    (tmp_path / "fluid.tab").write_text("no label in this table\n", encoding="utf-8")

    with pytest.raises(ValueError, match="declares no PVTTABLE LABEL"):
        case_compiler.compile_case_spec(SPEC, owner, verify=_clean_toolkit)


def test_a_round_trip_disagreement_on_any_stated_value_fails_closed() -> None:
    clean = case_compiler.compile_case_spec(SPEC).validation
    from dataclasses import replace

    for field, value, message in (
        ("fluid_labels", ("WRONG",), "fluid label"),
        ("thermal", ("adiabatic", "extra"), "thermal"),
        ("boundaries", (("SOURCE_A", 1.0, 40.0),), "boundary"),
        ("roughness", (("MAIN", "PIPE_A", 0.5),), "roughness"),
    ):
        with pytest.raises(case_compiler.CaseCompileError, match=message):
            case_compiler.compile_case_spec(SPEC, verify=lambda _text, f=field, v=value: replace(clean, **{f: v}))
