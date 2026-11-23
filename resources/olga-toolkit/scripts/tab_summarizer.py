"""
tab_summarizer.py -- Human-readable summary of an OLGA .tab PVT table file.

Usage:
    python tab_summarizer.py <file.tab>
    python tab_summarizer.py <file.tab> --json

Exit codes:
    0 -- success
    1 -- file not found or usage error
    2 -- parse error
"""

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import parser
# ---------------------------------------------------------------------------

try:
    from tab_parser import TabParser
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from tab_parser import TabParser


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_size(nbytes):
    """Format file size in human-readable form."""
    if nbytes < 1024:
        return f"{nbytes} B"
    elif nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f} KB"
    else:
        return f"{nbytes / (1024 * 1024):.1f} MB"


def _pa_to_bar(pa):
    """Convert Pascals to bar."""
    return pa / 1.0e5


def _fmt_num(v):
    """Format a number: drop trailing zeros."""
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _fmt_mol_percent(components, moles):
    """Format component list with mol% values."""
    parts = []
    for i, comp in enumerate(components):
        if i < len(moles):
            pct = moles[i] * 100.0 if moles[i] <= 1.0 else moles[i]
            parts.append(f"{comp} ({pct:.1f} mol%)")
        else:
            parts.append(comp)
    return ", ".join(parts)


def _fmt_mol_weights(components, mol_weights):
    """Format component molecular weights."""
    parts = []
    for i, comp in enumerate(components):
        if i < len(mol_weights):
            parts.append(f"{comp}={_fmt_num(mol_weights[i])}")
        else:
            parts.append(comp)
    return ", ".join(parts)


def _formulation_label(code):
    """Expand PVT formulation code to descriptive text."""
    labels = {
        "PH": "Pressure-Enthalpy",
        "PT": "Pressure-Temperature",
    }
    desc = labels.get(code.upper(), "")
    if desc:
        return f"{code} ({desc})"
    return code


# ---------------------------------------------------------------------------
# TabSummarizer
# ---------------------------------------------------------------------------

class TabSummarizer:
    """Generate human-readable summary of an OLGA .tab PVT file."""

    def __init__(self, tab_path):
        """Parse file (header only for speed)."""
        self.tab_path = str(tab_path)
        self._tab = TabParser(tab_path, header_only=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def summarize(self):
        """Return formatted text summary."""
        t = self._tab
        filename = Path(self.tab_path).name

        lines = []
        lines.append(f"PVT Table Summary: {filename}")

        lines.append(f"  Label:        {t.label or '(none)'}")
        lines.append(f"  Phase:        {t.phase or '(none)'}")
        lines.append(f"  Formulation:  {_formulation_label(t.formulation) if t.formulation else '(none)'}")
        lines.append("")

        # Components
        comps = t.components
        moles = t.moles
        if comps:
            lines.append(f"  Components:   {_fmt_mol_percent(comps, moles)}")
        mw = t.mol_weights
        if mw:
            lines.append(f"  Mol Weights:  {_fmt_mol_weights(comps, mw)}")
        lines.append("")

        # Pressure grid
        grid = t.pressure_grid
        if grid:
            p_min_bar = _pa_to_bar(min(grid))
            p_max_bar = _pa_to_bar(max(grid))
            lines.append(f"  Pressure:     {_fmt_num(p_min_bar)} - {_fmt_num(p_max_bar)} bar ({len(grid)} points)")

        temperatures = t.temperature_grid
        if temperatures:
            lines.append(f"  Temperature:  {_fmt_num(min(temperatures))} - {_fmt_num(max(temperatures))} C ({len(temperatures)} points)")
        bt = t.bubble_temperatures
        if bt:
            lines.append(f"  Bubble T:     {_fmt_num(min(bt))} - {_fmt_num(max(bt))} C (bubble range)")

        # Enthalpy grid
        nh = t.n_enthalpies
        if nh:
            unique = set(nh)
            if len(unique) == 1:
                lines.append(f"  Enthalpy:     {nh[0]} points per pressure level")
            else:
                lines.append(f"  Enthalpy:     {min(nh)}-{max(nh)} points per pressure level")

        # Mesh type
        if t.mesh_type:
            lines.append(f"  Mesh Type:    {t.mesh_type}")
        lines.append("")

        # Properties
        props = t.available_properties
        if props:
            lines.append(f"  Properties:   {', '.join(props)} [{len(props)} found]")

        # File size
        lines.append(f"  File Size:    {_fmt_size(t._raw_size)}")

        return "\n".join(lines)

    def to_dict(self):
        """Return summary as dict."""
        t = self._tab
        grid = t.pressure_grid
        bt = t.bubble_temperatures
        nh = t.n_enthalpies

        return {
            "filepath": self.tab_path,
            "filename": Path(self.tab_path).name,
            "label": t.label,
            "phase": t.phase,
            "formulation": t.formulation,
            "components": [
                {"name": c, "mole_fraction": t.moles[i] if i < len(t.moles) else None}
                for i, c in enumerate(t.components)
            ],
            "mol_weights": t.mol_weights,
            "pressure": {
                "min_pa": min(grid) if grid else None,
                "max_pa": max(grid) if grid else None,
                "min_bar": _pa_to_bar(min(grid)) if grid else None,
                "max_bar": _pa_to_bar(max(grid)) if grid else None,
                "n_points": len(grid),
            },
            "bubble_temperature": {
                "min_c": min(bt) if bt else None,
                "max_c": max(bt) if bt else None,
                "n_points": len(bt),
            },
            "temperature": {
                "min_c": min(t.temperature_grid) if t.temperature_grid else None,
                "max_c": max(t.temperature_grid) if t.temperature_grid else None,
                "n_points": len(t.temperature_grid),
            },
            "columns": t.columns,
            "point_data_loaded": False,
            "enthalpy_per_pressure": sorted(set(nh)) if nh else [],
            "mesh_type": t.mesh_type,
            "available_properties": t.available_properties,
            "file_size_bytes": t._raw_size,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: python tab_summarizer.py <file.tab> [--json]", file=sys.stderr)
        sys.exit(1)

    filepath = args[0]
    if not Path(filepath).exists():
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    flags = set(args[1:])

    try:
        summarizer = TabSummarizer(filepath)
    except Exception as exc:
        print(f"Error: failed to parse {filepath}: {exc}", file=sys.stderr)
        sys.exit(2)

    if "--json" in flags:
        print(json.dumps(summarizer.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(summarizer.summarize())


if __name__ == "__main__":
    main()
