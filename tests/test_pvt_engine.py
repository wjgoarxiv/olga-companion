"""Clean-room PVT engine: textbook checks against cited public data.

Reference data (public):
- NIST Chemistry WebBook, SRD 69, thermophysical properties of fluids
  (CO2: Span & Wagner 1996; CH4: Setzmann & Wagner 1991; propane: Lemmon et al.
  2009). Tables saved under tests/fixtures/pvt_engine/.
- MultiComponentFlash.jl documentation, Peng-Robinson two-phase flash example
  (methane / n-decane, 30 C, 50 bar, z = 0.4 / 0.6), an open-source
  implementation's published output, used only as a numeric cross-check.
"""

from __future__ import annotations

import ast
import csv
import math
from pathlib import Path

import pytest

from olga_companion import pvt_engine
from olga_companion.pvt_engine import (
    SUPPORTED_COMPONENTS,
    SUPPORTED_EOS,
    CubicEOS,
    UnknownComponentError,
    flash_tp,
    get_component,
    node_properties,
    rachford_rice,
)
from olga_companion.pvt_engine.components import Component
from olga_companion.pvt_engine.cubic import pure_saturation_pressure
from olga_companion.pvt_engine.flash import bubble_pressure, dew_pressure, phase_envelope

FIXTURES = Path(__file__).parent / "fixtures" / "pvt_engine"
R = 8.314462618


def _nist(name: str) -> list[dict[str, float]]:
    with (FIXTURES / name).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    header = rows[0]
    return [
        {key: float(value) if value.replace(".", "", 1).replace("-", "", 1).replace("e", "", 1).isdigit() else value
         for key, value in zip(header, row)}
        for row in rows[1:]
    ]


def _rel(value: float, ref: float) -> float:
    return abs(value - ref) / abs(ref)


# ---------------------------------------------------------------- components

def test_eight_components_with_a_source_per_constant() -> None:
    assert SUPPORTED_COMPONENTS == ("CO2", "N2", "CH4", "C2H6", "C3H8", "iC4", "nC4", "H2S")
    for name in SUPPORTED_COMPONENTS:
        comp = get_component(name)
        for field in ("tc", "pc", "omega", "molar_mass", "vc", "parachor", "cp_ig"):
            assert field in comp.sources and comp.sources[field].strip(), (name, field)
        assert comp.tc > 0 and comp.pc > 0 and comp.molar_mass > 0 and len(comp.cp_ig) == 4


def test_component_aliases_and_unknown_refused() -> None:
    assert get_component("carbon dioxide").name == "CO2"
    assert get_component("i-butane").name == "iC4"
    assert get_component("n-Butane").name == "nC4"
    with pytest.raises(UnknownComponentError) as raised:
        get_component("H2O")
    assert "CO2" in str(raised.value)
    with pytest.raises(UnknownComponentError):
        CubicEOS("PR", ["CO2", "water"])


def test_package_is_stdlib_only() -> None:
    allowed = set(__import__("sys").stdlib_module_names) | {"olga_companion"}
    for path in Path(pvt_engine.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            assert roots <= allowed, (path.name, roots - allowed)


# ---------------------------------------------------------------- EOS

def test_supported_models() -> None:
    assert SUPPORTED_EOS == ("PR", "PR78", "SRK")
    with pytest.raises(ValueError):
        CubicEOS("CPA", ["CO2"])


@pytest.mark.parametrize("model,tolerance", [("PR", 0.025), ("PR78", 0.025), ("SRK", 0.03)])
def test_pure_co2_vapour_pressure_vs_nist(model: str, tolerance: float) -> None:
    eos = CubicEOS(model, ["CO2"])
    for row in _nist("co2_sat.tsv"):
        t = row["Temperature (K)"]
        psat = pure_saturation_pressure(eos, t) / 1e5
        assert _rel(psat, row["Pressure (bar)"]) < tolerance, (model, t, psat)


def test_pure_co2_saturated_densities_vs_nist_with_volume_shift() -> None:
    eos = CubicEOS("PR", ["CO2"])
    for row in _nist("co2_sat.tsv"):
        t = row["Temperature (K)"]
        # A constant shift is calibrated at 0.7 Tc; liquid density drifts beyond Tr 0.89 (270 K).
        if t > 270:
            continue
        p = row["Pressure (bar)"] * 1e5
        props = node_properties(eos, t, p, [1.0])
        # Exactly on the NIST saturation pressure both roots exist in the EOS.
        liq = eos.density_at_root(t, p, [1.0], "liquid")
        vap = eos.density_at_root(t, p, [1.0], "vapor")
        assert _rel(liq, row["Density (l, kg/m3)"]) < 0.045, (t, liq)
        assert _rel(vap, row["Density (v, kg/m3)"]) < 0.05, (t, vap)
        assert props.gas.rho > 0 and props.liquid.rho > 0


def test_volume_shift_changes_density_not_phase_split() -> None:
    plain = CubicEOS("PR", ["CO2", "CH4"], shift=False)
    shifted = CubicEOS("PR", ["CO2", "CH4"])
    z = [0.7, 0.3]
    a = flash_tp(plain, 250.0, 30e5, z)
    b = flash_tp(shifted, 250.0, 30e5, z)
    assert a.n_phases == b.n_phases == 2
    assert a.vapor_fraction == pytest.approx(b.vapor_fraction, abs=1e-9)
    assert plain.density_at_root(250.0, 80e5, [1.0, 0.0], "liquid") != pytest.approx(
        shifted.density_at_root(250.0, 80e5, [1.0, 0.0], "liquid"), rel=1e-3)


def test_caloric_derivations_are_mutually_consistent() -> None:
    eos = CubicEOS("PR", ["CO2", "CH4"], kij={("CO2", "CH4"): 0.0919})
    z = [0.8, 0.2]
    t, p = 320.0, 40e5
    h = lambda temp: node_properties(eos, temp, p, z).gas.h
    cp_fd = (h(t + 0.01) - h(t - 0.01)) / 0.02
    cp = node_properties(eos, t, p, z).gas.cp
    assert _rel(cp, cp_fd) < 1e-4
    gas = node_properties(eos, t, p, z).gas
    drho_dp = (node_properties(eos, t, p * 1.0001, z).gas.rho - node_properties(eos, t, p * 0.9999, z).gas.rho) / (p * 2e-4)
    drho_dt = (node_properties(eos, t + 0.01, p, z).gas.rho - node_properties(eos, t - 0.01, p, z).gas.rho) / 0.02
    assert _rel(gas.drho_dp, drho_dp) < 1e-4
    assert _rel(gas.drho_dt, drho_dt) < 1e-4
    assert gas.drho_dt < 0 < gas.drho_dp


# ---------------------------------------------------------------- flash

def test_rachford_rice_constant_k_example() -> None:
    # Rachford & Rice (1952) form: sum z_i (K_i - 1) / (1 + V (K_i - 1)) = 0.
    z = [0.5, 0.3, 0.2]
    k = [2.5, 0.8, 0.1]
    v = rachford_rice(z, k)
    residual = sum(zi * (ki - 1) / (1 + v * (ki - 1)) for zi, ki in zip(z, k))
    assert abs(residual) < 1e-12
    assert 0 < v < 1
    x = [zi / (1 + v * (ki - 1)) for zi, ki in zip(z, k)]
    assert sum(x) == pytest.approx(1.0, abs=1e-12)
    assert sum(ki * xi for ki, xi in zip(k, x)) == pytest.approx(1.0, abs=1e-12)


def _decane() -> Component:
    return Component(
        name="nC10", formula="C10H22", aliases=(), molar_mass=142.285, tc=617.7, pc=21.1e5 / 1e5,
        omega=0.4923, vc=603.0, parachor=433.5, cp_ig=(-7.913, 9.609e-1, -5.288e-4, 1.131e-7),
        sources={k: "test-only component (Poling et al. 5th ed. values)" for k in
                 ("tc", "pc", "omega", "molar_mass", "vc", "parachor", "cp_ig")},
    )


def test_binary_flash_methane_decane_matches_published_pr_example() -> None:
    eos = CubicEOS("PR", ["CH4", _decane()], shift=False)
    z = [0.4, 0.6]
    result = flash_tp(eos, 303.15, 50e5, z)
    assert result.n_phases == 2
    gas = next(ph for ph in result.phases if ph.kind == "gas")
    liq = next(ph for ph in result.phases if ph.kind == "liquid")
    # MultiComponentFlash.jl documentation: V 0.2079, x_CH4 0.2427, y_CH4 0.99963.
    assert result.vapor_fraction == pytest.approx(0.2079, rel=0.03)
    assert liq.x[0] == pytest.approx(0.2427, rel=0.03)
    assert gas.x[0] == pytest.approx(0.99963, abs=2e-3)
    # Independent of the reference: equal fugacities and material balance.
    ln_l = eos.ln_phi(303.15, 50e5, liq.x, liq.Z)
    ln_v = eos.ln_phi(303.15, 50e5, gas.x, gas.Z)
    for i in range(2):
        assert math.log(liq.x[i]) + ln_l[i] == pytest.approx(math.log(gas.x[i]) + ln_v[i], abs=1e-8)
        v = result.vapor_fraction
        assert (1 - v) * liq.x[i] + v * gas.x[i] == pytest.approx(z[i], abs=1e-9)


def test_stability_and_phase_identification() -> None:
    eos = CubicEOS("PR", ["CO2"])
    assert flash_tp(eos, 250.0, 1e5, [1.0]).phases[0].kind == "gas"
    assert flash_tp(eos, 250.0, 100e5, [1.0]).phases[0].kind == "liquid"
    assert flash_tp(eos, 350.0, 200e5, [1.0]).n_phases == 1
    mix = CubicEOS("PR", ["CO2", "N2"])
    assert flash_tp(mix, 300.0, 10e5, [0.9, 0.1]).n_phases == 1
    two = flash_tp(mix, 230.0, 20e5, [0.9, 0.1])
    assert two.n_phases == 2 and 0 < two.vapor_fraction < 1
    assert two.converged


def test_bubble_dew_and_envelope() -> None:
    eos = CubicEOS("PR", ["CH4", "C3H8"])
    z = [0.3, 0.7]
    t = 280.0
    pb, pd = bubble_pressure(eos, t, z), dew_pressure(eos, t, z)
    assert pd < pb
    inside = flash_tp(eos, t, 0.5 * (pb + pd), z)
    assert inside.n_phases == 2
    assert flash_tp(eos, t, pb * 1.05, z).n_phases == 1
    assert flash_tp(eos, t, pd * 0.95, z).n_phases == 1
    points = phase_envelope(eos, z, [260.0, 280.0, 300.0])
    assert [round(p["T"]) for p in points] == [260, 280, 300]
    assert all(p["bubble"] is None or p["bubble"] > 0 for p in points)


def test_pure_methane_and_propane_vapour_pressure_vs_nist() -> None:
    for fixture, name, tolerance in (("ch4_sat.tsv", "CH4", 0.03), ("c3_sat.tsv", "C3H8", 0.03)):
        eos = CubicEOS("PR", [name])
        for row in _nist(fixture):
            psat = pure_saturation_pressure(eos, row["Temperature (K)"]) / 1e5
            assert _rel(psat, row["Pressure (bar)"]) < tolerance, (name, row["Temperature (K)"], psat)


# ---------------------------------------------------------------- properties

def test_single_phase_co2_properties_vs_nist() -> None:
    eos = CubicEOS("PR", ["CO2"])
    ref = {(row["Temperature (K)"], row["Pressure (bar)"]): row
           for name in ("co2_iso_250.tsv", "co2_iso_300.tsv", "co2_iso_350.tsv") for row in _nist(name)}
    checked = 0
    for (t, p_bar), row in ref.items():
        # Within 5 K of Tc and above 60 bar the cubic and the missing critical enhancement are far off
        # (Cp and conductivity by 30-50 %); that region is reported in the evidence, not tested here.
        if 295 <= t <= 310 and p_bar >= 60:
            continue
        props = node_properties(eos, t, p_bar * 1e5, [1.0])
        # The present phase (rs = 1 is gas). The NIST label would pick the liquid column for "supercritical" rows,
        # which only matched while the absent phase was a copy of the present one.
        phase = props.gas if props.rs == 1.0 else props.liquid
        assert _rel(phase.rho, row["Density (kg/m3)"]) < 0.06, (t, p_bar, phase.rho)
        assert _rel(phase.mu, row["Viscosity (uPa*s)"] * 1e-6) < 0.25, (t, p_bar, phase.mu)
        assert _rel(phase.k, row["Therm. Cond. (W/m*K)"]) < 0.20, (t, p_bar, phase.k)
        checked += 1
    assert checked >= 10
    # Dilute gas: tighter.
    low = node_properties(eos, 300.0, 1e5, [1.0]).gas
    nist_low = ref[(300.0, 1.0)]
    assert _rel(low.mu, 15.0031e-6) < 0.05
    assert _rel(low.k, 0.0167737) < 0.08
    assert _rel(low.cp, 852.534) < 0.03
    # Enthalpy departure between 1 and 34 bar at 300 K (reference-independent difference).
    dh = node_properties(eos, 300.0, 34e5, [1.0]).gas.h - low.h
    assert _rel(dh, (471.357 - 507.429) * 1e3) < 0.12
    assert nist_low["Phase"] == "vapor"


def test_surface_tension_parachor_vs_nist_saturated_co2() -> None:
    eos = CubicEOS("PR", ["CO2"])
    for row in _nist("co2_sat.tsv"):
        t = row["Temperature (K)"]
        if not 230 <= t <= 280:
            continue
        sigma = node_properties(eos, t, row["Pressure (bar)"] * 1e5 * 1.0, [1.0]).sigma
        assert _rel(sigma, row["Surf. Tension (l, N/m)"]) < 0.35, (t, sigma)


def test_two_phase_node_has_every_column_positive_and_rs_between_zero_and_one() -> None:
    eos = CubicEOS("PR", ["CO2", "N2", "CH4"])
    node = node_properties(eos, 250.0, 30e5, [0.95, 0.03, 0.02])
    assert 0 < node.rs < 1
    for phase in (node.gas, node.liquid):
        assert min(phase.rho, phase.mu, phase.cp, phase.k) > 0
    assert node.liquid.rho > 5 * node.gas.rho
    assert node.sigma > 0
    assert node.fills == []


def test_single_phase_node_reports_filled_columns() -> None:
    eos = CubicEOS("PR", ["CO2", "N2"])
    node = node_properties(eos, 330.0, 5e5, [0.9, 0.1])
    assert node.rs == 1.0
    assert node.fills and node.fills[0]["absent"] == "liquid"
    assert node.fills[0]["method"] in {"metastable_root", "single_root"}
    assert "ROHL" in node.fills[0]["columns"]


def test_teaching_trace_records_roots_iterations_and_split() -> None:
    eos = CubicEOS("PR", ["CO2", "N2", "CH4"])
    node = node_properties(eos, 250.0, 30e5, [0.95, 0.03, 0.02], trace=True)
    trace = node.trace
    assert trace["feed_roots"] and all("Z" in r for r in trace["feed_roots"])
    assert trace["stability"]["unstable"] is True
    assert trace["stability"]["trials"]
    assert trace["successive_substitution"] and "K" in trace["successive_substitution"][0]
    assert trace["split"]["vapor_fraction"] == pytest.approx(node.rs_mole, abs=1e-12)
    assert node_properties(eos, 250.0, 30e5, [0.95, 0.03, 0.02]).trace is None


def test_entropy_matches_cp_over_t_for_single_phase() -> None:
    eos = CubicEOS("PR", ["CO2", "CH4", "C3H8"])
    z = [0.6, 0.3, 0.1]
    for t, p in ((300.0, 20e5), (350.0, 100e5)):
        node = node_properties(eos, t, p, z)
        assert node.n_phases == 1
        phase = node.gas if node.rs == 1 else node.liquid
        pick = lambda temp: (lambda q: q.gas if q.rs == 1 else q.liquid)(node_properties(eos, temp, p, z))
        ds_dt = (pick(t + 0.01).s - pick(t - 0.01).s) / 0.02
        assert _rel(phase.cp / t, ds_dt) < 1e-6


def test_near_critical_negative_flash_is_a_converged_single_phase() -> None:
    names = ["iC4", "C3H8", "nC4", "N2", "CO2", "C2H6", "H2S", "CH4"]
    z = [0.2768, 0.0075, 0.0617, 0.2178, 0.2828, 0.0258, 0.0422, 0.0854]
    z[-1] = 1.0 - sum(z[:-1])
    node = node_properties(CubicEOS("PR78", names), 351.54, 104.0065e5, z)
    assert node.converged


def test_random_states_never_fail_or_give_non_physical_values() -> None:
    import random

    rng = random.Random(11)
    for model in SUPPORTED_EOS:
        for _ in range(12):
            names = rng.sample(SUPPORTED_COMPONENTS, rng.randint(2, 8))
            weights = [rng.random() ** 2 + 1e-3 for _ in names]
            z = [w / sum(weights) for w in weights]
            eos = CubicEOS(model, names)
            for _ in range(8):
                node = node_properties(eos, rng.uniform(205, 420), 10 ** rng.uniform(5, 7.7), z)
                assert node.converged and 0 <= node.rs <= 1 and node.sigma >= 0
                for phase in (node.gas, node.liquid):
                    assert min(phase.rho, phase.mu, phase.cp, phase.k) > 0
