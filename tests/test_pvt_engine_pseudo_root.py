"""Absent-phase columns come from a pseudo-root, not from a copy of the present phase.

Black-box finding (2026-10-31): where the cubic has a single real root the engine filled the absent phase from
"an extrapolated EOS root", and that root was the present phase's own root, so ROHL = ROG and VISHL = VISG on a
gas-only node. These tests pin the liquid-like (and vapour-like) stand-in, the unchanged present phase, the
fill report, and that the absent-phase density is smooth and monotone across the grid.

The fluid is neutral: CO2 0.9 / C3H8 0.1, Peng-Robinson.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from olga_companion import fluids
from olga_companion.pvt_engine import CubicEOS, generate_table, node_properties

Z = [0.9, 0.1]
BAR = 1e5


@pytest.fixture(scope="module")
def eos() -> CubicEOS:
    return CubicEOS("PR", ["CO2", "C3H8"])


def _node(eos: CubicEOS, t_c: float, p_bar: float):
    return node_properties(eos, t_c + 273.15, p_bar * BAR, Z)


# ------------------------------------------------------------ gas-only node

@pytest.mark.parametrize("t_c", [20.0, 30.0])
def test_gas_only_node_absent_liquid_is_liquid_like(eos: CubicEOS, t_c: float) -> None:
    node = _node(eos, t_c, 20.0)
    assert node.n_phases == 1 and node.rs == 1.0
    gas, liq = node.gas, node.liquid
    assert liq.rho > 300.0, liq.rho
    assert liq.rho > 5.0 * gas.rho
    assert liq.mu > 2.0 * gas.mu
    assert liq.k > gas.k
    assert liq.cp > gas.cp
    assert liq.h < gas.h and liq.s < gas.s
    assert liq.drho_dp > 0.0 > liq.drho_dt


def test_gas_only_node_is_no_longer_a_copy_of_the_gas_columns(eos: CubicEOS) -> None:
    node = _node(eos, 20.0, 20.0)
    for name in ("rho", "mu", "cp", "h", "s", "k", "drho_dp", "drho_dt"):
        assert getattr(node.liquid, name) != getattr(node.gas, name), name


def test_fill_report_marks_the_pseudo_root_extrapolation(eos: CubicEOS) -> None:
    node = _node(eos, 20.0, 20.0)
    assert len(node.fills) == 1
    fill = node.fills[0]
    assert fill["absent"] == "liquid"
    assert fill["method"] == "single_root"
    assert fill["extrapolation"] == "pseudo-root extrapolation"
    assert "ROHL" in fill["columns"] and "VISHL" in fill["columns"]


# ---------------------------------------------------------- liquid-only node

def test_liquid_only_node_absent_gas_is_gas_like(eos: CubicEOS) -> None:
    node = _node(eos, -20.0, 200.0)
    assert node.n_phases == 1 and node.rs == 0.0
    gas, liq = node.gas, node.liquid
    assert 0.0 < gas.rho < 0.5 * liq.rho, (gas.rho, liq.rho)
    assert gas.mu < 0.5 * liq.mu
    assert gas.k < liq.k
    assert gas.h > liq.h
    assert gas.drho_dp > 0.0 > gas.drho_dt
    fill = node.fills[0]
    assert fill["absent"] == "gas" and fill["extrapolation"] == "pseudo-root extrapolation"
    assert "ROG" in fill["columns"] and "VISG" in fill["columns"]


# ------------------------------------------------ present phase is unchanged

def test_present_phase_values_are_unchanged(eos: CubicEOS) -> None:
    # Values taken from the engine before the pseudo-root change (gas-only and liquid-only nodes).
    gas = _node(eos, 20.0, 20.0).gas
    assert gas.rho == pytest.approx(42.10, rel=2e-3)
    assert gas.mu == pytest.approx(1.497e-5, rel=2e-3)
    assert gas.h == pytest.approx(-28859.8, rel=2e-3)
    assert gas.cp == pytest.approx(1091.3, rel=2e-3)
    assert gas.k == pytest.approx(0.0195, rel=5e-3)
    liq = _node(eos, -20.0, 200.0).liquid
    assert liq.rho == pytest.approx(1006.37, rel=2e-3)
    assert liq.mu == pytest.approx(1.538e-4, rel=2e-3)
    assert liq.h == pytest.approx(-361724.3, rel=2e-3)
    assert liq.cp == pytest.approx(1815.4, rel=2e-3)


# ----------------------------------------------- smooth and monotone on a grid

P_GRID = [5.0, 10.0, 15.0, 20.0, 30.0, 40.0]
T_GRID = [float(t) for t in range(-10, 71, 5)]
# The stand-in reaches its critical-volume plateau with a square-root approach, so the steepest 5 K step is
# about 20 %; the old copy jumped by a factor of 10 at the same place.
MAX_NEIGHBOUR_STEP = 0.25


def _single_phase_column(eos: CubicEOS, p_bar: float, kind_present: str, absent_attr: str) -> list[tuple[float, float]]:
    out = []
    for t_c in T_GRID:
        node = _node(eos, t_c, p_bar)
        present_gas = node.n_phases == 1 and node.rs == 1.0
        present_liq = node.n_phases == 1 and node.rs == 0.0
        if (kind_present == "gas" and present_gas) or (kind_present == "liquid" and present_liq):
            out.append((t_c, getattr(getattr(node, absent_attr), "rho")))
    return out


def test_absent_liquid_density_is_monotone_and_smooth_along_temperature(eos: CubicEOS) -> None:
    checked = 0
    for p_bar in P_GRID:
        column = _single_phase_column(eos, p_bar, "gas", "liquid")
        for (t0, r0), (t1, r1) in zip(column, column[1:]):
            assert r1 <= r0 * (1.0 + 1e-9), (p_bar, t0, t1, r0, r1)  # a liquid-like density never rises with T
            assert abs(r1 - r0) / r0 < MAX_NEIGHBOUR_STEP, (p_bar, t0, t1, r0, r1)
            checked += 1
    assert checked >= 20


def test_absent_liquid_density_is_monotone_and_smooth_along_pressure(eos: CubicEOS) -> None:
    for t_c in (10.0, 15.0, 20.0, 25.0, 30.0):
        previous = None
        for step in range(1, 61):
            p_bar = 1.0 + 1.0 * step
            node = _node(eos, t_c, p_bar)
            if not (node.n_phases == 1 and node.rs == 1.0):
                previous = None
                continue
            rho = node.liquid.rho
            if previous is not None:
                assert rho >= previous * (1.0 - 1e-9), (t_c, p_bar, previous, rho)
                assert abs(rho - previous) / previous < 0.06, (t_c, p_bar, previous, rho)
            previous = rho


def test_absent_gas_density_is_gas_like_and_smooth_on_the_liquid_side(eos: CubicEOS) -> None:
    checked = 0
    for p_bar in (80.0, 120.0, 200.0, 300.0):
        column = _single_phase_column(eos, p_bar, "liquid", "gas")
        for (t0, r0), (t1, r1) in zip(column, column[1:]):
            assert abs(r1 - r0) / r0 < MAX_NEIGHBOUR_STEP, (p_bar, t0, t1, r0, r1)
            checked += 1
        for t_c in (t for t, _ in column):
            node = _node(eos, t_c, p_bar)
            assert node.gas.rho < node.liquid.rho
    assert checked >= 15


def test_absent_phases_meet_at_the_critical_volume_when_no_phase_split_exists(eos: CubicEOS) -> None:
    # Far above the mixture's critical temperature there is only one fluid: both stand-ins sit at the EOS critical volume.
    hot = node_properties(eos, 450.0, 20.0 * BAR, Z)
    assert hot.n_phases == 1
    other = hot.liquid if hot.rs == 1.0 else hot.gas
    assert other.rho > 0.0 and other.rho != (hot.gas if hot.rs == 1.0 else hot.liquid).rho
    v_liq = eos.pseudo_volume(450.0, Z, "liquid")
    v_gas = eos.pseudo_volume(450.0, Z, "gas")
    assert v_liq == pytest.approx(v_gas, rel=1e-9)
    assert v_liq == pytest.approx(eos.vc_over_b * eos.mix(450.0, Z).b, rel=1e-9)


def test_pseudo_volumes_bracket_the_critical_volume_at_every_temperature(eos: CubicEOS) -> None:
    for t_c in range(-50, 220, 10):
        T = t_c + 273.15
        b = eos.mix(T, Z).b
        v_liq = eos.pseudo_volume(T, Z, "liquid")
        v_gas = eos.pseudo_volume(T, Z, "gas")
        assert b < v_liq <= eos.vc_over_b * b * (1 + 1e-9) <= v_gas * (1 + 1e-9), (t_c, v_liq, v_gas)


# --------------------------------------------------- every supported EOS works

@pytest.mark.parametrize("model", ["PR", "PR78", "SRK"])
def test_every_supported_eos_gives_distinct_positive_absent_columns(model: str) -> None:
    eos = CubicEOS(model, ["CO2", "C3H8"])
    node = node_properties(eos, 293.15, 20.0 * BAR, Z)
    assert node.liquid.rho > 5.0 * node.gas.rho
    assert min(node.liquid.mu, node.liquid.cp, node.liquid.k) > 0.0


# ----------------------------------------------------------- table and validator

@pytest.fixture
def validate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    scripts = Path(fluids.fluids_toolkit_status()["toolkit_dir"]) / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    validator = importlib.import_module("tab_validator")

    def run(path: Path) -> dict:
        return validator.TabValidator(str(path)).validate()

    return run


def test_written_table_has_liquid_like_absent_columns_and_validates(tmp_path: Path, validate) -> None:
    out = tmp_path / "out"
    out.mkdir()
    pressures = [10e5, 20e5, 40e5, 120e5, 200e5]
    temps = [-20.0, 10.0, 20.0, 30.0, 40.0]
    report = generate_table(
        path=out / "neutral.tab", components=["CO2", "C3H8"], moles=Z, eos="PR",
        pressures_pa=pressures, temperatures_c=temps, label="NEUTRAL-CO2-C3H8",
    )
    result = validate(out / "neutral.tab")
    assert result["errors"] == [], result["errors"]
    text = (out / "neutral.tab").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("PVTTABLE POINT")]
    columns = ("PT", "TM", "ROG", "ROHL", "DROGDP", "DROHLDP", "DROGDT", "DROHLDT", "RS",
               "VISG", "VISHL", "CPG", "CPHL", "HG", "HHL", "TCG", "TCHL", "SIGGHL", "SEG", "SEHL")
    by_node = {}
    for row in rows:
        values = [float(v) for v in row.split("(", 1)[1].rsplit(")", 1)[0].split(",")]
        by_node[(values[0], values[1])] = dict(zip(columns, values))
    gas_only = by_node[(20e5, 20.0)]
    assert gas_only["RS"] == 1.0
    assert gas_only["ROHL"] > 300.0 and gas_only["VISHL"] > gas_only["VISG"]
    liquid_only = by_node[(200e5, -20.0)]
    assert liquid_only["RS"] == 0.0 and liquid_only["ROG"] < liquid_only["ROHL"]
    assert report.fills and all(f["extrapolation"] == "pseudo-root extrapolation" for f in report.fills
                                if f["method"] in ("single_root", "metastable_root_limited"))
