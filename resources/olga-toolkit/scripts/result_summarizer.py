"""
result_summarizer.py — Human-readable summary of OLGA .tpl / .ppl result files.

Usage:
    python result_summarizer.py <file.tpl|.ppl> [--json]

Outputs a formatted text summary (or JSON with --json) to stdout.
"""

import json
import math
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Graceful pyfas import (mirrors pattern from result_parser.py)
# ---------------------------------------------------------------------------

try:
    from pyfas import Tpl, Ppl
    _PYFAS_AVAILABLE = True
except ImportError:
    _PYFAS_AVAILABLE = False
    Tpl = None
    Ppl = None

# ---------------------------------------------------------------------------
# Optional numpy — prefer it for performance, fall back to pure Python
# ---------------------------------------------------------------------------

try:
    import numpy as _np
    _NUMPY_AVAILABLE = True
except ImportError:
    _np = None
    _NUMPY_AVAILABLE = False


# ---------------------------------------------------------------------------
# ResultParser shim
# ---------------------------------------------------------------------------
# result_parser.py lives alongside this script.  Import it when available;
# otherwise define a minimal shim so the module can still be imported and
# tested without the sibling file present.

try:
    from result_parser import ResultParser
except ImportError:
    class ResultParser:  # type: ignore[no-redef]
        """Minimal shim — replace with real result_parser.ResultParser."""

        def __init__(self, filepath: str):
            self.filepath = filepath
            self._ext = Path(filepath).suffix.lower()
            if not _PYFAS_AVAILABLE:
                raise ImportError(
                    "pyfas is required to parse OLGA result files. "
                    "Install it with: pip install pyfas"
                )
            if self._ext == ".tpl":
                self._obj = Tpl(filepath)
                self._obj.extract(*list(self._obj.trends.keys()))
            elif self._ext == ".ppl":
                self._obj = Ppl(filepath)
            else:
                raise ValueError(f"Unsupported extension: {self._ext!r} (expected .tpl or .ppl)")

        # ── Tpl accessors ────────────────────────────────────────────────

        @property
        def is_tpl(self) -> bool:
            return self._ext == ".tpl"

        @property
        def is_ppl(self) -> bool:
            return self._ext == ".ppl"

        @property
        def time(self):
            """Time vector (seconds) — numpy array for .tpl."""
            return self._obj.time

        @property
        def trends(self) -> dict:
            """For .tpl: {idx: label_string}."""
            if self.is_tpl:
                return self._obj.label
            return {}

        @property
        def trend_data(self) -> dict:
            """For .tpl: {idx: numpy_array}."""
            if self.is_tpl:
                return self._obj.data
            return {}

        # ── Ppl accessors ────────────────────────────────────────────────

        @property
        def branches(self) -> list:
            """For .ppl: list of branch name strings."""
            if self.is_ppl:
                return self._obj.branches
            return []

        @property
        def timesteps(self) -> list:
            """For .ppl: list of float timestep values (seconds)."""
            if self.is_ppl:
                return list(self._obj.timesteps)
            return []

        @property
        def data_in_df(self):
            """For .ppl: EasyDict of DataFrames."""
            if self.is_ppl:
                return self._obj.data_in_df
            return None

        @property
        def geometries(self) -> dict:
            """For .ppl: {branch: (x_array, y_array)}."""
            if self.is_ppl:
                return self._obj.geometries
            return {}

        def filter_data(self, pattern: str = "") -> dict:
            """For .ppl: {idx: raw_catalog_line}."""
            if self.is_ppl:
                return self._obj.filter_data(pattern)
            return {}


# ---------------------------------------------------------------------------
# Pure-Python statistics helpers (no numpy required)
# ---------------------------------------------------------------------------

def _mean(values) -> float:
    n = len(values)
    if n == 0:
        return float("nan")
    return sum(values) / n


def _std(values) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    m = _mean(values)
    variance = sum((x - m) ** 2 for x in values) / n
    return math.sqrt(variance)


def _to_list(arr) -> list:
    """Convert numpy array or list to plain Python list of floats."""
    if _NUMPY_AVAILABLE and isinstance(arr, _np.ndarray):
        return arr.tolist()
    return list(arr)


# ---------------------------------------------------------------------------
# Formatting constants
# ---------------------------------------------------------------------------

WIDE = 63


def _hr(char: str = "─", width: int = WIDE) -> str:
    return char * width


def _section(title: str) -> str:
    return f"\n{title}\n{_hr('─', len(title))}"


# ---------------------------------------------------------------------------
# Label parsing helpers
# ---------------------------------------------------------------------------

def _parse_label(label: str) -> tuple[str, str, str]:
    """
    Parse a pyfas catalog label string into (variable, position, unit).

    Tpl label example:
        "PT 'POSITION:' 'Observation1' '(Pa)' 'Pressure'"
    Ppl label example:
        "PT 'SECTION:' 'BRANCH:' 'old_offshore' '(Pa)' 'Pressure'"
    """
    import re
    tokens = re.findall(r"'([^']*)'", label)
    # First bare token is the variable name
    bare = label.split("'")[0].strip()
    variable = bare if bare else (tokens[0] if tokens else "?")

    # Position: token after POSITION: or BRANCH:
    position = ""
    for i, tok in enumerate(tokens):
        if tok in ("POSITION:", "BRANCH:") and i + 1 < len(tokens):
            position = tokens[i + 1]
            break

    # Unit: token wrapped in parens
    unit = ""
    for tok in tokens:
        if tok.startswith("(") and tok.endswith(")"):
            unit = tok[1:-1]
            break

    return variable, position, unit


# ---------------------------------------------------------------------------
# ResultSummarizer
# ---------------------------------------------------------------------------

class ResultSummarizer:
    """
    Produce human-readable and machine-readable summaries of OLGA result files.

    Supports .tpl (trend / time-series) and .ppl (profile / spatial) files.
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.parser = ResultParser(filepath)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def summarize(self) -> str:
        """Return a formatted multi-section human-readable summary string."""
        # Ensure stdout handles Unicode box-drawing characters on Windows.
        import io
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass

        if self.parser.is_tpl:
            return self._summarize_tpl()
        elif self.parser.is_ppl:
            return self._summarize_ppl()
        else:
            return f"Unsupported file type: {self.filepath}"

    def to_dict(self) -> dict:
        """Return a JSON-serializable structured summary."""
        if self.parser.is_tpl:
            return self._tpl_dict()
        elif self.parser.is_ppl:
            return self._ppl_dict()
        return {}

    # ------------------------------------------------------------------
    # Analytics helpers
    # ------------------------------------------------------------------

    def _compute_stats(self, values: list) -> dict:
        """
        Compute descriptive statistics for a list of numeric values.

        Returns:
            {min, max, mean, std, final, range}
        All values are plain Python floats.  NaN/inf are handled gracefully.
        """
        finite = [v for v in values if math.isfinite(v)]
        if not finite:
            nan = float("nan")
            return {"min": nan, "max": nan, "mean": nan, "std": nan,
                    "final": nan, "range": nan, "has_nan": True, "has_inf": False}

        has_nan = len(finite) < len(values)
        has_inf = any(math.isinf(v) for v in values)

        vmin = min(finite)
        vmax = max(finite)
        vmean = _mean(finite)
        vstd = _std(finite)
        vfinal = values[-1] if math.isfinite(values[-1]) else finite[-1]
        vrange = vmax - vmin

        return {
            "min": vmin,
            "max": vmax,
            "mean": vmean,
            "std": vstd,
            "final": vfinal,
            "range": vrange,
            "has_nan": has_nan,
            "has_inf": has_inf,
        }

    def _assess_convergence(self, time: list, values: list) -> dict:
        """
        Assess whether a time-series variable has converged.

        Criteria:
          - CONVERGED:     std(last 10%) / range < 0.05
          - OSCILLATING:   sign changes in derivative exceed threshold
          - NOT_CONVERGED: otherwise

        Returns:
            {status, detail}
        """
        n = len(values)
        if n < 4:
            return {"status": "INSUFFICIENT_DATA", "detail": "Too few data points"}

        finite = [v for v in values if math.isfinite(v)]
        if not finite:
            return {"status": "UNKNOWN", "detail": "All values non-finite"}

        vrange = max(finite) - min(finite)

        # Last 10% window (minimum 2 points)
        window = max(2, n // 10)
        tail = [v for v in values[-window:] if math.isfinite(v)]
        tail_std = _std(tail)

        # Convergence check
        if vrange < 1e-12:
            return {"status": "CONVERGED", "detail": "Variable is constant"}

        ratio = tail_std / vrange
        if ratio < 0.05:
            # Check for oscillation in the tail
            if len(tail) >= 3:
                diffs = [tail[i + 1] - tail[i] for i in range(len(tail) - 1)]
                sign_changes = sum(
                    1 for i in range(len(diffs) - 1)
                    if diffs[i] * diffs[i + 1] < 0
                )
                if sign_changes >= len(diffs) * 0.6:
                    return {
                        "status": "OSCILLATING",
                        "detail": f"Sign changes in tail: {sign_changes}/{len(diffs)-1}",
                    }
            return {
                "status": "CONVERGED",
                "detail": f"Tail std/range = {ratio:.3f} (< 0.05)",
            }

        # Check for oscillation across full series
        finite_all = [v for v in values if math.isfinite(v)]
        if len(finite_all) >= 3:
            diffs_all = [finite_all[i + 1] - finite_all[i] for i in range(len(finite_all) - 1)]
            sign_changes_all = sum(
                1 for i in range(len(diffs_all) - 1)
                if diffs_all[i] * diffs_all[i + 1] < 0
            )
            if sign_changes_all >= len(diffs_all) * 0.4:
                return {
                    "status": "OSCILLATING",
                    "detail": f"Sign changes: {sign_changes_all}/{len(diffs_all)-1}",
                }

        return {
            "status": "NOT_CONVERGED",
            "detail": f"Tail std/range = {ratio:.3f} (>= 0.05)",
        }

    def _detect_anomalies(self, time: list, values: list) -> list:
        """
        Detect anomalies in a time-series.

        Checks:
          - NaN or infinite values
          - Constant-zero variable (never changes)
          - Sudden jumps (> 50% change relative to current value in one step)

        Returns list of anomaly description strings (empty if none).
        """
        anomalies = []

        # NaN / inf check
        n_nan = sum(1 for v in values if math.isnan(v))
        n_inf = sum(1 for v in values if math.isinf(v))
        if n_nan:
            anomalies.append(f"Contains {n_nan} NaN value(s)")
        if n_inf:
            anomalies.append(f"Contains {n_inf} infinite value(s)")

        finite = [v for v in values if math.isfinite(v)]
        if not finite:
            return anomalies

        # Constant-zero check
        vrange = max(finite) - min(finite)
        if vrange == 0.0 and abs(finite[0]) < 1e-12:
            anomalies.append("Variable is constant zero throughout simulation")
            return anomalies

        # Sudden jump check (>50% of |current| in one timestep)
        for i in range(1, len(values)):
            prev, curr = values[i - 1], values[i]
            if not (math.isfinite(prev) and math.isfinite(curr)):
                continue
            if abs(prev) < 1e-12:
                continue
            delta_frac = abs(curr - prev) / abs(prev)
            if delta_frac > 0.5:
                t_val = time[i] if i < len(time) else "?"
                anomalies.append(
                    f"Sudden jump at t={_fmt_time(t_val)}: "
                    f"{prev:.3g} -> {curr:.3g} ({delta_frac*100:.0f}% change)"
                )

        return anomalies

    # ------------------------------------------------------------------
    # .tpl summary
    # ------------------------------------------------------------------

    def _summarize_tpl(self) -> str:
        p = self.parser
        time = _to_list(p.time)
        t0, t_end = (time[0], time[-1]) if time else (0.0, 0.0)
        n_points = len(time)
        hours = (t_end - t0) / 3600.0

        bar = "═" * WIDE
        lines = [
            bar,
            "  Simulation Results Summary",
            bar,
            "",
            f"  File: {self.filepath}",
            f"  Type: Trend data",
            f"  Simulation Duration: {t0:g} - {t_end:g} s ({hours:.1f} hours)",
            f"  Data Points: {n_points}",
        ]

        # Key Metrics table
        lines.append(_section("Key Metrics"))
        col_var = 16
        col_pos = 18
        col_num = 12
        col_unit = 10
        header = (
            f"  {'Variable':<{col_var}} {'Position':<{col_pos}}"
            f" {'Min':>{col_num}} {'Max':>{col_num}} {'Avg':>{col_num}}"
            f" {'Final':>{col_num}} {'Unit':<{col_unit}}"
        )
        lines.append(header)

        # Gather stats per variable
        all_stats = []
        for idx, label in p.trends.items():
            variable, position, unit = _parse_label(label)
            raw = p.trend_data.get(idx)
            if raw is None:
                continue
            vals = _to_list(raw)
            stats = self._compute_stats(vals)
            all_stats.append((variable, position, unit, stats, vals))
            row = (
                f"  {variable:<{col_var}} {position:<{col_pos}}"
                f" {_fmt_eng(stats['min']):>{col_num}}"
                f" {_fmt_eng(stats['max']):>{col_num}}"
                f" {_fmt_eng(stats['mean']):>{col_num}}"
                f" {_fmt_eng(stats['final']):>{col_num}}"
                f" {unit:<{col_unit}}"
            )
            lines.append(row)

        # Convergence Assessment
        lines.append(_section("Convergence Assessment"))
        if not all_stats:
            lines.append("  No data available for convergence assessment.")
        else:
            conv_results = []
            for variable, position, unit, stats, vals in all_stats:
                result = self._assess_convergence(time, vals)
                conv_results.append((variable, position, result))

            statuses = [r["status"] for _, _, r in conv_results]
            if all(s == "CONVERGED" for s in statuses):
                overall = "CONVERGED"
            elif any(s == "OSCILLATING" for s in statuses):
                overall = "OSCILLATING"
            elif any(s == "NOT_CONVERGED" for s in statuses):
                overall = "NOT_CONVERGED"
            else:
                overall = statuses[0] if statuses else "UNKNOWN"

            lines.append(f"  Status: {overall}")

            for variable, position, result in conv_results:
                tag = f"{variable} @ {position}" if position else variable
                lines.append(f"  - {tag}: {result['status']} — {result['detail']}")

            # Pressure drop across system (first PT variable)
            for variable, position, unit, stats, vals in all_stats:
                if variable == "PT":
                    initial = vals[0] if vals else float("nan")
                    final = stats["final"]
                    if math.isfinite(initial) and math.isfinite(final):
                        drop = abs(final - initial)
                        lines.append(f"  - Pressure drop: {_fmt_eng(drop)} {unit} across system")
                    break

        # Anomalies
        lines.append(_section("Anomalies"))
        all_anomalies = []
        for variable, position, unit, stats, vals in all_stats:
            tag = f"{variable} @ {position}" if position else variable
            found = self._detect_anomalies(time, vals)
            for a in found:
                all_anomalies.append(f"{tag}: {a}")

        if all_anomalies:
            for a in all_anomalies:
                lines.append(f"  - {a}")
        else:
            lines.append("  - None detected")

        lines.append(f"\n{bar}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # .ppl summary
    # ------------------------------------------------------------------

    def _summarize_ppl(self) -> str:
        p = self.parser
        branches = p.branches
        timesteps = p.timesteps
        n_ts = len(timesteps)
        t0 = timesteps[0] if timesteps else 0.0
        t_end = timesteps[-1] if timesteps else 0.0

        # Pipeline length from first branch geometry
        pipe_length = 0.0
        if branches and p.geometries:
            geo = p.geometries.get(branches[0])
            if geo is not None:
                xs = _to_list(geo[0])
                pipe_length = max(xs) if xs else 0.0

        bar = "═" * WIDE
        branch_names = ", ".join(branches)
        lines = [
            bar,
            "  Profile Results Summary",
            bar,
            "",
            f"  File: {self.filepath}",
            f"  Type: Profile data",
            f"  Branches: {len(branches)} ({branch_names})",
            f"  Timesteps: {n_ts} ({t0:g} - {t_end:g} s)",
            f"  Pipeline Length: {pipe_length:.2f} m",
        ]

        # Profile Summary using last timestep
        lines.append(_section("Profile Summary (final timestep)"))

        col_var = 12
        col_minp = 18
        col_maxp = 18
        col_delt = 12
        col_unit = 8
        header = (
            f"  {'Variable':<{col_var}}"
            f" {'Min @ Position':<{col_minp}}"
            f" {'Max @ Position':<{col_maxp}}"
            f" {'Delta':>{col_delt}}"
            f" {'Unit':<{col_unit}}"
        )
        lines.append(header)

        if not branches or p.data_in_df is None:
            lines.append("  (no profile data available)")
        else:
            branch = branches[0]
            df_dict = p.data_in_df
            # collect available variable names in this branch
            try:
                branch_data = df_dict[branch]
                var_names = list(branch_data.keys()) if hasattr(branch_data, "keys") else []
            except (KeyError, TypeError):
                var_names = []

            last_t = timesteps[-1] if timesteps else None

            # Also gather units from filter_data catalog
            unit_map = {}
            for idx, raw_line in p.filter_data("").items():
                _, _, unit = _parse_label(raw_line)
                # variable name is the first token
                var = raw_line.split("'")[0].strip()
                if var and unit:
                    unit_map[var] = unit

            for var in var_names:
                try:
                    df = branch_data[var]
                    if last_t is None or last_t not in df.columns:
                        # Use the last available column
                        col = df.columns[-1]
                    else:
                        col = last_t
                    series = df[col]
                    vals = _to_list(series.values)
                    positions = _to_list(series.index)
                except Exception:
                    continue

                finite_pairs = [
                    (v, pos)
                    for v, pos in zip(vals, positions)
                    if math.isfinite(v)
                ]
                if not finite_pairs:
                    continue

                vmin, pos_min = min(finite_pairs, key=lambda x: x[0])
                vmax, pos_max = max(finite_pairs, key=lambda x: x[0])
                delta = vmax - vmin
                unit = unit_map.get(var, "")

                min_str = f"{_fmt_eng(vmin)} @ {pos_min:.0f}m"
                max_str = f"{_fmt_eng(vmax)} @ {pos_max:.0f}m"

                row = (
                    f"  {var:<{col_var}}"
                    f" {min_str:<{col_minp}}"
                    f" {max_str:<{col_maxp}}"
                    f" {_fmt_eng(delta):>{col_delt}}"
                    f" {unit:<{col_unit}}"
                )
                lines.append(row)

        lines.append(f"\n{bar}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # to_dict helpers
    # ------------------------------------------------------------------

    def _tpl_dict(self) -> dict:
        p = self.parser
        time = _to_list(p.time)
        t0 = time[0] if time else 0.0
        t_end = time[-1] if time else 0.0

        variables = []
        all_convergence = []

        for idx, label in p.trends.items():
            variable, position, unit = _parse_label(label)
            raw = p.trend_data.get(idx)
            if raw is None:
                continue
            vals = _to_list(raw)
            stats = self._compute_stats(vals)
            conv = self._assess_convergence(time, vals)
            anomalies = self._detect_anomalies(time, vals)

            variables.append({
                "index": idx,
                "variable": variable,
                "position": position,
                "unit": unit,
                "stats": {
                    "min": stats["min"],
                    "max": stats["max"],
                    "mean": stats["mean"],
                    "std": stats["std"],
                    "final": stats["final"],
                    "range": stats["range"],
                },
                "convergence": conv,
                "anomalies": anomalies,
            })
            all_convergence.append(conv["status"])

        if all(s == "CONVERGED" for s in all_convergence):
            overall_conv = "CONVERGED"
        elif any(s == "OSCILLATING" for s in all_convergence):
            overall_conv = "OSCILLATING"
        elif any(s == "NOT_CONVERGED" for s in all_convergence):
            overall_conv = "NOT_CONVERGED"
        else:
            overall_conv = all_convergence[0] if all_convergence else "UNKNOWN"

        return {
            "file": self.filepath,
            "type": "trend",
            "time_start": t0,
            "time_end": t_end,
            "duration_hours": (t_end - t0) / 3600.0,
            "n_points": len(time),
            "overall_convergence": overall_conv,
            "variables": variables,
        }

    def _ppl_dict(self) -> dict:
        p = self.parser
        timesteps = p.timesteps
        branches = p.branches
        t0 = timesteps[0] if timesteps else 0.0
        t_end = timesteps[-1] if timesteps else 0.0

        pipe_length = 0.0
        if branches and p.geometries:
            geo = p.geometries.get(branches[0])
            if geo is not None:
                xs = _to_list(geo[0])
                pipe_length = max(xs) if xs else 0.0

        branch_summaries = []
        for branch in branches:
            try:
                branch_data = p.data_in_df[branch]
                var_names = list(branch_data.keys()) if hasattr(branch_data, "keys") else []
            except (KeyError, TypeError):
                var_names = []

            unit_map = {}
            for idx, raw_line in p.filter_data("").items():
                _, _, unit = _parse_label(raw_line)
                var = raw_line.split("'")[0].strip()
                if var and unit:
                    unit_map[var] = unit

            variables = []
            last_t = timesteps[-1] if timesteps else None
            for var in var_names:
                try:
                    df = branch_data[var]
                    col = last_t if (last_t is not None and last_t in df.columns) else df.columns[-1]
                    series = df[col]
                    vals = _to_list(series.values)
                    positions = _to_list(series.index)
                except Exception:
                    continue

                finite_pairs = [(v, pos) for v, pos in zip(vals, positions) if math.isfinite(v)]
                if not finite_pairs:
                    continue

                vmin, pos_min = min(finite_pairs, key=lambda x: x[0])
                vmax, pos_max = max(finite_pairs, key=lambda x: x[0])

                variables.append({
                    "variable": var,
                    "unit": unit_map.get(var, ""),
                    "min": vmin,
                    "min_position_m": pos_min,
                    "max": vmax,
                    "max_position_m": pos_max,
                    "delta": vmax - vmin,
                })

            branch_summaries.append({"branch": branch, "variables": variables})

        return {
            "file": self.filepath,
            "type": "profile",
            "n_branches": len(branches),
            "branches": branches,
            "n_timesteps": len(timesteps),
            "time_start": t0,
            "time_end": t_end,
            "pipeline_length_m": pipe_length,
            "branch_summaries": branch_summaries,
        }


# ---------------------------------------------------------------------------
# Number formatting helpers
# ---------------------------------------------------------------------------

def _fmt_eng(v) -> str:
    """Format a float in engineering notation with 3 significant figures."""
    if not math.isfinite(v):
        return "NaN" if math.isnan(v) else "Inf"
    if v == 0.0:
        return "0"
    mag = abs(v)
    # Use fixed notation for numbers in a readable range
    if 0.001 <= mag < 1e6:
        formatted = f"{v:.4g}"
    else:
        formatted = f"{v:.3e}"
    return formatted


def _fmt_time(t) -> str:
    """Format a time value in seconds to a short string."""
    try:
        t = float(t)
    except (TypeError, ValueError):
        return str(t)
    if t >= 3600:
        return f"{t/3600:.2f}h"
    elif t >= 60:
        return f"{t/60:.1f}min"
    return f"{t:.1f}s"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python result_summarizer.py <file.tpl|.ppl> [--json]",
            file=sys.stderr,
        )
        sys.exit(1)

    filepath = sys.argv[1]
    if not Path(filepath).exists():
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    flag = sys.argv[2] if len(sys.argv) > 2 else ""

    # Ensure stdout handles Unicode box-drawing characters on Windows terminals.
    import io
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    elif sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    summarizer = ResultSummarizer(filepath)

    if flag == "--json":
        print(json.dumps(summarizer.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(summarizer.summarize())


if __name__ == "__main__":
    main()
