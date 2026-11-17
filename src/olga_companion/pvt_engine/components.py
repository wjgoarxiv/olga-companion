"""Pure-component constants of the independent PVT engine.

Every constant carries its public source in ``Component.sources``. Critical
constants, acentric factors and critical densities come from the NIST Chemistry
WebBook, SRD 69 (thermophysical properties of fluids, fetched 2026-10-31); the
critical molar volume is molar mass / critical density. Molar masses are
computed from IUPAC standard atomic weights (C 12.011, H 1.008, N 14.007,
O 15.999, S 32.06). The ideal-gas heat-capacity polynomials and the parachors
are the classical published values listed below, entered by hand; they are the
first thing to re-check against the book before the table is relied on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .errors import UnknownComponentError

_NIST = "NIST Chemistry WebBook SRD 69, fluid data page ({fluid}), fetched 2026-10-31"
_CP = ("Reid, Prausnitz & Poling, The Properties of Gases and Liquids, 4th ed. (1987), Appendix A, "
       "ideal-gas Cp = a + bT + cT^2 + dT^3 in J/mol/K, T in K (about 273-1500 K)")
_PARACHOR = ("Parachor [(mN/m)^0.25 cm^3/mol] as tabulated for the Weinaug-Katz method (Weinaug & Katz, "
             "Ind. Eng. Chem. 35 (1943) 239; Reid, Prausnitz & Poling 4th ed. ch. 12)")
_MASS = "IUPAC standard atomic weights applied to the molecular formula"


@dataclass(frozen=True)
class Component:
    name: str
    formula: str
    aliases: tuple[str, ...]
    molar_mass: float  # g/mol
    tc: float  # K
    pc: float  # bar
    omega: float
    vc: float  # cm3/mol
    parachor: float
    cp_ig: tuple[float, float, float, float]  # J/mol/K polynomial in T (K)
    sources: Mapping[str, str] = field(default_factory=dict, compare=False, hash=False)


def _make(name, formula, aliases, molar_mass, tc, pc, omega, rho_c, parachor, cp_ig, fluid) -> Component:
    nist = _NIST.format(fluid=fluid)
    return Component(
        name=name, formula=formula, aliases=aliases, molar_mass=molar_mass, tc=tc, pc=pc, omega=omega,
        vc=round(molar_mass / rho_c * 1000.0, 3), parachor=parachor, cp_ig=cp_ig,
        sources={
            "molar_mass": _MASS, "tc": nist, "pc": nist, "omega": nist,
            "vc": f"molar mass / critical density; critical density from {nist}",
            "parachor": _PARACHOR, "cp_ig": _CP,
        },
    )


COMPONENTS: dict[str, Component] = {
    c.name: c for c in (
        _make("CO2", "CO2", ("carbon dioxide", "co2"), 44.009, 304.1282, 73.773, 0.22394, 467.6, 78.0,
              (19.80, 7.344e-2, -5.602e-5, 1.715e-8), "carbon dioxide"),
        _make("N2", "N2", ("nitrogen", "n2"), 28.014, 126.192, 33.958, 0.0372, 313.3, 41.0,
              (31.15, -1.357e-2, 2.680e-5, -1.168e-8), "nitrogen"),
        _make("CH4", "CH4", ("methane", "c1", "ch4"), 16.043, 190.564, 45.992, 0.01142, 162.66, 77.0,
              (19.25, 5.213e-2, 1.197e-5, -1.132e-8), "methane"),
        _make("C2H6", "C2H6", ("ethane", "c2", "c2h6"), 30.070, 305.322, 48.722, 0.0995, 206.18, 108.0,
              (5.409, 1.781e-1, -6.938e-5, 8.713e-9), "ethane"),
        _make("C3H8", "C3H8", ("propane", "c3", "c3h8"), 44.097, 369.89, 42.512, 0.1521, 220.0, 150.3,
              (-4.224, 3.063e-1, -1.586e-4, 3.215e-8), "propane"),
        _make("iC4", "C4H10", ("isobutane", "i-butane", "ic4", "i-c4", "ic4h10"), 58.123, 407.81, 36.29,
              0.184, 225.5, 181.5, (-1.390, 3.847e-1, -1.846e-4, 2.895e-8), "isobutane"),
        _make("nC4", "C4H10", ("n-butane", "butane", "nc4", "n-c4", "nc4h10"), 58.123, 425.125, 37.96,
              0.201, 228.0, 189.9, (9.487, 3.313e-1, -1.108e-4, -2.822e-9), "butane"),
        _make("H2S", "H2S", ("hydrogen sulfide", "hydrogen sulphide", "h2s"), 34.08, 373.1, 90.0, 0.1005,
              347.3, 80.1, (31.94, 1.436e-3, 2.432e-5, -1.176e-8), "hydrogen sulfide"),
    )
}

SUPPORTED_COMPONENTS = tuple(COMPONENTS)

_LOOKUP = {key.lower(): comp for comp in COMPONENTS.values() for key in (comp.name, *comp.aliases)}


def get_component(name: object) -> Component:
    """Resolve a user name to a component; an unknown name is refused, never guessed."""
    if isinstance(name, Component):
        return name
    key = str(name).strip().lower()
    if key in _LOOKUP:
        return _LOOKUP[key]
    raise UnknownComponentError(
        f"Component {name!r} is not available in the independent engine. "
        f"Supported components: {', '.join(SUPPORTED_COMPONENTS)}."
    )
