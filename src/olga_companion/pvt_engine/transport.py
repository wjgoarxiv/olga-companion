"""Transport properties.

- Viscosity: Lohrenz, Bray & Clark, J. Pet. Technol. 16 (1964) 1171, fourth-order polynomial in reduced
  density driven by the EOS density; dilute-gas part from Stiel & Thodos (1961) per component with
  Herning-Zipperer square-root-of-molar-mass mixing. Pedersen corresponding states is not used: it
  needs a methane reference-viscosity correlation that is not included here. LBC is the viscosity model.
- Thermal conductivity: modified Eucken dilute-gas value (Poling, Prausnitz & O'Connell, 5th ed., ch. 10)
  with Herning-Zipperer mixing, plus the Stiel & Thodos (1964, AIChE J. 10, 26) density correction on
  Kay-rule pseudo-critical constants.
- Surface tension: Weinaug & Katz, Ind. Eng. Chem. 35 (1943) 239, two-phase parachor form.
"""

from __future__ import annotations

import math
from typing import Sequence

from .components import Component
from .cubic import R

_LBC = (0.10230, 0.023364, 0.058533, -0.040758, 0.0093324)
_ATM_BAR = 1.01325


def cp_ideal(comp: Component, T: float) -> float:
    a, b, c, d = comp.cp_ig
    return a + T * (b + T * (c + T * d))


def _xi(tc: float, pc_atm: float, mw: float) -> float:
    return tc ** (1.0 / 6.0) / (math.sqrt(mw) * pc_atm ** (2.0 / 3.0))


def dilute_viscosity(comp: Component, T: float) -> float:
    """Stiel-Thodos dilute-gas viscosity of one component, Pa s."""
    tr = T / comp.tc
    xi = _xi(comp.tc, comp.pc / _ATM_BAR, comp.molar_mass)
    scaled = 34e-5 * tr ** 0.94 if tr <= 1.5 else 17.78e-5 * (4.58 * tr - 1.67) ** 0.625
    return scaled / xi * 1e-3


def _herning_zipperer(values: Sequence[float], x: Sequence[float], comps: Sequence[Component]) -> float:
    weights = [xi * math.sqrt(c.molar_mass) for xi, c in zip(x, comps)]
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)


def viscosity_lbc(comps: Sequence[Component], x: Sequence[float], T: float, molar_density: float) -> float:
    """Lohrenz-Bray-Clark viscosity, Pa s. ``molar_density`` in mol/m3."""
    mw = sum(xi * c.molar_mass for xi, c in zip(x, comps))
    tpc = sum(xi * c.tc for xi, c in zip(x, comps))
    ppc_atm = sum(xi * c.pc for xi, c in zip(x, comps)) / _ATM_BAR
    vpc = sum(xi * c.vc for xi, c in zip(x, comps))  # cm3/mol
    eta0 = _herning_zipperer([dilute_viscosity(c, T) for c in comps], x, comps) * 1e3  # cP
    rho_r = molar_density * 1e-6 * vpc
    poly = sum(a * rho_r ** k for k, a in enumerate(_LBC))
    xi_mix = _xi(tpc, ppc_atm, mw)
    return (eta0 + (poly ** 4 - 1e-4) / xi_mix) * 1e-3


def _stiel_thodos_residual(rho_r: float) -> float:
    if rho_r < 0.5:
        return 14.0e-3 * (math.exp(0.535 * rho_r) - 1.0)
    if rho_r < 2.0:
        return 13.1e-3 * (math.exp(0.67 * rho_r) - 1.069)
    return 2.976e-3 * (math.exp(1.155 * rho_r) + 2.016)


def thermal_conductivity(comps: Sequence[Component], x: Sequence[float], T: float, molar_density: float) -> float:
    """W/m/K; ``molar_density`` in mol/m3."""
    lam0 = []
    for c in comps:
        cv = cp_ideal(c, T) - R
        eta = dilute_viscosity(c, T)
        lam0.append(eta / (c.molar_mass / 1000.0) * (1.32 * cv + 1.77 * R))
    dilute = _herning_zipperer(lam0, x, comps)
    mw = sum(xi * c.molar_mass for xi, c in zip(x, comps))
    tpc = sum(xi * c.tc for xi, c in zip(x, comps))
    ppc = sum(xi * c.pc for xi, c in zip(x, comps))  # bar
    vpc = sum(xi * c.vc for xi, c in zip(x, comps))  # cm3/mol
    zc = ppc * 1e5 * vpc * 1e-6 / (R * tpc)
    gamma = 210.0 * (tpc * mw ** 3 / ppc ** 4) ** (1.0 / 6.0)
    rho_r = molar_density * 1e-6 * vpc
    return dilute + _stiel_thodos_residual(rho_r) / (gamma * zc ** 5)


def surface_tension(
    comps: Sequence[Component], x: Sequence[float], rho_liquid: float, y: Sequence[float], rho_vapor: float
) -> float:
    """Weinaug-Katz parachor surface tension, N/m. Densities in mol/m3."""
    bracket = sum(c.parachor * (xi * rho_liquid - yi * rho_vapor) * 1e-6 for c, xi, yi in zip(comps, x, y))
    return max(bracket, 0.0) ** 4 * 1e-3
