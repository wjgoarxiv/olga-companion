"""Per-node phase properties: density and derivatives, transport, caloric, filled absent phases.

Caloric properties: ideal-gas Cp polynomial plus cubic-EOS departure functions (untranslated volume).
Reference state: each pure component ideal gas, H = 0 and S = 0 at 298.15 K and 101325 Pa;
ideal mixing entropy is included.
Derivatives of density are at constant phase composition.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from . import transport
from .cubic import R, CubicEOS
from .errors import UnsupportedStateError
from .flash import FlashResult, _normalise, flash_tp

T_MIN, T_MAX = 200.0, 500.0
P_MIN, P_MAX = 1e3, 1.5e8
T_REF, P_REF = 298.15, 101325.0

PSEUDO_ROOT_LABEL = "pseudo-root extrapolation"

GAS_COLUMNS = ("ROG", "DROGDP", "DROGDT", "VISG", "CPG", "HG", "TCG", "SEG")
LIQUID_COLUMNS = ("ROHL", "DROHLDP", "DROHLDT", "VISHL", "CPHL", "HHL", "TCHL", "SEHL")


@dataclass(frozen=True)
class PhaseProps:
    kind: str
    x: tuple[float, ...]
    Z: float
    molar_mass: float  # kg/mol
    rho: float  # kg/m3
    drho_dp: float  # kg/m3/Pa
    drho_dt: float  # kg/m3/K
    mu: float  # Pa s
    cp: float  # J/kg/K
    h: float  # J/kg
    s: float  # J/kg/K
    k: float  # W/m/K


@dataclass
class NodeProperties:
    gas: PhaseProps
    liquid: PhaseProps
    rs: float  # gas mass fraction
    rs_mole: float  # gas mole fraction
    sigma: float  # N/m
    n_phases: int
    converged: bool
    fills: list[dict] = field(default_factory=list)
    trace: dict | None = None


def _ideal_enthalpy_entropy(comp, T: float) -> tuple[float, float]:
    a, b, c, d = comp.cp_ig
    h = a * (T - T_REF) + b / 2 * (T ** 2 - T_REF ** 2) + c / 3 * (T ** 3 - T_REF ** 3) + d / 4 * (T ** 4 - T_REF ** 4)
    s = a * math.log(T / T_REF) + b * (T - T_REF) + c / 2 * (T ** 2 - T_REF ** 2) + d / 3 * (T ** 3 - T_REF ** 3)
    return h, s


def phase_properties(eos: CubicEOS, T: float, P: float, x: Sequence[float], Z: float, kind: str) -> PhaseProps:
    n = eos.n
    m = eos.mix(T, x)
    mw = eos.molar_mass(x)
    v_eos = Z * R * T / P
    v = v_eos - m.c
    if v <= 0.0:
        raise UnsupportedStateError(f"Translated molar volume is not positive at {T:g} K, {P:g} Pa.")
    rho = mw / v
    dpdv, dpdt = eos.pressure_derivatives(T, v_eos, m)
    dv_dp = 1.0 / dpdv
    dv_dt = -dpdt / dpdv
    drho_dp = -rho * rho / mw * dv_dp
    drho_dt = -rho * rho / mw * dv_dt

    sd, u = eos.sqrt_delta, eos.u
    integral = math.log((2.0 * v_eos + m.b * (u + sd)) / (2.0 * v_eos + m.b * (u - sd))) / (m.b * sd)
    h_res = R * T * (Z - 1.0) + (T * m.a1 - m.a) * integral
    ln_phi = eos.ln_phi(T, P, x, Z, m)
    g_res = R * T * sum(xi * lp for xi, lp in zip(x, ln_phi))
    s_res = (h_res - g_res) / T
    cp0 = h0 = s0 = 0.0
    for xi, comp in zip(x, eos.components):
        if xi <= 0.0:
            continue
        hi, si = _ideal_enthalpy_entropy(comp, T)
        cp0 += xi * transport.cp_ideal(comp, T)
        h0 += xi * hi
        s0 += xi * (si - R * math.log(xi))
    s0 -= R * math.log(P / P_REF)
    cv = cp0 - R + T * m.a2 * integral
    cp = cv + T * dpdt ** 2 / (-dpdv)
    molar_density = 1.0 / v
    comps = eos.components
    return PhaseProps(
        kind=kind, x=tuple(x), Z=Z, molar_mass=mw, rho=rho, drho_dp=drho_dp, drho_dt=drho_dt,
        mu=transport.viscosity_lbc(comps, x, T, molar_density),
        cp=cp / mw, h=(h0 + h_res) / mw, s=(s0 + s_res) / mw,
        k=transport.thermal_conductivity(comps, x, T, molar_density),
    )


def _molar_density(eos: CubicEOS, T: float, P: float, x: Sequence[float], Z: float) -> float:
    return 1.0 / (Z * R * T / P - eos.mix(T, x).c)


def _pseudo_phase(eos: CubicEOS, T: float, x: Sequence[float], kind: str) -> PhaseProps:
    """Properties of the liquid-like or vapour-like pseudo-root of the feed at ``T``.

    The pseudo-root is a real, stable EOS state (see ``CubicEOS.pseudo_volume``) at the pressure the EOS gives
    for its volume, so density, derivatives, viscosity, Cp, H, S and conductivity are those of that phase
    there, with no formula of their own. The values do not follow the node pressure.
    """
    m = eos.mix(T, x)
    v = eos.pseudo_volume(T, x, kind, m)
    p_state = eos.pressure(T, v, m)
    return phase_properties(eos, T, p_state, x, p_state * v / (R * T), kind)


def node_properties(eos: CubicEOS, T: float, P: float, z: Sequence[float], trace: bool = False) -> NodeProperties:
    """Flash and evaluate every column of one table node. ``T`` in K, ``P`` in Pa."""
    if not (T_MIN <= T <= T_MAX):
        raise UnsupportedStateError(
            f"Temperature {T:g} K is outside the supported window {T_MIN:g}-{T_MAX:g} K "
            f"(the ideal-gas Cp polynomials are published for about 273-1500 K and are used down to {T_MIN:g} K)."
        )
    if not (P_MIN <= P <= P_MAX):
        raise UnsupportedStateError(f"Pressure {P:g} Pa is outside the supported window {P_MIN:g}-{P_MAX:g} Pa.")
    z = _normalise(z, eos.n)
    flash: FlashResult = flash_tp(eos, T, P, z, trace)
    comps = eos.components
    fills: list[dict] = []
    if flash.n_phases == 2:
        gas_split = next(p for p in flash.phases if p.kind == "gas")
        liq_split = next(p for p in flash.phases if p.kind == "liquid")
        gas = phase_properties(eos, T, P, gas_split.x, gas_split.Z, "gas")
        liq = phase_properties(eos, T, P, liq_split.x, liq_split.Z, "liquid")
        v = gas_split.fraction
        rs = v * gas.molar_mass / (v * gas.molar_mass + (1.0 - v) * liq.molar_mass)
        sigma = transport.surface_tension(
            comps, liq.x, _molar_density(eos, T, P, liq.x, liq.Z), gas.x, _molar_density(eos, T, P, gas.x, gas.Z))
        return NodeProperties(gas, liq, rs, v, sigma, 2, flash.converged, fills, flash.trace)

    only = flash.phases[0]
    main = phase_properties(eos, T, P, only.x, only.Z, only.kind)
    roots = eos.z_roots(T, P, z)
    other_kind = "liquid" if only.kind == "gas" else "gas"
    candidate = roots[0] if other_kind == "liquid" else roots[-1]
    extrapolated = False
    if abs(candidate - only.Z) > 1e-9:
        method = "metastable_root"
        pseudo_v = eos.pseudo_volume(T, z, other_kind)
        root_v = candidate * R * T / P
        # A metastable root closer to its spinodal than the pseudo-root is replaced by it, so the absent-phase
        # columns stay continuous where the root appears; the root itself is used everywhere it is further in.
        if (root_v > pseudo_v) if other_kind == "liquid" else (root_v < pseudo_v):
            other = _pseudo_phase(eos, T, z, other_kind)
            method = "metastable_root_limited"
            extrapolated = True
        else:
            other = phase_properties(eos, T, P, z, candidate, other_kind)
        liq_density = _molar_density(eos, T, P, z, roots[0])
        gas_density = _molar_density(eos, T, P, z, roots[-1])
        sigma = transport.surface_tension(comps, z, liq_density, z, gas_density)
        sigma_method = "parachor on the two EOS roots of the feed"
    else:
        other = _pseudo_phase(eos, T, z, other_kind)
        method = "single_root"
        extrapolated = True
        sigma = 0.0
        sigma_method = "zero: one EOS root, no interface"
    gas, liq = (main, other) if only.kind == "gas" else (other, main)
    absent = other_kind
    fill = {
        "absent": absent, "method": method, "sigma_method": sigma_method,
        "columns": list(LIQUID_COLUMNS if absent == "liquid" else GAS_COLUMNS) + ["SIGGHL"],
    }
    if extrapolated:
        fill["extrapolation"] = PSEUDO_ROOT_LABEL
    fills.append(fill)
    rs = 1.0 if only.kind == "gas" else 0.0
    return NodeProperties(gas, liq, rs, rs, sigma, 1, flash.converged, fills, flash.trace)
