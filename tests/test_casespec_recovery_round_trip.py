"""Byte-exact recovery of compiler features added for beginner re-edit."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from case_spec_v2_support import PVT_TABLE_TEXT
from olga_companion import case_compiler, case_spec, windows_broker, workspace
from olga_companion.agent import tools
from olga_companion.case_spec_recovery import UnsupportedSourceError, recover_case_spec
from olga_companion.case_transactions import plan_case_edits_from_source

FIXTURES = Path(__file__).parent / "fixtures"
OUTPUTS = FIXTURES / "casespec_outputs.json"
SOURCE = FIXTURES / "casespec_source_massflow.json"
VALVE = FIXTURES / "casespec_valve.json"
TAB = FIXTURES / "fluids" / "fluid.tab"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _round_trip(tmp_path: Path, spec: dict):
    source = tmp_path / "case.genkey"
    original = case_compiler.render_case_spec(spec)
    source.write_bytes(original)
    recovered = recover_case_spec(source)
    assert case_compiler.render_case_spec(recovered) == original
    return recovered


def test_closed_inlet_and_source_round_trip(tmp_path: Path) -> None:
    raw = _load(SOURCE)
    raw["nodes"][0] = {"label": "SOURCE", "kind": "closed"}

    recovered = _round_trip(tmp_path, raw)

    inlet = next(node for node in recovered.nodes if node.label == "SOURCE")
    assert inlet.kind == "closed"
    assert recovered.massflow_sources[0].label == "FEED"
    assert recovered.massflow_sources[0].series is None


def test_source_series_round_trip(tmp_path: Path) -> None:
    raw = _load(SOURCE)
    raw["massflow_sources"][0]["series"] = [
        {
            "time_s": 0,
            "mass_flow_kg_s": 0,
            "temperature_c": 15,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
        },
        {
            "time_s": 5,
            "mass_flow_kg_s": 2,
            "temperature_c": 15,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
        },
    ]

    recovered = _round_trip(tmp_path, raw)
    series = recovered.massflow_sources[0].series

    assert series is not None and len(series) == 2
    assert series[0].time_s == 0
    assert series[1].mass_flow_kg_s == 2
    assert series[1].time_s == 5


def test_valve_round_trip_omits_equilibrium_model(tmp_path: Path) -> None:
    recovered = _round_trip(tmp_path, _load(VALVE))
    text = case_compiler.render_case_spec(recovered).decode()

    assert recovered.equipment[0].label == "VALVE_A"
    assert recovered.equipment[0].opening == 1
    assert "SECTIONBOUNDARY=5" in text
    assert "EQUILIBRIUMMODEL" not in text


def test_valve_line_with_equilibrium_model_stays_unrecoverable(tmp_path: Path) -> None:
    source = tmp_path / "case.genkey"
    text = case_compiler.render_case_spec(_load(VALVE)).decode()
    source.write_text(
        text.replace(
            "SECTIONBOUNDARY=5, DIAMETER=0.08 m",
            "SECTIONBOUNDARY=5, EQUILIBRIUMMODEL=FROZEN, DIAMETER=0.08 m",
        ),
        encoding="utf-8",
    )

    with pytest.raises(UnsupportedSourceError):
        recover_case_spec(source)


def test_steady_state_off_without_initial_conditions_does_not_round_trip() -> None:
    raw = _load(OUTPUTS)
    raw["integration"]["steady_state"] = False

    with pytest.raises(ValidationError, match="steady_state_off_requires_initial_conditions"):
        case_compiler.render_case_spec(raw)


def test_stated_mindt_and_dtstart_round_trip(tmp_path: Path) -> None:
    raw = _load(OUTPUTS)
    raw["integration"]["min_dt_s"] = 0.01
    raw["integration"]["dt_start_s"] = 0.5

    recovered = _round_trip(tmp_path, raw)

    assert recovered.integration.min_dt_s == 0.01
    assert recovered.integration.dt_start_s == 0.5


def test_outlet_fractions_round_trip(tmp_path: Path) -> None:
    raw = _load(OUTPUTS)
    for node in raw["nodes"]:
        if node["kind"] == "sink":
            node["gas_fraction"] = 0.2
            node["total_water_fraction"] = 0.8

    recovered = _round_trip(tmp_path, raw)
    sink = next(node for node in recovered.nodes if node.kind == "sink")

    assert sink.gas_fraction == 0.2
    assert sink.total_water_fraction == 0.8


def test_one_outlet_fraction_is_refused(tmp_path: Path) -> None:
    raw = _load(OUTPUTS)
    for node in raw["nodes"]:
        if node["kind"] == "sink":
            del node["total_water_fraction"]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "pressure_node_fractions_required"
    partial = case_compiler.render_case_spec(_load(OUTPUTS)).replace(
        b", TOTALWATERFRACTION=0.35 -", b"", 1
    )
    source = tmp_path / "partial.genkey"
    source.write_bytes(partial)
    with pytest.raises(UnsupportedSourceError, match="phase fraction"):
        recover_case_spec(source)


def test_default_trend_positions_round_trip_the_first_and_last_section(tmp_path: Path) -> None:
    recovered = _round_trip(tmp_path, _load(OUTPUTS))
    text = case_compiler.render_case_spec(recovered).decode()

    assert recovered.trend_positions is None
    assert 'POSITION LABEL="POS_MAIN_1", PIPE=PIPE_A, SECTION=1' in text
    assert 'POSITION LABEL="POS_MAIN", PIPE=PIPE_A, SECTION=10' in text
    assert "TRENDDATA POSITION=(POS_MAIN_1, POS_MAIN)," in text


def test_named_trend_positions_round_trip(tmp_path: Path) -> None:
    raw = _load(OUTPUTS)
    raw["trend_positions"] = [
        {"label": "POS_END", "pipe": "PIPE_A", "section": 10},
        {"label": "POS_MID", "pipe": "PIPE_A", "section": 4},
    ]

    recovered = _round_trip(tmp_path, raw)
    labels = [point.label for point in recovered.trend_positions or ()]

    assert labels == ["POS_MID", "POS_END"]
    assert "POS_MAIN" not in case_compiler.render_case_spec(recovered).decode()


def test_stated_intervals_round_trip(tmp_path: Path) -> None:
    raw = _load(OUTPUTS)
    raw["integration"] = {
        "end_time_s": 60.0,
        "trend_interval_s": 2.0,
        "profile_interval_s": 10.0,
        "output_interval_s": 30.0,
        "max_dt_s": 6.0,
    }

    recovered = _round_trip(tmp_path, raw)

    assert recovered.integration.trend_interval_s == 2
    assert recovered.integration.profile_interval_s == 10
    assert recovered.integration.output_interval_s == 30
    assert recovered.integration.max_dt_s == 6


def test_recovered_closed_inlet_edits_massflow_and_preflights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    shutil.copyfile(TAB, root / "fluid.tab")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    spec = {
        "version": "2",
        "nodes": [
            {"label": "INLET_NODE", "kind": "closed"},
            {
                "label": "OUTLET_NODE",
                "kind": "sink",
                "pressure_pa": 3_000_000.0,
                "temperature_c": 15.0,
                "gas_fraction": 0.15,
                "total_water_fraction": 0.35,
            },
        ],
        "flowpaths": [{
            "label": "PIPELINE",
            "from": "INLET_NODE",
            "to": "OUTLET_NODE",
            "pipes": [{
                "label": "PIPE_1",
                "centerline_m": [[0, 0, 0], [100, 0, 0]],
                "diameter_m": 0.1,
                "roughness_m": 5e-5,
                "sections": 5,
            }],
        }],
        "pvt_reference": "fluid.tab",
        "fluid_label": "FLUID-A",
        "thermal": {"model": "adiabatic"},
        "integration": {"end_time_s": 3600.0},
        "outputs": ["PT", "TM"],
        "massflow_sources": [{
            "label": "FEED",
            "flowpath": "PIPELINE",
            "pipe": "PIPE_1",
            "section": 1,
            "time_s": 0.0,
            "mass_flow_kg_s": 1.0,
            "temperature_c": 20.0,
            "gas_fraction": 0.0,
            "total_water_fraction": 0.0,
        }],
    }
    source = root / "beginner.genkey"
    source.write_bytes(case_compiler.render_case_spec(spec))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    parent = Path("/mnt/c/Users/Woojin/AppData/Local/Temp")
    parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    hold = tempfile.TemporaryDirectory(prefix="olga-c4-broker-", dir=parent)
    cache = Path(hold.name)
    monkeypatch.setattr(windows_broker, "sandbox_root", lambda: cache)
    monkeypatch.setattr(windows_broker, "_e2e_cache_hold", hold, raising=False)

    result = plan_case_edits_from_source(
        source,
        [{
            "op": "set_source_massflow",
            "label": "FEED",
            "mass_flow_kg_s": 2.5,
            "temperature_c": 20.0,
            "gas_fraction": 0.0,
            "total_water_fraction": 0.0,
        }],
        expected_hash=source_hash,
        workspace_root=root,
    )

    assert result.publishable is True, getattr(result, "errors", result)
    assert result.validation.validator_clean is True
    assert b"MASSFLOW=(2.5) kg/s" in result.compiled_bytes
    edited = root / "beginner-edited.genkey"
    edited.write_bytes(result.compiled_bytes)
    workspace.set_active_path(str(edited))
    review = tools.dispatch("genkey_review", {"path": str(edited)})
    detected = tools.dispatch("run_detect", {"source": str(edited)})
    candidates = [
        item for item in detected.get("candidates", [])
        if isinstance(item, dict) and item.get("candidate_id")
    ]
    assert candidates, detected
    runtime = candidates[0]
    preflight = tools.dispatch(
        "simulation_setup",
        {
            "binding": {"kind": "active_case", "source_sha256": review["source_sha256"]},
            "integration": {"end_time_s": 3600},
            "outputs": ["PT", "TM"],
            "runtime": {
                "candidate_id": runtime["candidate_id"],
                "runtime_id": runtime["runtime_id"],
            },
            "timeout_s": 120,
            "output_target": {"relative_dir": "managed-run-sandbox"},
            "context_generation": workspace.context_identity()[1],
        },
    )
    assert preflight["ready"] is True, preflight


def test_massflow_edit_replaces_a_recovered_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _load(SOURCE)
    raw["massflow_sources"][0]["series"] = [
        {
            "time_s": 0,
            "mass_flow_kg_s": 0,
            "temperature_c": 15,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
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
    (tmp_path / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "journal"))

    result = plan_case_edits_from_source(
        source,
        [{
            "op": "set_source_massflow",
            "label": "FEED",
            "mass_flow_kg_s": 3.0,
            "temperature_c": 15.0,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
        }],
        expected_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        workspace_root=tmp_path,
    )

    assert result.publishable is True, getattr(result, "errors", result)
    text = result.compiled_bytes.decode()
    assert "MASSFLOW=(3) kg/s" in text
    assert "TIME=(0, 5)" not in text


def test_recovered_valve_opening_edit_compiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "valve.genkey"
    source.write_bytes(case_compiler.render_case_spec(_load(VALVE)))
    (tmp_path / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "journal"))

    result = plan_case_edits_from_source(
        source,
        [{"op": "set_valve_opening", "label": "VALVE_A", "opening": 0.25}],
        expected_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        workspace_root=tmp_path,
    )

    assert result.publishable is True, getattr(result, "errors", result)
    assert result.validation.validator_clean is True
    assert b"OPENING=0.25" in result.compiled_bytes
    assert b"EQUILIBRIUMMODEL" not in result.compiled_bytes
