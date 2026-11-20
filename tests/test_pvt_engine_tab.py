"""Keyword .tab writer: validator, no-overwrite, fills, grid policy."""

from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import pytest

from olga_companion import fluids
from olga_companion.pvt_engine import (
    GridPolicyError,
    UnknownComponentError,
    generate_table,
)
from olga_companion.pvt_engine.errors import OverwriteError

FIXTURE_COLUMNS = [
    "PT", "TM", "ROG", "ROHL", "DROGDP", "DROHLDP", "DROGDT", "DROHLDT", "RS",
    "VISG", "VISHL", "CPG", "CPHL", "HG", "HHL", "TCG", "TCHL", "SIGGHL", "SEG", "SEHL",
]


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    # A dedicated folder: other suites drop marker files into tmp_path itself.
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def validate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    scripts = Path(fluids.fluids_toolkit_status()["toolkit_dir"]) / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    validator = importlib.import_module("tab_validator")

    def run(path: Path) -> dict:
        return validator.TabValidator(str(path)).validate()

    return run


def _small(out_dir: Path, name: str = "neutral.tab", **overrides):
    args = dict(
        path=out_dir / name,
        components=["CO2", "N2"],
        moles=[0.9, 0.1],
        eos="PR",
        pressures_pa=[5e5, 20e5, 60e5],
        temperatures_c=[-30.0, 0.0, 40.0],
        label="NEUTRAL-CO2-N2",
    )
    args.update(overrides)
    return generate_table(**args)


def test_written_table_matches_fixture_columns_and_validates(out_dir: Path, validate) -> None:
    report = _small(out_dir)
    text = (out_dir / "neutral.tab").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == 'PVTTABLE LABEL = "NEUTRAL-CO2-N2",PHASE = TWO,\\'
    assert f"COLUMNS = ( {', '.join(FIXTURE_COLUMNS)} )" in text
    assert "MESHTYPE = STANDARD" in text and "NOPRES" not in text and "NOTEMP" not in text
    for key in ('EOS = "PR Peneloux"', "MOLWEIGHT = (", "DENSITY = (",
                "STDPRESSURE = 1 ATM", "STDTEMPERATURE = 288.15 K",
                "GOR = -999", "GLR = -999", "STDGASDENSITY =", "STDOILDENSITY =",
                "BUBBLEPRESSURES = (", "BUBBLETEMPERATURES = ("):
        assert key in text, key
    assert text.count("PVTTABLE POINT") == 9
    result = validate(out_dir / "neutral.tab")
    assert result["errors"] == [], result["errors"]
    assert report.node_count == 9


def _provenance_block(out_dir: Path) -> str:
    text = (out_dir / "neutral.tab").read_text(encoding="utf-8")
    first, _, rest = text.partition("\n")
    assert first.startswith("PVTTABLE LABEL"), first
    head, _, _ = rest.partition("COMPONENTS")
    assert "!" in head
    return head


def test_provenance_header_names_engine_eos_and_models(out_dir: Path) -> None:
    _small(out_dir)
    head = _provenance_block(out_dir)
    lowered = head.lower()
    for needle in ("pvt_engine", "peng-robinson", "peneloux", "lohrenz", "weinaug", "stiel",
                   "michelsen", "independent table, not multiflash-identical",
                   "binary interaction parameters: all zero"):
        assert needle in lowered, needle


def test_no_overwrite_of_table_or_fill_report(out_dir: Path) -> None:
    target = out_dir / "neutral.tab"
    target.write_text("original", encoding="utf-8")
    with pytest.raises(OverwriteError):
        _small(out_dir)
    assert target.read_text(encoding="utf-8") == "original"
    target.unlink()
    (out_dir / "neutral.fill.json").write_text("{}", encoding="utf-8")
    with pytest.raises(OverwriteError):
        _small(out_dir)
    assert not target.exists()


def test_unknown_component_and_bad_inputs_are_refused_before_writing(out_dir: Path) -> None:
    with pytest.raises(UnknownComponentError):
        _small(out_dir, components=["CO2", "H2O"])
    with pytest.raises(ValueError):
        _small(out_dir, moles=[0.5, 0.4])
    with pytest.raises(ValueError):
        _small(out_dir, eos="CPA")
    with pytest.raises(ValueError):
        _small(out_dir, label="bad label!")
    with pytest.raises(ValueError):
        _small(out_dir, pressures_pa=[5e5, 5e5])
    with pytest.raises(ValueError):
        _small(out_dir, kij={("CO2", "N2"): "x"})
    assert list(out_dir.iterdir()) == []


def test_triple_point_refusal_and_clip_for_co2_rich_fluids(out_dir: Path) -> None:
    with pytest.raises(GridPolicyError) as raised:
        _small(out_dir, components=["CO2"], moles=[1.0], temperatures_c=[-70.0, -20.0, 40.0])
    message = str(raised.value)
    assert "216.59" in message and "5.18" in message and "-70" in message
    assert list(out_dir.iterdir()) == []
    report = _small(out_dir, components=["CO2"], moles=[1.0], temperatures_c=[-70.0, -20.0, 40.0],
                    grid_policy="clip")
    assert report.clipped_temperatures_c == [-70.0]
    text = (out_dir / "neutral.tab").read_text(encoding="utf-8")
    assert "NOTEMP" not in text and "BUBBLEPRESSURES = (" in text


def test_non_co2_rich_fluid_is_not_clipped_by_the_co2_rule(out_dir: Path) -> None:
    report = _small(out_dir, components=["CH4", "C3H8"], moles=[0.5, 0.5],
                    pressures_pa=[5e5, 20e5], temperatures_c=[-50.0, 20.0])
    assert report.clipped_temperatures_c == []


def test_fill_report_is_listed_in_report_sidecar_and_header(out_dir: Path) -> None:
    report = _small(out_dir)
    assert report.fills, "single-phase nodes must report their filled absent phase"
    entry = report.fills[0]
    assert {"i_pressure", "i_temperature", "pressure_pa", "temperature_c", "absent", "columns", "method"} <= set(entry)
    sidecar = json.loads((out_dir / "neutral.fill.json").read_text(encoding="utf-8"))
    assert sidecar["filled_node_count"] == len(report.fills)
    assert sidecar["independent_table_not_multiflash_identical"] is True
    head = _provenance_block(out_dir)
    assert f"filled nodes: {len(report.fills)} of 9" in head.lower()


def test_user_supplied_bip_is_written_and_default_is_zero(out_dir: Path) -> None:
    _small(out_dir, kij={("CO2", "N2"): -0.017})
    head = _provenance_block(out_dir)
    assert "CO2-N2 = -0.017" in head


def test_non_physical_value_is_never_written(out_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from olga_companion.pvt_engine import tab_writer
    from olga_companion.pvt_engine.errors import NonPhysicalValueError

    original = tab_writer.node_properties

    def broken(*args, **kwargs):
        node = original(*args, **kwargs)
        object.__setattr__(node.gas, "rho", -1.0)
        return node

    monkeypatch.setattr(tab_writer, "node_properties", broken)
    with pytest.raises(NonPhysicalValueError):
        _small(out_dir)
    assert list(out_dir.iterdir()) == []


def test_trace_nodes_are_collected(out_dir: Path) -> None:
    report = _small(out_dir, trace_nodes=[(1, 0)])
    assert set(report.traces) == {(1, 0)}
    assert report.traces[(1, 0)]["feed_roots"]


@pytest.mark.parametrize("label,components,moles", [
    ("grid-pure-co2", ["CO2"], [1.0]),
    ("grid-co2-n2-ch4", ["CO2", "N2", "CH4"], [0.95, 0.03, 0.02]),
])
def test_forty_by_forty_grid_passes_validator(out_dir: Path, validate, label, components, moles) -> None:
    pressures = [(1.0 + 99.0 * i / 39) * 1e5 for i in range(40)]
    temperatures = [-50.0 + 100.0 * j / 39 for j in range(40)]
    started = time.perf_counter()
    report = generate_table(out_dir / f"{label}.tab", components, moles, "PR", pressures, temperatures, label)
    elapsed = time.perf_counter() - started
    result = validate(out_dir / f"{label}.tab")
    assert result["errors"] == [], result["errors"][:5]
    assert report.node_count == 1600
    print(f"{label}: {elapsed:.1f} s, fills={len(report.fills)}, warnings={len(result['warnings'])}")
