"""OLGA keyword ``.tab`` writer (PHASE = TWO, MESHTYPE = STANDARD) for the independent engine.

Never overwrites: the table and its fill-report sidecar are created exclusively. Every node where a phase is
absent and its columns were filled by a pseudo-root extrapolation (or a zero surface tension) is listed in the
report, in the sidecar and in a count in the file header. A property that fails a physical check stops the
run before anything is written.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .components import SUPPORTED_COMPONENTS, get_component
from .cubic import SUPPORTED_EOS, CubicEOS
from .errors import (
    GridPolicyError,
    NonPhysicalValueError,
    OverwriteError,
    PvtEngineError,
    UnsupportedStateError,
)
from .flash import bubble_pressure
from .properties import P_MAX, P_MIN, T_MAX, T_MIN, node_properties

ENGINE_NAME = "olga_companion.pvt_engine"
ENGINE_VERSION = "0.1"

COLUMNS = (
    "PT", "TM", "ROG", "ROHL", "DROGDP", "DROHLDP", "DROGDT", "DROHLDT", "RS",
    "VISG", "VISHL", "CPG", "CPHL", "HG", "HHL", "TCG", "TCHL", "SIGGHL", "SEG", "SEHL",
)

CO2_TRIPLE_T_K = 216.59  # Span & Wagner, J. Phys. Chem. Ref. Data 25 (1996) 1509
CO2_TRIPLE_P_BAR = 5.18
CO2_RICH_MOLE_FRACTION = 0.5

_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_EOS_TEXT = {
    "PR": "Peng-Robinson (Peng & Robinson, 1976)",
    "PR78": "Peng-Robinson with the 1978 alpha function (Robinson & Peng, 1978)",
    "SRK": "Soave-Redlich-Kwong (Soave, 1972)",
}

# The keyword header mirrors the order of OLGA's own STANDARD samples
# (e.g. Compr-Gas.tab, PHASE = TWO): quoted label first on line 1, then EOS,
# composition, reference data, standard state, gas/oil reference densities,
# mesh, axes, bubble line and columns. Keys the engine cannot compute honestly
# (CRITICAL*, DEW* on a TWO-phase table) are omitted, never invented.
_EOS_KEYWORD = {"PR": "PR Peneloux", "PR78": "PR 78 Peneloux", "SRK": "SRK Peneloux"}
T_STD_K = 288.15  # 15 C; the sample tables use 288.15 K (15 C) or 288.71 K
P_STD_PA = 101325.0  # 1 ATM
_BUBBLE_ABSENT_PA = 1e10  # the samples' not-available bubble pressure


def _standard_densities(model: CubicEOS, moles: list[float]) -> tuple[float, float]:
    """EOS gas/oil densities (kg/m3) at 101325 Pa and 288.15 K.

    A phase that is absent at the standard state reports 0.0, the Compr-Gas
    convention (its STDOILDENSITY is 0 where no oil exists at standard
    conditions). A failed standard flash also reports 0.0 rather than an
    invented value.
    """
    try:
        node = node_properties(model, T_STD_K, P_STD_PA, list(moles))
    except (PvtEngineError, ValueError, ArithmeticError):
        return 0.0, 0.0
    if not node.converged:
        return 0.0, 0.0
    if node.n_phases == 2:
        return node.gas.rho, node.liquid.rho
    if node.rs >= 1.0:
        return node.gas.rho, 0.0
    return 0.0, node.liquid.rho


def _bubble_pressures(model: CubicEOS, moles: list[float], temps_c: list[float]) -> list[float]:
    """Bubble pressure (Pa) per grid temperature; 1e10 where none exists.

    The samples write 1e10 Pa where a temperature has no bubble point; the
    engine reports that convention instead of hiding the missing point.
    """
    out = []
    for temp_c in temps_c:
        try:
            out.append(bubble_pressure(model, temp_c + 273.15, list(moles)))
        except (PvtEngineError, ValueError, ArithmeticError, ZeroDivisionError, OverflowError):
            out.append(_BUBBLE_ABSENT_PA)
    return out


@dataclass
class TableReport:
    path: Path
    sidecar_path: Path | None
    label: str
    node_count: int
    fills: list[dict] = field(default_factory=list)
    clipped_temperatures_c: list[float] = field(default_factory=list)
    traces: dict[tuple[int, int], dict] = field(default_factory=dict)
    elapsed_s: float = 0.0


def _number(value: float) -> str:
    return format(value, ".10g")


def _grid(values: Iterable[float], kind: str, low: float, high: float) -> list[float]:
    out = []
    for raw in values:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            raise ValueError(f"{kind} grid values must be finite numbers.")
        out.append(float(_number(float(raw))))
    if len(out) < 2:
        raise ValueError(f"{kind} grid needs at least two values.")
    if any(b <= a for a, b in zip(out, out[1:])):
        raise ValueError(f"{kind} grid must be strictly increasing.")
    if out[0] < low or out[-1] > high:
        raise UnsupportedStateError(f"{kind} grid {out[0]:g} to {out[-1]:g} is outside the supported window {low:g} to {high:g}.")
    return out


def _check_node(node, where: str) -> None:
    def bad(name: str, value: float, why: str):
        raise NonPhysicalValueError(f"Node {where}: {name} = {value!r} is not physical ({why}); nothing was written.")

    for phase in (node.gas, node.liquid):
        for name in ("rho", "mu", "cp", "k"):
            value = getattr(phase, name)
            if not math.isfinite(value) or value <= 0.0:
                bad(f"{phase.kind} {name}", value, "must be finite and positive")
        for name in ("drho_dp", "drho_dt", "h", "s"):
            value = getattr(phase, name)
            if not math.isfinite(value) or abs(value) > 1e30:
                bad(f"{phase.kind} {name}", value, "must be finite")
    if not math.isfinite(node.sigma) or node.sigma < 0.0:
        bad("surface tension", node.sigma, "must be finite and not negative")
    if not (0.0 <= node.rs <= 1.0):
        bad("gas mass fraction", node.rs, "must lie in [0, 1]")


def _row(node, p: float, t_c: float) -> list[float]:
    g, l = node.gas, node.liquid
    return [p, t_c, g.rho, l.rho, g.drho_dp, l.drho_dp, g.drho_dt, l.drho_dt, node.rs,
            g.mu, l.mu, g.cp, l.cp, g.h, l.h, g.k, l.k, node.sigma, g.s, l.s]


@dataclass
class CheckedRequest:
    comps: list
    names: list[str]
    moles: list[float]
    eos: str
    model: CubicEOS
    pressures: list[float]
    temps_c: list[float]
    clipped: list[float]


def fill_report_path(table: Path) -> Path:
    return table.with_name(table.stem + ".fill.json")


def check_request(
    components: Sequence[object],
    moles: Sequence[float],
    eos: str,
    pressures_pa: Sequence[float],
    temperatures_c: Sequence[float],
    label: str,
    kij: Mapping[tuple[str, str], float] | None = None,
    grid_policy: str = "refuse",
) -> CheckedRequest:
    """Every refusal that needs no file and no flash: names, moles, model, label and both grids."""
    comps = [get_component(c) for c in components]
    if len({c.name for c in comps}) != len(comps):
        raise ValueError("A component appears more than once.")
    moles = list(moles)
    if len(moles) != len(comps) or any(isinstance(m, bool) or not isinstance(m, (int, float)) or not math.isfinite(m) or m < 0 for m in moles):
        raise ValueError("Moles must be one finite non-negative number per component.")
    if abs(sum(moles) - 1.0) > 1e-6:
        raise ValueError(f"Moles must sum to 1 within 1e-6 (got {sum(moles):.8g}); the engine never rescales a composition.")
    if eos not in SUPPORTED_EOS:
        raise ValueError(f"EOS {eos!r} is not available in the independent engine. Supported: {', '.join(SUPPORTED_EOS)}.")
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise ValueError("Label must be 1-64 characters: letters, digits, underscore, hyphen, dot.")
    if grid_policy not in ("refuse", "clip"):
        raise ValueError("grid_policy must be 'refuse' or 'clip'.")
    model = CubicEOS(eos, comps, kij=kij)
    pressures = _grid(pressures_pa, "Pressure", P_MIN, P_MAX)
    temps_c = _grid(temperatures_c, "Temperature", T_MIN - 273.15, T_MAX - 273.15)

    clipped: list[float] = []
    names = [c.name for c in comps]
    if "CO2" in names and moles[names.index("CO2")] >= CO2_RICH_MOLE_FRACTION:
        low = [t for t in temps_c if t + 273.15 < CO2_TRIPLE_T_K]
        if low:
            listed = ", ".join(f"{t:g}" for t in low)
            if grid_policy == "refuse":
                raise GridPolicyError(
                    f"This CO2-rich fluid (CO2 {moles[names.index('CO2')]:.3g} mole fraction) has grid temperatures below the CO2 triple point "
                    f"({CO2_TRIPLE_T_K} K = {CO2_TRIPLE_T_K - 273.15:.2f} C, {CO2_TRIPLE_P_BAR} bar): {listed} C. "
                    "The engine has no solid phase and writes no dry-ice states. Raise the lowest temperature or ask for grid_policy='clip'."
                )
            clipped = low
            temps_c = [t for t in temps_c if t not in low]
            if len(temps_c) < 2:
                raise GridPolicyError("Clipping at the CO2 triple point leaves fewer than two temperatures.")

    return CheckedRequest(comps, names, moles, eos, model, pressures, temps_c, clipped)


def generate_table(
    path: str | os.PathLike,
    components: Sequence[object],
    moles: Sequence[float],
    eos: str,
    pressures_pa: Sequence[float],
    temperatures_c: Sequence[float],
    label: str,
    kij: Mapping[tuple[str, str], float] | None = None,
    grid_policy: str = "refuse",
    trace_nodes: Iterable[tuple[int, int]] | None = None,
    write_fill_report: bool = True,
) -> TableReport:
    """Compute and write a keyword ``.tab``. ``trace_nodes`` holds (i_pressure, i_temperature) pairs to trace."""
    started = time.perf_counter()
    checked = check_request(components, moles, eos, pressures_pa, temperatures_c, label, kij, grid_policy)
    comps, names, moles, model = checked.comps, checked.names, checked.moles, checked.model
    pressures, temps_c, clipped = checked.pressures, checked.temps_c, checked.clipped
    target = Path(path)
    sidecar = fill_report_path(target) if write_fill_report else None
    for existing in (target, sidecar):
        if existing is not None and existing.exists():
            raise OverwriteError(f"{existing.name} already exists; the engine never overwrites a file. Choose a new name.")

    trace_set = {tuple(n) for n in (trace_nodes or ())}
    n_p, n_t = len(pressures), len(temps_c)
    nodes: dict[tuple[int, int], list[float]] = {}
    fills: list[dict] = []
    traces: dict[tuple[int, int], dict] = {}
    for it, t_c in enumerate(temps_c):
        for ip, p in enumerate(pressures):
            where = f"P={p:g} Pa, T={t_c:g} C (index {ip},{it})"
            node = node_properties(model, t_c + 273.15, p, moles, trace=(ip, it) in trace_set)
            if not node.converged:
                raise UnsupportedStateError(f"Node {where}: the flash did not converge; nothing was written.")
            _check_node(node, where)
            nodes[(ip, it)] = _row(node, p, t_c)
            for fill in node.fills:
                fills.append({"i_pressure": ip, "i_temperature": it, "pressure_pa": p, "temperature_c": t_c, **fill})
            if node.trace is not None:
                traces[(ip, it)] = node.trace
    fills.sort(key=lambda f: (f["i_pressure"], f["i_temperature"]))

    bips = ", ".join(f"{a}-{b} = {_number(v)}" for (a, b), v in model.kij_given.items())
    bip_line = (f"binary interaction parameters: {bips} (user supplied; every other pair zero)" if bips
                else "binary interaction parameters: all zero (none supplied)")
    header = [
        f"! Independent PVT table written by {ENGINE_NAME} {ENGINE_VERSION}.",
        "! Independent table, not Multiflash-identical. Not qualified for OLGA use; compare before relying on it.",
        f"! EOS: {_EOS_TEXT[eos]} with Peneloux constant volume shift (Peneloux et al., 1982); {bip_line}.",
        "! Flash: Michelsen tangent-plane stability (1982a), Rachford-Rice successive substitution with Newton acceleration (Michelsen 1982b), vapour-liquid only.",
        "! Viscosity: Lohrenz-Bray-Clark (1964). Thermal conductivity: modified Eucken dilute gas with Stiel-Thodos (1964) density correction. Surface tension: Weinaug-Katz parachor (1943).",
        "! Enthalpy and entropy: EOS departure plus ideal-gas Cp; zero at 298.15 K and 101325 Pa per pure component (compound datum). RS is the gas mass fraction.",
        f"! Grid: {n_p} pressures x {n_t} temperatures. Filled nodes: {len(fills)} of {n_p * n_t} (phase absent; columns filled by a pseudo-root extrapolation or zero surface tension"
        + ("; listed in the fill report" if sidecar else "") + ").",
        f"! Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.",
    ]
    if clipped:
        header.append(f"! Grid clipped at the CO2 triple point: removed temperatures {', '.join(f'{t:g}' for t in clipped)} C.")
    std_gas, std_oil = _standard_densities(model, moles)
    bubble = _bubble_pressures(model, moles, temps_c)
    quoted = ", ".join(f'"{name}"' for name in names)
    lines = [
        f'PVTTABLE LABEL = "{label}",PHASE = TWO,\\',
        *header,
        f'EOS = "{_EOS_KEYWORD[eos]}",\\',
        f"COMPONENTS = ( {quoted} ), MOLES = ( {', '.join(_number(m) for m in moles)} ), \\",
        # Pure-component reference densities are databank quantities the engine
        # does not ship; zeros follow the samples' not-available convention
        # (Compr-Gas.tab reports 0 for every light component).
        f"MOLWEIGHT = ( {', '.join(_number(comp.molar_mass) for comp in comps)} ) g/mol, \\",
        f"DENSITY = ( {', '.join(_number(0.0) for _ in comps)} ) g/cm3, \\",
        f"STDPRESSURE = {_number(1.0)} ATM, \\",
        f"STDTEMPERATURE = {_number(T_STD_K)} K, \\",
        # The engine has no standard-process GOR/GLR model; -999 follows the
        # samples' not-available convention (Compr-Gas.tab uses it for both).
        f"GOR = {_number(-999.0)} Sm3/Sm3, \\",
        f"GLR = {_number(-999.0)} Sm3/Sm3, \\",
        f"STDGASDENSITY = {_number(std_gas)} kg/m3, \\",
        f"STDOILDENSITY = {_number(std_oil)} kg/m3, \\",
        # No CRITICALPRESSURE/CRITICALTEMPERATURE: the engine has no mixture
        # critical-point solver, so the lines are omitted, never invented.
        # No DEW*: a TWO-phase sample (Compr-Gas.tab) carries no dew line.
        "MESHTYPE = STANDARD, \\",
        f"PRESSURE = ( {', '.join(_number(p) for p in pressures)} ) PA, \\",
        f"TEMPERATURE = ( {', '.join(_number(t) for t in temps_c)} ) C, \\",
        f"BUBBLEPRESSURES = ( {', '.join(_number(p) for p in bubble)} ) PA, \\",
        f"BUBBLETEMPERATURES = ( {', '.join(_number(t) for t in temps_c)} ) C, \\",
        f"COLUMNS = ( {', '.join(COLUMNS)} )",
    ]
    for ip in range(n_p):
        for it in range(n_t):
            lines.append("PVTTABLE POINT = ( " + ", ".join(_number(v) for v in nodes[(ip, it)]) + " )")
    text = "\n".join(lines) + "\n"

    report = TableReport(target, sidecar, label, n_p * n_t, fills, clipped, traces)
    created: list[Path] = []
    try:
        with open(target, "x", encoding="utf-8", newline="\n") as handle:
            created.append(target)
            handle.write(text)
        if sidecar is not None:
            body = {
                "engine": f"{ENGINE_NAME} {ENGINE_VERSION}",
                "independent_table_not_multiflash_identical": True,
                "label": label, "eos": eos, "components": names, "moles": moles,
                "node_count": n_p * n_t, "filled_node_count": len(fills),
                "clipped_temperatures_c": clipped, "fills": fills,
            }
            with open(sidecar, "x", encoding="utf-8", newline="\n") as handle:
                created.append(sidecar)
                json.dump(body, handle, indent=1)
                handle.write("\n")
    except FileExistsError as exc:
        for made in created:
            made.unlink(missing_ok=True)
        named = Path(exc.filename).name if exc.filename else target.name
        raise OverwriteError(f"{named} already exists; the engine never overwrites a file.") from exc
    except Exception:
        for made in created:
            made.unlink(missing_ok=True)
        raise
    report.elapsed_s = time.perf_counter() - started
    return report
