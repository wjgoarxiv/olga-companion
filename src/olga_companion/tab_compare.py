"""Read-only comparison of two OLGA ``.tab`` tables for the same fluid and grid.

Either table may be the reference; the second is the candidate. Grids that differ compare only
their common (P, T) nodes, and the report says so; grid values that differ only by rounding
(about 1e-9 relative) count as the same node. Relative difference per node is
``|c - r| / |r|``. A node whose reference value is zero has no relative difference: it stays out
of the relative mean and maximum and is reported on its own, as a count (``zero_reference_nodes``)
and the largest absolute difference (``zero_reference_max_abs_diff``). Regions come from the
reference RS (gas mass fraction): ``>= 0.999`` gas-only, ``<= 0.001`` liquid-only, else two-phase.
Headline figures use only the nodes where the column's phase is present in the reference: gas
columns where RS > 0.001, liquid columns where RS < 0.999, SIGGHL on two-phase nodes only (a value
at a node without that phase is a filled number, not a property). The all-node figures stay in
``columns`` and are reported as "including filled values". Nodes where the two tables disagree on
the phase label (gas-only, liquid-only or two-phase, from each table's own RS) are counted and
listed. Filled columns come from the validator's V017/V019 warnings, and tables that state
different components or mole fractions get a warning; quotes around component names are ignored
and common aliases (C3 / PROPANE / C3H8, CO2 / CARBON DIOXIDE, ...) count as the same component. This module never writes: both tables are only opened
for reading, the toolkit scripts are imported without bytecode and without leaving ``sys.path``
changed.
"""

from __future__ import annotations

import bisect
import math
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import toolkit_dir
from .genkey_static import MAX_GENKEY_INPUT_BYTES

GAS_ONLY_RS = 0.999
LIQUID_ONLY_RS = 0.001
HEAT_BINS = 8
# The same input ceiling the toolkit applies to a case file; a larger table is refused unread.
MAX_TAB_BYTES = MAX_GENKEY_INPUT_BYTES
GRID_TOLERANCE = 1e-9
MOLE_TOLERANCE = 1e-6
GAS_PRESENT_RS = 0.001
LIQUID_PRESENT_RS = 0.999
MAX_LISTED_DISAGREEMENTS = 50
GAS_COLUMNS = frozenset({"ROG", "DROGDP", "DROGDT", "VISG", "CPG", "HG", "TCG", "SEG"})
LIQUID_COLUMNS = frozenset({"ROHL", "DROHLDP", "DROHLDT", "VISHL", "CPHL", "HHL", "TCHL", "SEHL"})
TWO_PHASE_COLUMNS = frozenset({"SIGGHL"})

# Canonical component -> the other spellings tables use for it (upper case).
_COMPONENT_ALIASES = {
    "METHANE": ("C1", "CH4"),
    "ETHANE": ("C2", "C2H6"),
    "PROPANE": ("C3", "C3H8"),
    "IC4": ("I-BUTANE", "ISOBUTANE", "2-METHYLPROPANE", "I-C4H10", "IC4H10"),
    "NC4": ("N-BUTANE", "BUTANE", "N-C4H10", "NC4H10"),
    "NITROGEN": ("N2",),
    "CARBON DIOXIDE": ("CO2",),
    "HYDROGEN SULPHIDE": ("H2S", "HYDROGEN SULFIDE"),
    "WATER": ("H2O",),
}
_ALIAS_TO_COMPONENT = {
    spelling: canonical
    for canonical, spellings in _COMPONENT_ALIASES.items()
    for spelling in (canonical, *spellings)
}

_PROPERTY_RE = re.compile(r"^Property (\S+)")


class GridMismatchError(ValueError):
    """Raised when the tables share no comparable grid, columns, or files."""


_parser_module = None
_validator_module = None
_TOOLKIT_LOCK = threading.Lock()


@contextmanager
def _toolkit_imports() -> Iterator[None]:
    """Expose the toolkit scripts for one call without leaving the process changed.

    ``sys.path`` is put back exactly as it was (the validator inserts its own folder on a lazy
    import), and no ``__pycache__`` is written into the shipped toolkit folder.
    The swap is one critical section so two comparisons cannot restore each other's path.
    """
    with _TOOLKIT_LOCK:
        path_before = list(sys.path)
        bytecode_before = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(toolkit_dir() / "scripts"))
        try:
            yield
        finally:
            sys.path[:] = path_before
            sys.dont_write_bytecode = bytecode_before


def _toolkit():
    global _parser_module, _validator_module
    if _parser_module is None:
        with _toolkit_imports():
            import tab_parser
            import tab_validator

        _parser_module, _validator_module = tab_parser, tab_validator
    return _parser_module, _validator_module


def _check_file(path: Path) -> None:
    if not path.is_file():
        raise GridMismatchError(f"Table not found: {path.name}")
    size = path.stat().st_size
    if size > MAX_TAB_BYTES:
        raise GridMismatchError(
            f"{path.name} is too large to compare ({size} bytes; the limit is {MAX_TAB_BYTES} bytes)."
        )


def _parse(path: Path):
    """Parse one table; a table the parser cannot read is a clear refusal that names the file."""
    parser_module, _ = _toolkit()
    try:
        with _toolkit_imports():
            return parser_module.TabParser(str(path))
    except OSError as exc:
        raise GridMismatchError(f"Cannot read table {path.name}: {exc.strerror or type(exc).__name__}.") from exc
    except (ValueError, LookupError) as exc:
        raise GridMismatchError(f"Cannot read table {path.name}: {exc}") from exc


def _validate(path: Path) -> dict[str, Any]:
    _, validator_module = _toolkit()
    try:
        with _toolkit_imports():
            return validator_module.TabValidator(str(path)).validate()
    except OSError as exc:
        raise GridMismatchError(f"Cannot read table {path.name}: {exc.strerror or type(exc).__name__}.") from exc
    except (ValueError, LookupError) as exc:
        raise GridMismatchError(f"Cannot validate table {path.name}: {exc}") from exc


def read_grid(path: str | Path) -> dict[str, Any]:
    """Parse one table into its grid, columns and point rows (read-only)."""
    table = Path(path)
    _check_file(table)
    parsed = _parse(table)
    return {
        "label": parsed.label,
        "phase": parsed.phase,
        "columns": list(parsed.columns),
        "pressures": [float(value) for value in parsed.pressure_grid],
        "temperatures": [float(value) for value in parsed.temperature_grid],
        "rows": [[float(value) for value in row] for row in (parsed.point_rows or [])],
    }


def _warnings_by_column(report: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for warning in report.get("warnings", []):
        if warning.get("rule_id") not in ("V017", "V019"):
            continue
        match = _PROPERTY_RE.match(str(warning.get("message", "")))
        if match and match.group(1) not in found:
            found.append(match.group(1))
    return sorted(found)


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= GRID_TOLERANCE * (1.0 + max(abs(a), abs(b)))


def _snapper(axis: list[float]):
    """Map a value onto the nearest reference grid value when they differ only by rounding."""
    ordered = sorted(axis)

    def snap(value: float) -> float:
        index = bisect.bisect_left(ordered, value)
        for neighbour in ordered[max(0, index - 1): index + 1]:
            if _close(neighbour, value):
                return neighbour
        return value

    return snap


def _bins(values: list[float]) -> list[list[float]]:
    """Consecutive groups of the sorted axis, at most HEAT_BINS of them."""
    if len(values) <= HEAT_BINS:
        return [[value] for value in values]
    step = len(values) / HEAT_BINS
    return [values[int(index * step): int((index + 1) * step)] for index in range(HEAT_BINS)]


def canonical_component(name: str) -> str:
    """A component name without quotes, in one spelling per component (C3H8 -> PROPANE)."""
    text = " ".join(str(name).strip().strip("\"'").split()).upper()
    return _ALIAS_TO_COMPONENT.get(text, text)


def _composition(table) -> dict[str, float] | None:
    names = [str(name).strip() for name in (getattr(table, "components", None) or [])]
    moles = list(getattr(table, "moles", None) or [])
    if not names:
        return None
    result: dict[str, float] = {}
    for index, name in enumerate(names):
        key = canonical_component(name)
        amount = float(moles[index]) if len(moles) == len(names) else math.nan
        result[key] = result.get(key, 0.0) + amount
    return result


def _composition_text(table) -> str:
    names = [str(name).strip() for name in (getattr(table, "components", None) or [])]
    moles = list(getattr(table, "moles", None) or [])
    if len(moles) == len(names):
        return ", ".join(f"{name} {mole:g}" for name, mole in zip(names, moles))
    return ", ".join(names)


def _composition_warnings(ref, cand) -> list[dict[str, str]]:
    """Tables for different fluids can still be compared node by node, but not like for like."""
    ref_comp, cand_comp = _composition(ref), _composition(cand)
    if ref_comp is None or cand_comp is None:
        return []
    detail = f"reference: {_composition_text(ref)}; candidate: {_composition_text(cand)}"
    if set(ref_comp) != set(cand_comp):
        return [{
            "code": "components_differ",
            "message_en": f"The two tables list different components ({detail}), so the composition differs "
                          "and the differences below are not like for like.",
            "message_ko": f"두 표의 성분이 다릅니다(기준·후보: {_composition_text(ref)} / {_composition_text(cand)}). "
                          "조성이 달라 아래 차이는 같은 유체의 비교가 아닙니다.",
        }]
    same = all(
        math.isclose(ref_comp[name], cand_comp[name], rel_tol=MOLE_TOLERANCE, abs_tol=1e-9)
        for name in ref_comp
    )
    if same:
        return []
    return [{
        "code": "moles_differ",
        "message_en": f"The two tables state different mole fractions ({detail}), so the composition differs "
                      "and the differences below are not like for like.",
        "message_ko": f"두 표의 몰분율이 다릅니다(기준·후보: {_composition_text(ref)} / {_composition_text(cand)}). "
                      "조성이 달라 아래 차이는 같은 유체의 비교가 아닙니다.",
    }]


def _column_scope(name: str) -> str:
    if name in GAS_COLUMNS:
        return "gas"
    if name in LIQUID_COLUMNS:
        return "liquid"
    if name in TWO_PHASE_COLUMNS:
        return "two_phase"
    return "all"


def _phase_present(scope: str, rs: float) -> bool:
    if scope == "gas":
        return rs > GAS_PRESENT_RS
    if scope == "liquid":
        return rs < LIQUID_PRESENT_RS
    if scope == "two_phase":
        return GAS_PRESENT_RS < rs < LIQUID_PRESENT_RS
    return True


def _phase_label(rs: float) -> str:
    if rs >= GAS_ONLY_RS:
        return "gas_only"
    if rs <= LIQUID_ONLY_RS:
        return "liquid_only"
    return "two_phase"


_LABEL_EN = {"gas_only": "gas-only", "liquid_only": "liquid-only", "two_phase": "two-phase"}
_LABEL_KO = {"gas_only": "가스", "liquid_only": "액체", "two_phase": "2상"}


def compare_tables(reference: str | Path, candidate: str | Path) -> dict[str, Any]:
    """Compare two ``.tab`` files without writing anything. JSON-serializable."""
    ref_path, cand_path = Path(reference), Path(candidate)
    for path in (ref_path, cand_path):
        _check_file(path)
    ref = _parse(ref_path)
    cand = _parse(cand_path)
    ref_report = _validate(ref_path)
    cand_report = _validate(cand_path)

    ref_columns = list(ref.columns)
    cand_columns = list(cand.columns)
    compared = [name for name in ref_columns if name in cand_columns and name not in ("PT", "TM")]
    skipped = sorted(
        [name for name in ref_columns if name not in cand_columns]
        + [name for name in cand_columns if name not in ref_columns]
    )
    if not compared:
        raise GridMismatchError("The tables share no comparable property columns.")

    ref_index = {name: ref_columns.index(name) for name in compared}
    cand_index = {name: cand_columns.index(name) for name in compared}
    rp = ref_columns.index("PT")
    rt = ref_columns.index("TM")
    cp = cand_columns.index("PT")
    ct = cand_columns.index("TM")
    ref_rows = {(float(row[rp]), float(row[rt])): row for row in (ref.point_rows or [])}
    snap_p = _snapper([key[0] for key in ref_rows])
    snap_t = _snapper([key[1] for key in ref_rows])
    cand_rows = {
        (snap_p(float(row[cp])), snap_t(float(row[ct]))): row for row in (cand.point_rows or [])
    }
    exact = (
        [float(value) for value in ref.pressure_grid] == [snap_p(float(value)) for value in cand.pressure_grid]
        and [float(value) for value in ref.temperature_grid]
        == [snap_t(float(value)) for value in cand.temperature_grid]
    )
    common = sorted(set(ref_rows) & set(cand_rows))
    if not common:
        raise GridMismatchError("The tables share no common (pressure, temperature) nodes.")
    pairs = [(ref_rows[key], cand_rows[key], key) for key in common]

    rs_index = ref_columns.index("RS") if "RS" in ref_columns and "RS" in cand_columns else None
    cand_rs_index = cand_columns.index("RS") if rs_index is not None else None
    region_names = ("gas_only", "liquid_only", "two_phase")
    region_nodes: dict[str, int] = {name: 0 for name in region_names}
    region_total: dict[str, float] = {name: 0.0 for name in region_names}
    region_count: dict[str, int] = {name: 0 for name in region_names}

    def region_of(row) -> str | None:
        if rs_index is None:
            return None
        rs = float(row[rs_index])
        if rs >= GAS_ONLY_RS:
            return "gas_only"
        if rs <= LIQUID_ONLY_RS:
            return "liquid_only"
        return "two_phase"

    columns: dict[str, dict[str, Any]] = {}
    # Relative difference per node; a node with a zero reference value has none and is absent.
    cell_rel: dict[str, dict[tuple[float, float], float]] = {name: {} for name in compared}
    for name in compared:
        total = 0.0
        peak = -1.0
        peak_key: tuple[float, float] | None = None
        zero_refs = 0
        zero_abs = 0.0
        for ref_row, cand_row, key in pairs:
            reference_value = float(ref_row[ref_index[name]])
            difference = abs(float(cand_row[cand_index[name]]) - reference_value)
            if reference_value == 0.0:
                zero_refs += 1
                zero_abs = max(zero_abs, difference)
                continue
            rel = difference / abs(reference_value)
            total += rel
            cell_rel[name][key] = rel
            if rel > peak:
                peak, peak_key = rel, key
        relative_nodes = len(cell_rel[name])
        columns[name] = {
            "nodes": len(pairs),
            "relative_nodes": relative_nodes,
            "mean_rel_diff": (total / relative_nodes) if relative_nodes else None,
            "max_rel_diff": peak if relative_nodes else None,
            "max_location": (
                {"pressure_pa": peak_key[0], "temperature_c": peak_key[1]} if peak_key else None
            ),
            "zero_reference_nodes": zero_refs,
            "zero_reference_max_abs_diff": zero_abs,
        }

    for ref_row, _, key in pairs:
        region = region_of(ref_row)
        if region is None:
            continue
        region_nodes[region] += 1
        for name in compared:
            if key in cell_rel[name]:
                region_total[region] += cell_rel[name][key]
                region_count[region] += 1

    present_columns: dict[str, dict[str, Any]] = {}
    headline: dict[str, Any] | None = None
    disagreements: list[dict[str, Any]] = []
    if rs_index is not None and cand_rs_index is not None:
        ref_rs = {key: float(ref_row[rs_index]) for ref_row, _, key in pairs}
        for name in compared:
            scope = _column_scope(name)
            present_keys = [key for _, _, key in pairs if _phase_present(scope, ref_rs[key])]
            rels = {key: cell_rel[name][key] for key in present_keys if key in cell_rel[name]}
            top = max(rels, key=lambda key: rels[key]) if rels else None
            present_columns[name] = {
                "scope": scope,
                "nodes": len(present_keys),
                "relative_nodes": len(rels),
                "mean_rel_diff": (sum(rels.values()) / len(rels)) if rels else None,
                "max_rel_diff": rels[top] if top is not None else None,
                "max_location": (
                    {"pressure_pa": top[0], "temperature_c": top[1]} if top is not None else None
                ),
            }
        ranked = {n: c for n, c in present_columns.items() if c["max_rel_diff"] is not None}
        if ranked:
            best = max(ranked, key=lambda n: ranked[n]["max_rel_diff"])
            headline = {
                "column": best,
                "max_rel_diff": ranked[best]["max_rel_diff"],
                "max_location": ranked[best]["max_location"],
            }
        for ref_row, cand_row, key in pairs:
            ref_label = _phase_label(float(ref_row[rs_index]))
            cand_label = _phase_label(float(cand_row[cand_rs_index]))
            if ref_label != cand_label:
                disagreements.append({
                    "pressure_pa": key[0], "temperature_c": key[1],
                    "reference": ref_label, "candidate": cand_label,
                })
    present_phase = {
        "basis": "RS" if rs_index is not None else "unavailable",
        "columns": present_columns,
        "headline": headline,
    }
    phase_disagreement = {
        "basis": "RS" if rs_index is not None else "unavailable",
        "count": len(disagreements),
        "nodes": disagreements[:MAX_LISTED_DISAGREEMENTS],
        "truncated": len(disagreements) > MAX_LISTED_DISAGREEMENTS,
    }

    with_relative = {name: item for name, item in columns.items() if item["max_rel_diff"] is not None}
    peak_name = max(with_relative, key=lambda name: with_relative[name]["max_rel_diff"]) if with_relative else None
    zero_columns = {name: item for name, item in columns.items() if item["zero_reference_nodes"]}
    filled = {
        "reference": _warnings_by_column(ref_report),
        "candidate": _warnings_by_column(cand_report),
    }
    warnings = _composition_warnings(ref, cand)

    common_p = sorted({key[0] for key in common})
    common_t = sorted({key[1] for key in common})
    bins_p, bins_t = _bins(common_p), _bins(common_t)

    def heat_cell(name: str, p_bin: list[float], t_bin: list[float]) -> float | None:
        """The largest difference in the bin, so the global peak is always drawn; None if nothing compared."""
        found = [
            cell_rel[name][(p, t)] for p in p_bin for t in t_bin if (p, t) in cell_rel[name]
        ]
        return float(f"{max(found):.4g}") if found else None

    heat = {
        "pressures_pa": [group[0] for group in bins_p],
        "temperatures_c": [group[0] for group in bins_t],
        "pressure_ranges_pa": [[group[0], group[-1]] for group in bins_p],
        "temperature_ranges_c": [[group[0], group[-1]] for group in bins_t],
        "columns": {
            name: [[heat_cell(name, p_bin, t_bin) for t_bin in bins_t] for p_bin in bins_p]
            for name in compared
        },
    }

    grid = {
        "method": "exact" if exact else "common_nodes",
        "reference_nodes": len(ref_rows),
        "candidate_nodes": len(cand_rows),
    }
    method_en = "exact grid" if exact else "common nodes"
    method_ko = "동일 격자" if exact else "공통 노드"
    summary_en = (
        f"Compared {len(pairs)} of {len(ref_rows)} reference and {len(cand_rows)} candidate nodes"
        f" ({method_en}); {len(compared)} columns, skipped {len(skipped)}."
    )
    summary_ko = (
        f"기준 {len(ref_rows)}개·후보 {len(cand_rows)}개 노드 중 {len(pairs)}개 비교"
        f"({method_ko}), {len(compared)}개 항목, 제외 {len(skipped)}개."
    )
    if peak_name is not None and headline is not None:
        top = with_relative[peak_name]
        where = top["max_location"]
        at = headline["max_location"]
        summary_en += (
            f" Largest relative difference where the phase is present: {headline['column']}"
            f" {headline['max_rel_diff']:.3g} at P={at['pressure_pa']:g} Pa, T={at['temperature_c']:g} C;"
            f" including filled values: {peak_name} {top['max_rel_diff']:.3g}"
            f" at P={where['pressure_pa']:g} Pa, T={where['temperature_c']:g} C."
        )
        summary_ko += (
            f" 해당 상이 존재하는 노드의 가장 큰 상대오차: {headline['column']}"
            f" {headline['max_rel_diff']:.3g} (P={at['pressure_pa']:g} Pa, T={at['temperature_c']:g} C);"
            f" 채움값 포함: {peak_name} {top['max_rel_diff']:.3g}"
            f" (P={where['pressure_pa']:g} Pa, T={where['temperature_c']:g} C)."
        )
    elif peak_name is not None:
        top = with_relative[peak_name]
        where = top["max_location"]
        summary_en += (
            f" Largest relative difference: {peak_name} {top['max_rel_diff']:.3g}"
            f" at P={where['pressure_pa']:g} Pa, T={where['temperature_c']:g} C."
        )
        summary_ko += (
            f" 가장 큰 상대오차: {peak_name} {top['max_rel_diff']:.3g}"
            f" (P={where['pressure_pa']:g} Pa, T={where['temperature_c']:g} C)."
        )
    else:
        summary_en += " No relative difference could be formed: every compared reference value is zero."
        summary_ko += " 비교한 기준값이 모두 0이라 상대오차를 계산할 수 없습니다."
    if zero_columns:
        zero_nodes = sum(item["zero_reference_nodes"] for item in zero_columns.values())
        zero_peak = max(item["zero_reference_max_abs_diff"] for item in zero_columns.values())
        summary_en += (
            f" {len(zero_columns)} column(s) hold {zero_nodes} node(s) whose reference value is zero;"
            f" those are compared by absolute difference only (largest {zero_peak:.3g})."
        )
        summary_ko += (
            f" 기준값이 0인 노드가 {len(zero_columns)}개 항목에 {zero_nodes}개 있어"
            f" 절대 차이로만 비교했습니다(최대 {zero_peak:.3g})."
        )
    if disagreements:
        shown = disagreements[:5]
        more = len(disagreements) - len(shown)
        places_en = "; ".join(
            f"P={n['pressure_pa']:g} Pa, T={n['temperature_c']:g} C "
            f"({_LABEL_EN[n['reference']]} vs {_LABEL_EN[n['candidate']]})"
            for n in shown
        )
        places_ko = "; ".join(
            f"P={n['pressure_pa']:g} Pa, T={n['temperature_c']:g} C "
            f"({_LABEL_KO[n['reference']]}↔{_LABEL_KO[n['candidate']]})"
            for n in shown
        )
        summary_en += (
            f" The phase label differs at {len(disagreements)} node(s) (reference vs candidate): {places_en}"
            + (f"; and {more} more." if more else ".")
        )
        summary_ko += (
            f" 상 구분(기체·액체·2상)이 다른 {len(disagreements)}개 노드(기준↔후보): {places_ko}"
            + (f" 외 {more}개." if more else ".")
        )
    summary_en += (
        f" Filled columns: reference [{', '.join(filled['reference']) or 'none'}],"
        f" candidate [{', '.join(filled['candidate']) or 'none'}]."
    )
    summary_ko += (
        f" 채움 항목: 기준 [{', '.join(filled['reference']) or '없음'}],"
        f" 후보 [{', '.join(filled['candidate']) or '없음'}]."
    )
    for warning in warnings:
        summary_en += f" Warning: {warning['message_en']}"
        summary_ko += f" 주의: {warning['message_ko']}"
    regions = {
        name: {
            "nodes": region_nodes[name],
            "mean_rel_diff": (region_total[name] / region_count[name]) if region_count[name] else 0.0,
        }
        for name in region_names
    }
    return {
        "reference": {"path": ref_path.name, "label": ref.label, "phase": ref.phase},
        "candidate": {"path": cand_path.name, "label": cand.label, "phase": cand.phase},
        "grid": grid,
        "compared_nodes": len(pairs),
        "columns": columns,
        "present_phase": present_phase,
        "phase_disagreement": phase_disagreement,
        "skipped_columns": skipped,
        "regions": regions,
        "region_basis": "RS" if rs_index is not None else "unavailable",
        "filled": filled,
        "warnings": warnings,
        "heat": heat,
        "trace": None,
        "trace_note": (
            "File-based comparison carries no per-node engine trace; traces live "
            "with the generating run (pvt_engine TableReport.traces via trace_nodes)."
        ),
        "summary_en": summary_en,
        "summary_ko": summary_ko,
    }
