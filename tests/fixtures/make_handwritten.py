"""Writes the hand-made fixtures from plain formulas and typed numbers (no OLGA or Multiflash output).

    python tests/fixtures/make_handwritten.py
"""
from __future__ import annotations

import math
from pathlib import Path

HERE = Path(__file__).parent
R, M = 8.314462618, 0.02  # J/mol/K; a 20 g/mol ideal gas
COLUMNS = (
    "PT TM ROG ROHL ROWT DROGDP DROHLDP DROWTDP DROGDT DROHLDT DROWTDT RS RSW VISG VISHL VISWT "
    "CPG CPHL CPWT HG HHL HWT TCG TCHL TCWT SIGGHL SIGGWT SIGHLWT SEG SEHL SEWT"
).split()


def _point(p: float, t: float) -> list[float]:
    """Ideal gas; an oil and a water with linear density; constant heat capacities."""
    k, dt = t + 273.15, t - 25.0
    rog = p * M / (R * k)
    cpg, cpo, cpw = 2200.0, 2100.0, 4180.0
    entropy = [cp * math.log(k / 298.15) for cp in (cpg, cpo, cpw)]
    return [
        p, t, rog, 700.0 - 0.7 * dt + 1e-6 * p, 997.0 - 0.3 * dt + 4.5e-7 * p,
        rog / p, 1e-6, 4.5e-7, -rog / k, -0.7, -0.3,
        max(0.0, 0.8 - 6e-8 * p), 0.02 * 1e5 / p,
        1.1e-5, 4e-4, 8e-4, cpg, cpo, cpw,
        cpg * dt, cpo * dt - 3e5, cpw * dt - 2e6, 0.03, 0.12, 0.6, 0.02, 0.07, 0.05,
        entropy[0] - R / M * math.log(p / 101325.0), entropy[1] - 800.0, entropy[2] - 6000.0,
    ]


def _list(values: list[float]) -> str:
    return " , ".join(f"{value:.6g}" for value in values)


def table() -> str:
    pressures, temperatures = [1e5, 5e6, 1e7], [0.0, 26.85, 76.85]
    lines = [
        "PVTTABLE LABEL = probe ,  PHASE = THREE, \\",
        "!",
        "! Test table written for OLGA Companion by tests/fixtures/make_handwritten.py; not for design use.",
        "!",
        "COMPONENTS = ( GAS , OIL , WATER ), \\",
        "MOLES = ( .3 , .1 , .6 ), \\",
        "MOLWEIGHT = ( 20 , 120 , 18.015 ), \\",
        "DENSITY = ( .3 , .7 , .997 ) G/CM3, \\",
        "STDPRESSURE = 101325 PA , \\",
        "STDTEMPERATURE = 15.55556 C, \\",
        "GOR = 400 SM3/SM3, \\",
        "GLR = 200 SM3/SM3, \\",
        "WC = .5 , \\",
        "STDGASDENSITY = .84 KG/M3, \\",
        "STDOILDENSITY = 706 KG/M3, \\",
        "STDWATDENSITY = 999 KG/M3, \\",
        "MESHTYPE = STANDARD,TOTWATERFRACTION = ( .4 ),\\",
        f"PRESSURE = ( {_list(pressures)} ) PA, \\",
        f"TEMPERATURE = ( {_list(temperatures)} ) C, \\",
        "BUBBLEPRESSURES = ( 1e6 , 5e6 , 9e6 , 1.2e7 ) PA, \\",
        "BUBBLETEMPERATURES = ( -80 , -20 , 40 , 100 ) C, \\",
        "DEWPRESSURES = ( 1e5 , 1e6 , 5e6 , 1.2e7 ) PA, \\",
        "DEWTEMPERATURES = ( 60 , 110 , 150 , 100 ) C, \\",
        "CRITICALPRESSURE = ( 1.2e7 ) PA, \\",
        "CRITICALTEMPERATURE = ( 100 ) C, \\",
        f"COLUMNS = ( {', '.join(COLUMNS)} )",
    ]
    lines += [f"PVTTABLE POINT = ( {_list(_point(p, t))} )" for p in pressures for t in temperatures]
    return "\n".join(lines) + "\n"


def controller_trend() -> str:
    """61 steps: the loop output falls from its bias 0.3 to 0 while the pressure settles."""
    head = [
        "'OLGA Companion test trend'", "TIME PLOT", "INPUT FILE", "'case.genkey'", "PVT FILE", "'fluid.tab'",
        "PROJECT", "'Hand-written controller trend'", "NETWORK", "1", "GEOMETRY' (M)  '", "BRANCH", "'MAIN'", "2",
        "0.0 50.0 100.0", "0.0 0.0 0.0",
        "CATALOG ", "3",
        "PT 'POSITION:' 'POS_MAIN' '(PA)' 'Pressure'",
        "GT 'POSITION:' 'POS_MAIN' '(KG/S)' 'Total mass flow'",
        "CONTR 'CONTROLLER:' 'PC' '(-)' 'Controller output'",
        "TIME SERIES  ' (S)  '",
    ]
    rows = [
        f"{10.0 * step:.6e} {2e6 - 5e3 * step:.6e} {1.5 - 0.01 * step:.6e} {max(0.0, round(0.3 - 0.01 * step, 4)):.6e}"
        for step in range(61)
    ]
    return "\n".join(head + rows) + "\n"


if __name__ == "__main__":
    for name, text in (("multiflash/handwritten_3x3.tab", table()), ("results/controller_loop.tpl", controller_trend())):
        (HERE / name).write_text(text, encoding="utf-8", newline="\n")
