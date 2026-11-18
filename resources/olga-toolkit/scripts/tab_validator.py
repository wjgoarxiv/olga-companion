"""
tab_validator.py -- Validation rule engine for OLGA .tab PVT table files.

Usage:
    python tab_validator.py <file.tab>
    python tab_validator.py <file.tab> --genkey model.genkey
    python tab_validator.py <file.tab> --json

Exit codes:
    0 -- no errors found (warnings/info are OK)
    1 -- one or more errors found
    2 -- file not found or parse error
"""

import json
import math
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import parsers
# ---------------------------------------------------------------------------

try:
    from tab_parser import TabParser
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from tab_parser import TabParser

# Genkey parser is optional (only needed for cross-referencing)
_GenkeyParser = None


def _get_genkey_parser():
    global _GenkeyParser
    if _GenkeyParser is not None:
        return _GenkeyParser
    try:
        from genkey_parser import GenkeyParser
        _GenkeyParser = GenkeyParser
    except ImportError:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from genkey_parser import GenkeyParser
            _GenkeyParser = GenkeyParser
        except ImportError:
            _GenkeyParser = None
    return _GenkeyParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _numeric(val):
    """Extract a plain number from a parsed value."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict) and "value" in val:
        v = val["value"]
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _extract_genkey_boundary_values(genkey_parser, key, normalize=False):
    """Extract all boundary values for a given key (PRESSURE/TEMPERATURE) from genkey nodes."""
    values = []
    for nd in genkey_parser.nodes:
        for child in nd.get("children", []):
            params = child.get("params", {})
            raw = params.get(key)
            if raw is not None:
                num = _numeric(raw)
                if num is not None:
                    if normalize:
                        unit = str(raw.get("unit", "")).upper() if isinstance(raw, dict) else ""
                        conversions = ({"PA": (1, 0), "KPA": (1000, 0), "MPA": (1e6, 0),
                                        "BAR": (1e5, 0), "BARA": (1e5, 0)}
                                       if key == "PRESSURE" else {"C": (1, 0), "K": (1, -273.15)})
                        if unit not in conversions or not math.isfinite(num):
                            raise ValueError(f"Unsupported or nonfinite genkey {key} boundary ({unit or 'no unit'})")
                        scale, offset = conversions[unit]
                        num = num * scale + offset
                    values.append(num)
                elif normalize:
                    raise ValueError(f"Nonnumeric genkey {key} boundary")
    return values


# Keyword COLUMNS from the public OLGA list. role "water" is a water-phase
# column; RSW stays "both" because it is the water mass fraction in the gas.
# unit is the manual unit for that keyword. A whole column equal to one of
# _COLUMN_DEFAULTS is a placeholder fill, not one node that happens to match.
_KEYWORD_COLUMNS = {
    "PT": ("Pa", "axis"),
    "TM": ("C", "axis"),
    "ROG": ("kg/m3", "both"),
    "ROHL": ("kg/m3", "both"),
    "ROWT": ("kg/m3", "water"),
    "DROGDP": ("s2/m2", "both"),
    "DROHLDP": ("s2/m2", "both"),
    "DROWTDP": ("s2/m2", "water"),
    "DROGDT": ("kg/m3/C", "both"),
    "DROHLDT": ("kg/m3/C", "both"),
    "DROWTDT": ("kg/m3/C", "water"),
    "RS": ("kg/kg", "both"),
    "RSW": ("kg/kg", "both"),
    "VISG": ("Ns/m2", "both"),
    "VISHL": ("Ns/m2", "both"),
    "VISWT": ("Ns/m2", "water"),
    "CPG": ("J/kg/C", "both"),
    "CPHL": ("J/kg/C", "both"),
    "CPWT": ("J/kg/C", "water"),
    "HG": ("J/kg", "both"),
    "HHL": ("J/kg", "both"),
    "HWT": ("J/kg", "water"),
    "TCG": ("W/m/C", "both"),
    "TCHL": ("W/m/C", "both"),
    "TCWT": ("W/m/C", "water"),
    "SIGGHL": ("N/m", "both"),
    "SIGGWT": ("N/m", "water"),
    "SIGHLWT": ("N/m", "water"),
    "SEG": ("J/kg/C", "both"),
    "SEHL": ("J/kg/C", "both"),
    "SEWT": ("J/kg/C", "water"),
}

_COLUMN_DEFAULTS = {
    "ROG": (1.0,),
    "ROHL": (800.0,),
    "ROWT": (1000.0,),
    "VISG": (1e-5,),
    "CPG": (2000.0, 4200.0),
    "CPHL": (2000.0, 4200.0),
    "CPWT": (2000.0, 4200.0),
    "TCHL": (0.13,),
    "SIGGHL": (0.02,),
    "SIGGWT": (0.02,),
    "SIGHLWT": (0.02,),
    "RS": (1.0e6,),
}

# Header keys seen across all 42 keyword .tab samples shipped with OLGA
# 2022.1.0 (checked 2026-10-31), plus PVTFORMULATION, a known OLGA header key.
# NOPRES and NOTEMP appear in none of the 42 and break the header, so V032
# reports them as errors. Any other unknown STANDARD key is a warning.
# The scope stays STANDARD-only: fixed-format tables never start with PVTTABLE LABEL.
_KEYWORD_HEADER_KEYS = {
    "LABEL", "PHASE", "PVTFORMULATION", "EOS", "COMPONENTS", "MOLES",
    "MOLWEIGHT", "DENSITY", "STDPRESSURE", "STDTEMPERATURE", "GOR", "GLR",
    "WC", "STDGASDENSITY", "STDOILDENSITY", "STDWATDENSITY",
    "CRITICALPRESSURE", "CRITICALTEMPERATURE", "MESHTYPE",
    "TOTWATERFRACTION", "PRESSURE", "TEMPERATURE", "BUBBLEPRESSURES",
    "BUBBLETEMPERATURES", "DEWPRESSURES", "DEWTEMPERATURES", "COLUMNS",
}


def _is_quoted(value) -> bool:
    return isinstance(value, str) and len(value) >= 2 and value.startswith('"') and value.endswith('"')


def _format_number(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return format(float(value), ".6g")


def _same_number(left, right):
    return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-12)


def _declared_count(raw):
    if isinstance(raw, dict) and "value" in raw:
        raw = raw["value"]
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if math.isfinite(raw) else None
    if isinstance(raw, list) and len(raw) == 1 and not isinstance(raw[0], bool):
        if isinstance(raw[0], (int, float)) and math.isfinite(raw[0]):
            return float(raw[0])
    return None


def _matching_default(name, values):
    placeholders = _COLUMN_DEFAULTS.get(name)
    if not placeholders or not values:
        return None
    for placeholder in placeholders:
        if all(_same_number(value, placeholder) for value in values):
            return placeholder
    return None


def _step_indices(values):
    """Indexes where a repeated value jumps to another repeated or plateau value."""
    found = []
    count = len(values)
    if count < 3:
        return found
    for index in range(1, count):
        if values[index] == values[index - 1]:
            continue
        left = 1
        cursor = index - 1
        while cursor > 0 and values[cursor - 1] == values[index - 1]:
            left += 1
            cursor -= 1
        right = 1
        cursor = index
        while cursor + 1 < count and values[cursor + 1] == values[index]:
            right += 1
            cursor += 1
        if left >= 2 or right >= 2:
            found.append(index)
    return found


_DENSITIES = {"ROG", "ROHL", "ROWT"}
_VISCOSITIES = {"VISG", "VISHL", "VISWT"}
_HEAT_CAPACITIES = {"CPG", "CPHL", "CPWT"}
_CONDUCTIVITIES = {"TCG", "TCHL", "TCWT"}
_SURFACE_TENSIONS = {"SIGGHL", "SIGGWT", "SIGHLWT"}
_MASS_FRACTIONS = {"RS", "RSW"}
_MAGNITUDE_LIMIT = 1e30
_FRACTION_TOLERANCE = 1e-9


def _physical_fault(name, value):
    """Return an error phrase for one impossible property cell, or None.

    Exact zero stays a warning for surface tension. Density, viscosity,
    heat capacity, and conductivity are errors at zero as well.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"Property {name} is non-finite or has absolute value above 1e30"
    if not math.isfinite(value) or abs(value) > _MAGNITUDE_LIMIT:
        return f"Property {name} is non-finite or has absolute value above 1e30"
    if name in _DENSITIES and value <= 0:
        return f"Property {name} density must be positive"
    if name in _VISCOSITIES and value <= 0:
        return f"Property {name} viscosity must be positive"
    if name in _HEAT_CAPACITIES and value <= 0:
        return f"Property {name} heat capacity must be positive"
    if name in _CONDUCTIVITIES and value <= 0:
        return f"Property {name} thermal conductivity must be positive"
    if name in _SURFACE_TENSIONS and value < 0:
        return f"Property {name} surface tension must not be negative"
    if name in _MASS_FRACTIONS and not (
        -_FRACTION_TOLERANCE <= value <= 1 + _FRACTION_TOLERANCE
    ):
        return f"Property {name} mass fraction must stay within [0, 1]"
    return None


def _header_number(raw):
    unit = ""
    if isinstance(raw, dict) and "value" in raw:
        unit = str(raw.get("unit") or "").strip()
        raw = raw["value"]
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw), unit
    if isinstance(raw, list) and len(raw) == 1 and not isinstance(raw[0], bool):
        if isinstance(raw[0], (int, float)):
            return float(raw[0]), unit
    return None


def _critical_temperature_impossible(value, unit):
    if not math.isfinite(value):
        return True
    if unit.strip().upper() in {"C", "CELSIUS", "DEGC"}:
        return value <= -273.15
    return value <= 0


# ---------------------------------------------------------------------------
# TabValidator
# ---------------------------------------------------------------------------

class TabValidator:
    """Validate an OLGA .tab PVT table file.

    Parameters
    ----------
    tab_path : str
        Path to .tab file.
    genkey_path : str or None
        Optional path to .genkey file for cross-referencing P/T ranges.
    """

    # Minimum required property tables for a usable PVT file
    _REQUIRED_PROPERTIES = {"ROG", "ROL"}

    def __init__(self, tab_path, genkey_path=None):
        self.tab_path = str(tab_path)
        self.genkey_path = str(genkey_path) if genkey_path else None
        self._findings = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self):
        """Run all checks. Returns dict with errors, warnings, info lists."""
        self._findings = []

        try:
            tab = TabParser(self.tab_path, header_only=False)
        except Exception as exc:
            self._add("V000", "ERROR", "parse",
                       f"Failed to parse .tab file: {exc}")
            return self._result()

        genkey = None
        if self.genkey_path:
            GenkeyParser = _get_genkey_parser()
            if GenkeyParser is None:
                self._add("V000", "WARNING", "parse",
                           "genkey_parser module not available; skipping cross-reference checks")
            else:
                try:
                    genkey = GenkeyParser(self.genkey_path)
                except Exception as exc:
                    self._add("V000", "WARNING", "parse",
                               f"Failed to parse .genkey file: {exc}")

        self._check_standard_formulation(tab)
        self._check_first_line(tab)
        self._check_label(tab)
        self._check_header_strings(tab)
        self._check_unknown_header_keys(tab)
        self._check_components(tab)
        self._check_moles(tab)
        self._check_pressure_grid(tab)
        self._check_noenthalpy(tab)
        self._check_required_properties(tab)
        self._check_keyword_columns(tab)
        self._check_keyword_grid(tab)
        self._check_property_values(tab)
        self._check_keyword_nodes(tab)
        self._check_critical_state(tab)

        if genkey:
            try:
                self._check_pressure_coverage(tab, genkey)
                self._check_temperature_coverage(tab, genkey)
            except ValueError as exc:
                self._add("V010", "ERROR", "coverage", str(exc))

        return self._result()

    def is_valid(self):
        """Returns True if no errors."""
        result = self.validate()
        return len(result["errors"]) == 0

    def summary(self):
        """Return a human-readable validation report."""
        result = self._result() if self._findings else self.validate()

        filename = Path(self.tab_path).name
        errors = result["errors"]
        warnings = result["warnings"]
        infos = result["info"]

        width = max(len(filename) + 22, 40)
        header_line = "=" * width

        lines = [
            f"Validation Report: {filename}",
            header_line,
            f"ERRORS:   {len(errors)}",
            f"WARNINGS: {len(warnings)}",
            f"INFO:     {len(infos)}",
        ]

        def _section(title, bucket):
            if not bucket:
                return
            lines.append("")
            lines.append(title)
            lines.append("-" * len(title))
            for f in bucket:
                lines.append(f"[{f['rule_id']}] {f['message']}")
                if f.get("location"):
                    lines.append(f"       Location : {f['location']}")
                if f.get("suggestion"):
                    lines.append(f"       Suggestion: {f['suggestion']}")

        _section("ERRORS", errors)
        _section("WARNINGS", warnings)
        _section("INFO", infos)

        if not self._findings:
            lines.append("")
            lines.append("No issues found.")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal: finding factory and result builder
    # ------------------------------------------------------------------

    def _add(self, rule_id, severity, category, message,
             location="", suggestion=""):
        self._findings.append({
            "rule_id": rule_id,
            "severity": severity,
            "category": category,
            "message": message,
            "location": location,
            "suggestion": suggestion,
        })

    def _result(self):
        return {
            "filepath": self.tab_path,
            "errors": [f for f in self._findings if f["severity"] == "ERROR"],
            "warnings": [f for f in self._findings if f["severity"] == "WARNING"],
            "info": [f for f in self._findings if f["severity"] == "INFO"],
            "findings": self._findings,
        }

    # ------------------------------------------------------------------
    # V011: do not infer PT unless both axes exist
    # ------------------------------------------------------------------

    def _check_standard_formulation(self, tab):
        if tab.mesh_type.upper() != "STANDARD" or tab.formulation:
            return
        self._add(
            "V011", "ERROR", "header",
            "STANDARD formulation is empty: both PRESSURE and TEMPERATURE axes are required",
            location="(header)",
            suggestion="Do not infer PT unless both axes are present",
        )

    # V001: PVTTABLE LABEL must be present
    # ------------------------------------------------------------------

    def _check_label(self, tab):
        if not tab.label:
            self._add("V001", "ERROR", "header",
                       "PVTTABLE LABEL is missing",
                       location="(header)",
                       suggestion="Add LABEL = <name> to the PVTTABLE header")

    # ------------------------------------------------------------------
    # V030: the first non-blank line must be PVTTABLE LABEL (STANDARD only)
    # ------------------------------------------------------------------

    def _check_first_line(self, tab):
        if tab.mesh_type.upper() != "STANDARD":
            return
        if getattr(tab, "header_at_top", True):
            return
        self._add("V030", "ERROR", "header",
                   "OLGA rejected a table whose first non-blank line is not PVTTABLE LABEL "
                   "(WARNING 1051: Wrong header). OLGA reads the keyword header from line 1",
                   location="(line 1)",
                   suggestion='Start the file with PVTTABLE LABEL = "<label>",PHASE = ... '
                              "and put provenance comments after line 1")

    # ------------------------------------------------------------------
    # V031: LABEL and COMPONENTS should be quoted (WARNING, STANDARD only)
    # ------------------------------------------------------------------

    def _check_header_strings(self, tab):
        if tab.mesh_type.upper() != "STANDARD":
            return
        if not _is_quoted(tab._pairs.get("LABEL")):
            self._add("V031", "WARNING", "header",
                       "PVTTABLE LABEL is not quoted; OLGA samples quote it",
                       location="LABEL",
                       suggestion='Write LABEL = "<label>" with double quotes')
        entries = tab._pairs.get("COMPONENTS")
        if isinstance(entries, list) and entries and any(not _is_quoted(e) for e in entries):
            self._add("V031", "WARNING", "header",
                       "COMPONENTS entries are not quoted; OLGA samples quote them",
                       location="COMPONENTS",
                       suggestion='Write COMPONENTS = ("C1", "C2") with double quotes')

    # ------------------------------------------------------------------
    # V032: unknown header keys (STANDARD only). NOPRES and NOTEMP are errors.
    # ------------------------------------------------------------------

    _BREAKING_HEADER_KEYS = frozenset({"NOPRES", "NOTEMP"})

    def _check_unknown_header_keys(self, tab):
        if tab.mesh_type.upper() != "STANDARD":
            return
        for key in tab._pairs:
            if key in {"_available_properties"} or key in _KEYWORD_HEADER_KEYS:
                continue
            if str(key).upper() in self._BREAKING_HEADER_KEYS:
                self._add("V032", "ERROR", "header",
                           f"Header key {key} is not in the OLGA keyword list "
                           "(OLGA samples never use it, and it breaks the header)",
                           location=key,
                           suggestion="Remove the key; the OLGA keyword header has "
                                      "no NOPRES or NOTEMP lines")
                continue
            self._add("V032", "WARNING", "header",
                       f"Header key {key} is not in the OLGA keyword list",
                       location=key,
                       suggestion="Remove the key unless this OLGA version documents it")

    # ------------------------------------------------------------------
    # V002: COMPONENTS and MOLES must be present and same length
    # ------------------------------------------------------------------

    def _check_components(self, tab):
        comps = tab.components
        moles = tab.moles
        if not comps:
            self._add("V002", "ERROR", "header",
                       "COMPONENTS is missing or empty",
                       location="(header)",
                       suggestion="Add COMPONENTS = ( name1 , name2 ) to the header")
            return
        if not moles:
            self._add("V002", "ERROR", "header",
                       "MOLES is missing or empty",
                       location="(header)",
                       suggestion="Add MOLES = ( frac1 , frac2 ) to the header")
            return
        if len(comps) != len(moles):
            self._add("V002", "ERROR", "header",
                       f"COMPONENTS has {len(comps)} entries but MOLES has {len(moles)}",
                       location="(header)",
                       suggestion="Ensure COMPONENTS and MOLES have the same number of elements")

    # ------------------------------------------------------------------
    # V003: MOLES should sum to approximately 1.0 or 100.0
    # ------------------------------------------------------------------

    def _check_moles(self, tab):
        moles = tab.moles
        if not moles:
            return
        total = sum(moles)
        if abs(total - 1.0) < 0.01:
            return
        if abs(total - 100.0) < 1.0:
            self._add("V003", "INFO", "header",
                       f"MOLES sum to {total:.4f} (percentage-based, not fractional)",
                       location="(header)")
            return
        self._add("V003", "WARNING", "header",
                   f"MOLES sum to {total:.6f}, expected ~1.0 or ~100.0",
                   location="(header)",
                   suggestion="Verify that mole fractions are correct")

    # ------------------------------------------------------------------
    # V004: PRESSURE grid must have at least 2 points
    # ------------------------------------------------------------------

    def _check_pressure_grid(self, tab):
        grid = tab.pressure_grid
        if not grid:
            self._add("V004", "ERROR", "grid",
                       "PRESSURE grid is missing or empty",
                       location="(header)",
                       suggestion="Add PRESSURE = ( p1 , p2 , ... ) PA to the header")
            return
        if len(grid) < 2:
            self._add("V004", "ERROR", "grid",
                       f"PRESSURE grid has only {len(grid)} point(s); need at least 2",
                       location="(header)",
                       suggestion="Provide at least 2 pressure points for interpolation")
        else:
            self._add("V004", "INFO", "grid",
                       f"PRESSURE grid: {len(grid)} points, "
                       f"{min(grid):.1f} - {max(grid):.1f} Pa",
                       location="(header)")

    # ------------------------------------------------------------------
    # V005: NOENTHALPY must be present
    # ------------------------------------------------------------------

    def _check_noenthalpy(self, tab):
        if tab.mesh_type.upper() == "STANDARD":
            return
        nh = tab.n_enthalpies
        if not nh:
            self._add("V005", "WARNING", "grid",
                       "NOENTHALPY is missing",
                       location="(header)",
                       suggestion="NOENTHALPY defines enthalpy grid counts per pressure level")

    # ------------------------------------------------------------------
    # V006: Required properties (ROG, ROL minimum)
    # ------------------------------------------------------------------

    def _check_required_properties(self, tab):
        available = set(tab.available_properties)
        if tab.mesh_type.upper() == "STANDARD" and tab.phase.upper() == "TWO":
            required = {"ROG", "ROHL"}
        elif tab.mesh_type.upper() == "STANDARD":
            required = {"ROG", "ROHL", "ROWT"}
        else:
            required = self._REQUIRED_PROPERTIES
        missing = required - available
        if missing:
            self._add("V006", "ERROR", "properties",
                       f"Required property table(s) missing: {', '.join(sorted(missing))}",
                       location="(property tables)",
                       suggestion=f"Verify the declared properties: {', '.join(sorted(required))}")
        # Info about what is present
        if available:
            self._add("V006", "INFO", "properties",
                       f"Property tables found ({len(available)}): {', '.join(sorted(available))}",
                       location="(property tables)")

    # ------------------------------------------------------------------
    # V009: Check property tables for NaN/Inf
    # ------------------------------------------------------------------

    def _check_property_values(self, tab):
        if tab._header_only:
            return
        for prop_name in tab.available_properties:
            data = tab.get_property(prop_name)
            if data is None:
                continue
            nan_count = sum(1 for x in data if math.isnan(x))
            inf_count = sum(1 for x in data if math.isinf(x))
            if nan_count > 0:
                self._add("V009", "ERROR", "properties",
                           f"Property '{prop_name}' contains {nan_count} NaN value(s)",
                           location=prop_name,
                           suggestion="Check PVT generation for errors in this property")
            if inf_count > 0:
                self._add("V009", "ERROR", "properties",
                           f"Property '{prop_name}' contains {inf_count} Inf value(s)",
                           location=prop_name,
                           suggestion="Check PVT generation for singularities in this property")

    # ------------------------------------------------------------------
    # V007: P range covers genkey boundary pressures
    # ------------------------------------------------------------------

    def _check_pressure_coverage(self, tab, genkey):
        grid = tab.pressure_grid
        if not grid:
            return
        p_min, p_max = min(grid), max(grid)

        bc_pressures = _extract_genkey_boundary_values(
            genkey, "PRESSURE", normalize=tab.mesh_type.upper() == "STANDARD")
        if not bc_pressures:
            return

        for p in bc_pressures:
            if p < p_min:
                self._add("V007", "WARNING", "coverage",
                           f"Genkey boundary pressure {p:.1f} is below PVT grid minimum {p_min:.1f}",
                           location="PRESSURE grid vs genkey BCs",
                           suggestion="Extend the PVT pressure range or adjust boundary conditions")
            elif p > p_max:
                self._add("V007", "WARNING", "coverage",
                           f"Genkey boundary pressure {p:.1f} exceeds PVT grid maximum {p_max:.1f}",
                           location="PRESSURE grid vs genkey BCs",
                           suggestion="Extend the PVT pressure range or adjust boundary conditions")

    # ------------------------------------------------------------------
    # V008: T range covers genkey boundary temperatures
    # ------------------------------------------------------------------

    def _check_temperature_coverage(self, tab, genkey):
        grid = tab.temperature_grid
        if not grid:
            return
        t_min, t_max = min(grid), max(grid)

        bc_temps = _extract_genkey_boundary_values(genkey, "TEMPERATURE", normalize=True)
        if not bc_temps:
            return

        for t in bc_temps:
            if t < t_min:
                self._add("V008", "WARNING", "coverage",
                           f"Genkey boundary temperature {t:.1f} is below PVT grid minimum {t_min:.1f}",
                           location="Temperature range vs genkey BCs",
                           suggestion="Extend the PVT temperature range or adjust boundary conditions")
            elif t > t_max:
                self._add("V008", "WARNING", "coverage",
                           f"Genkey boundary temperature {t:.1f} exceeds PVT grid maximum {t_max:.1f}",
                           location="Temperature range vs genkey BCs",
                           suggestion="Extend the PVT temperature range or adjust boundary conditions")

    # ------------------------------------------------------------------
    # V012: declared keyword columns and their phase
    # ------------------------------------------------------------------

    def _check_keyword_columns(self, tab):
        if tab.mesh_type.upper() != "STANDARD" or not tab.columns:
            return
        phase = tab.phase.upper()
        for name in tab.columns:
            spec = _KEYWORD_COLUMNS.get(name)
            if spec is None:
                self._add(
                    "V012", "ERROR", "properties",
                    f"Column {name} is not in the OLGA keyword list",
                    location=name,
                    suggestion="Use a keyword column with its OLGA unit, such as PT in Pa or ROG in kg/m3",
                )
                continue
            unit, role = spec
            if role == "water" and phase == "TWO":
                self._add(
                    "V012", "ERROR", "properties",
                    f"Column {name} ({unit}) is a water-phase column and is not valid when PHASE = TWO",
                    location=name,
                    suggestion="Remove the water-phase column or set PHASE = THREE",
                )

    # ------------------------------------------------------------------
    # V014: declared NOPRES / NOTEMP against the axis lengths
    # ------------------------------------------------------------------

    def _check_keyword_grid(self, tab):
        if tab.mesh_type.upper() != "STANDARD" or tab.formulation.upper() != "PT":
            return
        pairs = (
            ("NOPRES", tab.pressure_grid, "PRESSURE"),
            ("NOTEMP", tab.temperature_grid, "TEMPERATURE"),
        )
        for key, grid, label in pairs:
            if key not in tab._pairs:
                continue
            declared = _declared_count(tab._pairs.get(key))
            actual = len(grid)
            if declared is None or declared != actual:
                shown = _format_number(declared) if declared is not None else "unreadable"
                self._add(
                    "V014", "ERROR", "grid",
                    f"{key} is {shown} but the {label} grid has {actual} points",
                    location=key,
                    suggestion=f"Set {key} to the number of {label} points",
                )

    # ------------------------------------------------------------------
    # V017-V020: zero/step/default warnings, plus impossible property nodes
    # ------------------------------------------------------------------

    def _check_keyword_nodes(self, tab):
        if tab.mesh_type.upper() != "STANDARD" or not tab.point_rows:
            return
        columns = tab.columns
        if "PT" not in columns or "TM" not in columns:
            return
        p_index = columns.index("PT")
        t_index = columns.index("TM")
        props = [name for name in columns if name not in {"PT", "TM"}]
        for point_number, row in enumerate(tab.point_rows, start=1):
            location_tail = (
                f"P={_format_number(row[p_index])} Pa "
                f"T={_format_number(row[t_index])} C"
            )
            for name in props:
                value = row[columns.index(name)]
                fault = _physical_fault(name, value)
                if fault:
                    self._add(
                        "V020", "ERROR", "properties", fault,
                        location=f"{name} point {point_number} {location_tail}",
                    )
                if value == 0:
                    self._add(
                        "V017", "WARNING", "properties",
                        f"Property {name} is zero",
                        location=f"{name} point {point_number} {location_tail}",
                        suggestion="Use a sensible extrapolated value instead of zero",
                    )
        pressures = [float(value) for value in tab.pressure_grid]
        temperatures = [float(value) for value in tab.temperature_grid]
        if not pressures or not temperatures:
            return
        located = {
            (float(row[p_index]), float(row[t_index])): row
            for row in tab.point_rows
        }

        def _at(pressure, temperature):
            return located[(float(pressure), float(temperature))]

        for name in props:
            index = columns.index(name)
            values = [_at(pressure, temperature)[index]
                      for pressure in pressures for temperature in temperatures]
            placeholder = _matching_default(name, values)
            if placeholder is not None:
                self._add(
                    "V019", "WARNING", "properties",
                    f"Property {name} is default-filled with {_format_number(placeholder)} at every node",
                    location=(
                        f"{name} all {len(values)} nodes, first "
                        f"P={_format_number(pressures[0])} Pa "
                        f"T={_format_number(temperatures[0])} C"
                    ),
                    suggestion="Replace placeholder values for a phase that is absent",
                )
            for pressure in pressures:
                series = [_at(pressure, temperature)[index] for temperature in temperatures]
                for hit in _step_indices(series):
                    self._warn_step(name, series, hit, pressure, temperatures[hit])
            for temperature in temperatures:
                series = [_at(pressure, temperature)[index] for pressure in pressures]
                for hit in _step_indices(series):
                    self._warn_step(name, series, hit, pressures[hit], temperature)

    def _check_critical_state(self, tab):
        pairs = getattr(tab, "_pairs", {})
        if "CRITICALPRESSURE" in pairs:
            pressure = _header_number(pairs.get("CRITICALPRESSURE"))
            if pressure is not None:
                value, _unit = pressure
                if not math.isfinite(value) or value <= 0:
                    self._add(
                        "V021", "ERROR", "header",
                        "CRITICALPRESSURE must be positive",
                        location="CRITICALPRESSURE",
                    )
        if "CRITICALTEMPERATURE" in pairs:
            temperature = _header_number(pairs.get("CRITICALTEMPERATURE"))
            if temperature is not None:
                value, unit = temperature
                if _critical_temperature_impossible(value, unit):
                    self._add(
                        "V021", "ERROR", "header",
                        "CRITICALTEMPERATURE must be above absolute zero",
                        location="CRITICALTEMPERATURE",
                    )

    def _warn_step(self, name, series, hit, pressure, temperature):
        self._add(
            "V018", "WARNING", "properties",
            f"Property {name} steps from {_format_number(series[hit - 1])} "
            f"to {_format_number(series[hit])}",
            location=(
                f"{name} P={_format_number(pressure)} Pa "
                f"T={_format_number(temperature)} C"
            ),
            suggestion="Smooth the step before using the table",
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: python tab_validator.py <file.tab> [--genkey model.genkey] [--json]",
            file=sys.stderr,
        )
        sys.exit(1)

    filepath = args[0]
    if not Path(filepath).exists():
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(2)

    # Parse flags
    genkey_path = None
    output_json = False
    i = 1
    while i < len(args):
        if args[i] == "--genkey" and i + 1 < len(args):
            genkey_path = args[i + 1]
            if not Path(genkey_path).exists():
                print(f"Error: genkey file not found: {genkey_path}", file=sys.stderr)
                sys.exit(2)
            i += 2
        elif args[i] == "--json":
            output_json = True
            i += 1
        else:
            i += 1

    validator = TabValidator(filepath, genkey_path=genkey_path)
    result = validator.validate()

    if output_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(validator.summary())

    has_errors = len(result["errors"]) > 0
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
