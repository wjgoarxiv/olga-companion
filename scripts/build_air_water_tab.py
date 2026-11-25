# /// script
# requires-python = ">=3.11"
# dependencies = ["coolprop==8.1.0"]
# ///
"""Compute the bundled generic air-water table, resources/fluids/air_water.tab.

Run by hand when the table changes; the app ships only the result:

    uv run --no-project scripts/build_air_water_tab.py resources/fluids/air_water.tab

Equations, all published and all evaluated by CoolProp (MIT licence):
water IAPWS-95 with the IAPWS viscosity, conductivity and surface tension; dry air Lemmon 2000
with Lemmon-Jacobsen 2004 transport; gas saturated with water vapour ASHRAE RP-1485. The table
describes a mixture of half water, half air (mole), so where that water is all vapour (70 and 80 C at
0.5 bar, 80 C at 0.8 bar) the gas keeps that composition. Gas derivatives are at fixed composition.
The fluid has no oil phase, so every oil column repeats dry air (HHL 250 J/kg lower) and
SIGGHL is a constant.
Enthalpy and entropy are zero for each component as an ideal gas at 25 C and 1 atm.
"""

import math
import sys
from pathlib import Path

from CoolProp.CoolProp import HAPropsSI, PropsSI

PRESSURES = [5e4, 8e4, 101325.0, 1.2e5, 1.5e5, 2e5, 3e5, 5e5, 8e5, 1.2e6, 1.6e6, 2e6]
TEMPERATURES = [0, 10, 20, 25, 30, 40, 50, 60, 70, 80]
STD_P, STD_T = 101325.0, 15.55556
ATM, T_REF = 101325.0, 298.15
# IAPWS-95 starts at the triple point (the melting line reaches 273.16 K); 0 C is stepped to from here.
WATER_T_MIN = 273.17
WATER_SHARE = 0.5
# OLGA warns when a gas enthalpy is below the oil one; moist gas dips up to 220 J/kg below dry air.
OIL_OFFSET = 250.0
M_WATER, M_AIR = PropsSI("M", "Water"), PropsSI("M", "Air")
AIR = {"NITROGEN": 0.7812, "OXYGEN": 0.2096, "ARGON": 0.0092}
COLUMNS = (
    "PT TM ROG ROHL ROWT DROGDP DROHLDP DROWTDP DROGDT DROHLDT DROWTDT RS RSW VISG VISHL VISWT CPG CPHL CPWT "
    "HG HHL HWT TCG TCHL TCWT SIGGHL SIGGWT SIGHLWT SEG SEHL SEWT"
).split()
R_WATER = 8.314462618 / M_WATER
# A vapour at 10 Pa is an ideal gas; its entropy is then carried to 1 atm along the isotherm.
H_WATER0 = PropsSI("H", "T", T_REF, "P", 10.0, "Water")
S_WATER0 = PropsSI("S", "T", T_REF, "P", 10.0, "Water") - R_WATER * math.log(ATM / 10.0)
H_AIR0 = HAPropsSI("Hha", "T", T_REF, "P", ATM, "R", 0.0)
S_AIR0 = HAPropsSI("Sha", "T", T_REF, "P", ATM, "R", 0.0)


def water(p: float, kelvin: float) -> dict[str, float]:
    t = max(kelvin, WATER_T_MIN)
    step = kelvin - t
    get = lambda name: PropsSI(name, "T", t, "P", p, "Water")  # noqa: E731
    cp, slope = get("C"), get("d(D)/d(T)|P")
    sigma = PropsSI("I", "T", t, "Q", 0, "Water")
    return {
        "ROWT": get("D") + slope * step, "DROWTDP": get("d(D)/d(P)|T"), "DROWTDT": slope,
        "VISWT": get("V"), "CPWT": cp, "TCWT": get("L"), "SIGGWT": sigma, "SIGHLWT": sigma,
        "HWT": get("H") + cp * step - H_WATER0, "SEWT": get("S") + cp * step / t - S_WATER0,
    }


def air(p: float, t: float) -> dict[str, float]:
    get = lambda name: PropsSI(name, "T", t, "P", p, "Air")  # noqa: E731
    return {
        "ROHL": get("D"), "DROHLDP": get("d(D)/d(P)|T"), "DROHLDT": get("d(D)/d(T)|P"),
        "VISHL": get("V"), "CPHL": get("C"), "TCHL": get("L"), "SIGGHL": 0.02,
        "HHL": HAPropsSI("Hha", "T", t, "P", p, "R", 0.0) - H_AIR0 - OIL_OFFSET,
        "SEHL": HAPropsSI("Sha", "T", t, "P", p, "R", 0.0) - S_AIR0 - OIL_OFFSET / T_REF,
    }


def gas_density(p: float, t: float, mole: float) -> float:
    return 1 / HAPropsSI("Vha", "T", t, "P", p, "psi_w", mole)


def gas(p: float, t: float) -> dict[str, float]:
    boils = PropsSI("P", "T", max(t, WATER_T_MIN), "Q", 1, "Water") >= WATER_SHARE * p
    mole = WATER_SHARE if boils else min(WATER_SHARE, HAPropsSI("psi_w", "T", t, "P", p, "R", 1.0))
    get = lambda name: HAPropsSI(name, "T", t, "P", p, "psi_w", mole)  # noqa: E731
    x = mole * M_WATER / (mole * M_WATER + (1 - mole) * M_AIR)
    density = gas_density(p, t, mole)
    return {
        "ROG": density, "RS": 1.0, "RSW": x,
        # Taken towards lower pressure and higher temperature, where this gas stays unsaturated.
        "DROGDP": (density - gas_density(p * 0.999, t, mole)) / (0.001 * p),
        "DROGDT": (gas_density(p, t + 0.05, mole) - density) / 0.05,
        "VISG": get("mu"), "CPG": get("Cha"), "TCG": get("k"),
        "HG": get("Hha") - (1 - x) * H_AIR0 - x * H_WATER0,
        "SEG": get("Sha") - (1 - x) * S_AIR0 - x * S_WATER0,
    }


def numbers(values) -> str:
    return "( " + " , ".join(f"{value:.9g}" for value in values) + " )"


def table() -> str:
    std = gas(STD_P, STD_T + 273.15)
    std_gas, x_std = std["ROG"], std["RSW"]
    std_water = PropsSI("D", "T", STD_T + 273.15, "P", STD_P, "Water")
    # One mole, half water and half air, flashed at standard conditions.
    gas_mass = 0.5 * M_AIR / (1 - x_std)
    water_mass = 0.5 * M_WATER - gas_mass * x_std
    glr = (gas_mass / std_gas) / (water_mass / std_water)
    liquid = [std_water] + [PropsSI("D", "P", ATM, "Q", 0, name) for name in ("Nitrogen", "Oxygen", "Argon")]
    weights = [M_WATER] + [PropsSI("M", name) for name in ("Nitrogen", "Oxygen", "Argon")]
    envelope = [60.0 + 3 * i for i in range(25)]
    head = [
        'PVTTABLE LABEL = "AIR_WATER" ,  PHASE = THREE, \\',
        "!",
        "! OLGA Companion, scripts/build_air_water_tab.py",
        "! Open equations evaluated with CoolProp: water IAPWS-95, air Lemmon 2000, moist gas ASHRAE RP-1485.",
        "! No oil phase: the HL columns are placeholders that repeat dry air.",
        "!",
        'COMPONENTS = ( ' + ' , '.join(f'"{name}"' for name in ['WATER', *AIR]) + ' ), \\',
        f"MOLES = {numbers([0.5] + [0.5 * share for share in AIR.values()])}, \\",
        f"MOLWEIGHT = {numbers(1e3 * value for value in weights)}, \\",
        f"DENSITY = {numbers(1e-3 * value for value in liquid)} G/CM3, \\",
        f"STDPRESSURE = {STD_P:.0f} PA , \\",
        f"STDTEMPERATURE = {STD_T} C, \\",
        "GOR = -999 SM3/SM3, \\",
        f"GLR = {glr:.9g} SM3/SM3, \\",
        "WC = 1.00000000 , \\",
        f"STDGASDENSITY = {std_gas:.9g} KG/M3, \\",
        "STDOILDENSITY = -999 KG/M3, \\",
        f"STDWATDENSITY = {std_water:.9g} KG/M3, \\",
        f"MESHTYPE = STANDARD,TOTWATERFRACTION = {numbers([M_WATER / (M_WATER + M_AIR)])},\\",
        f"PRESSURE = {numbers(PRESSURES)} PA, \\",
        f"TEMPERATURE = {numbers(TEMPERATURES)} C, \\",
    ]
    for kind, quality in (("BUBBLE", 0), ("DEW", 1)):
        pressures = [PropsSI("P", "T", t, "Q", quality, "Air") for t in envelope]
        head.append(f"{kind}PRESSURES = {numbers(pressures)} PA, \\")
        head.append(f"{kind}TEMPERATURES = {numbers(t - 273.15 for t in envelope)} C, \\")
    head += [
        f"CRITICALPRESSURE = {numbers([PropsSI('pcrit', 'Air')])} PA, \\",
        f"CRITICALTEMPERATURE = {numbers([PropsSI('Tcrit', 'Air') - 273.15])} C, \\",
        f"COLUMNS = ( {', '.join(COLUMNS)} )",
    ]
    points = []
    for p in PRESSURES:
        for celsius in TEMPERATURES:
            kelvin = celsius + 273.15
            row = {"PT": p, "TM": celsius, **water(p, kelvin), **air(p, kelvin), **gas(p, kelvin)}
            points.append(f"PVTTABLE POINT = {numbers(row[name] for name in COLUMNS)}")
    return "\n".join(head + points) + "\n"


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(table(), encoding="ascii", newline="\n")
