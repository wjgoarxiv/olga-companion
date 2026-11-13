from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from olga_companion.case_compiler import render_case_spec
from olga_companion.case_spec_recovery import recover_case_spec
from olga_companion.case_transaction_store import load_transaction
from olga_companion.case_transactions import (
    UnsupportedSourceError,
    plan_case_edits_from_source,
)
from case_spec_v2_support import PVT_TABLE_TEXT, with_v2_inputs


def _spec() -> dict:
    return with_v2_inputs({
        "version": "1",
        "nodes": [
            {"label": "SOURCE", "kind": "source", "pressure_pa": 2_000_000.0},
            {"label": "SINK", "kind": "sink", "pressure_pa": 1_000_000.0},
        ],
        "flowpaths": [{
            "label": "MAIN", "from": "SOURCE", "to": "SINK",
            "pipes": [{
                "label": "PIPE_A", "centerline_m": [[0.0, 0.0, 0.0], [100.0, 0.0, 0.0]],
                "diameter_m": 0.1, "sections": 10,
            }],
        }],
        "pvt_reference": "fluid.tab",
        "integration": {"end_time_s": 3600.0},
        "outputs": ["PT"],
    })


def _branched_spec() -> dict:
    spec = _spec()
    spec["nodes"] = [
        {"label": "SOURCE", "kind": "source", "pressure_pa": 2_000_000.0},
        {"label": "TEE", "kind": "junction"},
        {"label": "SINK_A", "kind": "sink", "pressure_pa": 1_000_000.0},
        {"label": "SINK_B", "kind": "sink", "pressure_pa": 900_000.0},
    ]
    spec["flowpaths"] = [
        {
            "label": "MAIN", "from": "SOURCE", "to": "TEE",
            "pipes": [
                {"label": "P1", "centerline_m": [[0.0, 0.0, 0.0], [50.0, 0.0, 0.0]], "diameter_m": 0.1, "sections": 5},
                {"label": "P2", "centerline_m": [[50.0, 0.0, 0.0], [100.0, 0.0, 5.0]], "diameter_m": 0.1, "sections": 5},
            ],
        },
        {
            "label": "ARM_A", "from": "TEE", "to": "SINK_A",
            "pipes": [{"label": "PA", "centerline_m": [[100.0, 0.0, 5.0], [150.0, 20.0, 0.0]], "diameter_m": 0.08, "sections": 6}],
        },
        {
            "label": "ARM_B", "from": "TEE", "to": "SINK_B",
            "pipes": [{"label": "PB", "centerline_m": [[100.0, 0.0, 5.0], [145.0, -20.0, 2.0]], "diameter_m": 0.06, "sections": 4}],
        },
    ]
    return with_v2_inputs(spec)


def test_compiler_owned_source_is_recovered_without_model_resending_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a byte-exact deterministic CaseSpec compiler artifact.
    source = tmp_path / "compiled.genkey"
    source.write_bytes(render_case_spec(_spec()))
    (tmp_path / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "journal"))

    # When Chat supplies only source identity and ordered edits.
    result = plan_case_edits_from_source(
        source,
        [{"op": "set_integration", "end_time_s": 7200.0}],
        expected_hash=source_hash,
        workspace_root=tmp_path,
        context_generation=3,
    )

    # Then trusted CaseSpec state is recovered and source bytes remain unchanged.
    assert result.publishable is True
    assert b"ENDTIME=7200 s" in result.compiled_bytes
    assert load_transaction(result.transaction_id).source == source.resolve()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash


def test_arbitrary_legacy_source_fails_with_explicit_guidance(tmp_path: Path) -> None:
    # Given a contained GENKEY that was not emitted by the deterministic compiler.
    source = tmp_path / "legacy.genkey"
    source.write_bytes(b"CASE LABEL=owner\nENDCASE\n")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    # When source-only recovery cannot prove an exact CaseSpec round trip.
    result = plan_case_edits_from_source(
        source, [], expected_hash=source_hash, workspace_root=tmp_path,
    )

    # Then no guessed model or owner mutation is produced.
    assert result.publishable is False
    assert result.errors[0].code == "unsupported_operation"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    with pytest.raises(UnsupportedSourceError, match="CaseSpec compiler"):
        recover_case_spec(source)


def test_recovered_source_with_missing_pvt_is_not_publishable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a trusted compiler artifact whose referenced companion is missing.
    source = tmp_path / "compiled.genkey"
    source.write_bytes(render_case_spec(_spec()))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "journal"))

    # When source-only planning performs final contained compilation.
    result = plan_case_edits_from_source(
        source, [], expected_hash=source_hash, workspace_root=tmp_path,
    )

    # Then no unverified PVT transaction becomes publishable or durable.
    assert result.publishable is False
    assert result.errors[0].code == "compile_validation_failed"
    assert "missing" in result.errors[0].message
    assert not (tmp_path / "journal").exists()


def test_branched_multi_pipe_compiler_artifact_recovers_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given the arbitrary branched grammar emitted by CaseSpec v1.
    source = tmp_path / "branched.genkey"
    source.write_bytes(render_case_spec(_branched_spec()))
    (tmp_path / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "journal"))

    # When a pipe on one branch is edited from source identity alone.
    result = plan_case_edits_from_source(
        source,
        [{"op": "set_pipe_sections", "flowpath": "ARM_B", "pipe": "PB", "sections": 8}],
        expected_hash=source_hash,
        workspace_root=tmp_path,
    )

    # Then topology and pipe order survive exact recovery and final toolkit validation.
    assert result.publishable is True
    assert b"TAG=ARM_A" in result.compiled_bytes
    assert b"LABEL=PB" in result.compiled_bytes
    assert b"NSEGMENT=8" in result.compiled_bytes


def _plan(source: Path, workspace: Path, operations: list[dict]):
    return plan_case_edits_from_source(
        source, operations,
        expected_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        workspace_root=workspace,
    )


@pytest.mark.parametrize("thermal_name", ["adiabatic", "ambient"])
def test_each_thermal_model_recovers_exactly_and_edits_keep_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, thermal_name: str
) -> None:
    from case_spec_v2_support import ADIABATIC, AMBIENT

    # Given a compiler artifact for each explicit thermal model, with its matching PVT label.
    thermal = ADIABATIC if thermal_name == "adiabatic" else AMBIENT
    source = tmp_path / "compiled.genkey"
    source.write_bytes(render_case_spec(with_v2_inputs(_spec(), thermal) | {"thermal": thermal}))
    (tmp_path / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    original = source.read_bytes()
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "journal"))

    # When each new typed edit is planned from source identity alone.
    result = _plan(source, tmp_path, [
        {"op": "set_boundary_temperature", "node": "SOURCE", "temperature_c": 55.5},
        {"op": "set_pipe_roughness", "flowpath": "MAIN", "pipe": "PIPE_A", "roughness_m": 0.0001},
    ])

    # Then the edited copy is valid with the stated values; the original bytes are untouched.
    assert result.publishable is True, result.errors
    text = result.compiled_bytes.decode()
    assert "TEMPERATURE=55.5 C" in text and "ROUGHNESS=0.0001 m" in text
    assert {item.path for item in result.semantic_diff} == {
        "nodes.SOURCE.temperature_c", "flowpaths.MAIN.pipes.PIPE_A.roughness_m",
    }
    assert source.read_bytes() == original


def test_thermal_and_fluid_edits_are_typed_and_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from case_spec_v2_support import AMBIENT

    source = tmp_path / "compiled.genkey"
    source.write_bytes(render_case_spec(_spec()))
    (tmp_path / "fluid.tab").write_text('PVTTABLE LABEL = "NEW_FLUID", PHASE = BOTH\n', encoding="utf-8")
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "journal"))

    switched = _plan(source, tmp_path, [
        {"op": "set_fluid", "fluid_label": "NEW_FLUID"},
        {"op": "set_thermal", "thermal": AMBIENT},
    ])
    incomplete = _plan(source, tmp_path, [
        {"op": "set_fluid", "fluid_label": "NEW_FLUID"},
        {"op": "set_thermal", "thermal": {"model": "ambient_h_given", "ambient_temperature_c": 5.0}},
    ])

    assert switched.publishable is True, switched.errors
    assert b'FLUID="NEW_FLUID"' in switched.compiled_bytes and b"HEATTRANSFER" in switched.compiled_bytes
    assert incomplete.publishable is False
    assert incomplete.errors[0].code == "unsupported_operation"


def test_legacy_v1_compiler_artifact_is_classified_not_silently_migrated(tmp_path: Path) -> None:
    # Given bytes the v1 compiler emitted (numeric FLUID, fixed 20 C, invented wall values).
    source = tmp_path / "v1.genkey"
    source.write_text(
        "! Deterministic CaseSpec v1 compilation\n"
        "OPTIONS STEADYSTATE=ON, COMPOSITIONAL=OFF, FLOWMODEL=OLGAHD\n"
        " BRANCH FLUID=1\nENDCASE\n",
        encoding="utf-8",
    )
    original = source.read_bytes()

    # When typed editing is attempted.
    with pytest.raises(UnsupportedSourceError, match="CaseSpec v1.*never solver-valid.*CaseSpec v2"):
        _plan(source, tmp_path, [])

    # Then it is blocked with a reason and left unchanged; arbitrary GENKEY keeps its own message.
    assert source.read_bytes() == original


def test_external_genkey_with_physics_is_never_typed_edited(tmp_path: Path) -> None:
    source = tmp_path / "external.genkey"
    source.write_bytes((Path(__file__).parent / "fixtures" / "fluids" / "case_ok.genkey").read_bytes())
    original = source.read_bytes()

    refused = _plan(source, tmp_path, [{"op": "set_integration", "end_time_s": 10.0}])

    assert refused.publishable is False
    assert refused.errors[0].code == "unit_unchanged"
    assert source.read_bytes() == original
    with pytest.raises(UnsupportedSourceError, match="provenance marker is absent"):
        recover_case_spec(source)


def test_source_free_plan_checks_the_fluid_label_of_the_edited_spec_not_the_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion.case_transactions import case_spec_hash, plan_case_edits

    (tmp_path / "fluid.tab").write_text('PVTTABLE LABEL = "NEW_FLUID", PHASE = BOTH\n', encoding="utf-8")
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "journal"))
    wrong_base = _spec() | {"fluid_label": "OLD_FLUID"}

    fixed = plan_case_edits(wrong_base, [{"op": "set_fluid", "fluid_label": "NEW_FLUID"}],
                            expected_hash=case_spec_hash(wrong_base), workspace_root=tmp_path)
    right_base = _spec() | {"fluid_label": "NEW_FLUID"}
    broken = plan_case_edits(right_base, [{"op": "set_fluid", "fluid_label": "OLD_FLUID"}],
                             expected_hash=case_spec_hash(right_base), workspace_root=tmp_path)

    assert fixed.publishable is True, getattr(fixed, "errors", fixed)
    assert broken.publishable is False and "OLD_FLUID" in broken.errors[0].message
