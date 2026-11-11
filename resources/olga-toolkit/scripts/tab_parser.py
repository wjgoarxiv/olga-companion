"""
tab_parser.py -- Parser for OLGA .tab PVT (Pressure-Volume-Temperature) table files.

Usage:
    python tab_parser.py <file.tab>
    python tab_parser.py <file.tab> --json
    python tab_parser.py <file.tab> --components
    python tab_parser.py <file.tab> --pressure-range
    python tab_parser.py <file.tab> --properties

Exit codes:
    0 -- success
    1 -- file not found or usage error
    2 -- parse error
"""

import json
import math
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Known property table keywords
# ---------------------------------------------------------------------------

_PROPERTY_KEYWORDS = {
    "ROG", "ROL", "DROGDP", "DROLDP", "DROGDT", "DROLDT",
    "VISG", "VISL", "CPG", "CPL", "HG", "HL",
    "SIGGAL", "SIGWAL", "SIGWL",
    "RS", "RSW", "RSWO",
    "SEG", "SEL", "SEGAL",
    "TCG", "TCL",
    "ROW", "VISW", "CPW", "HW", "SEW",
    "DROGDH", "DROLDH", "DROWDP", "DROWDH",
}


# ---------------------------------------------------------------------------
# Line pre-processing (continuation joining)
# ---------------------------------------------------------------------------

def _join_continuation_lines(raw_lines):
    """Join lines ending with backslash into logical lines.

    Also strips comment lines (starting with !) and blank lines.
    Returns a single string of the joined content.
    """
    merged = []
    buf = []
    for line in raw_lines:
        stripped = line.rstrip("\r\n")

        # Strip inline -- skip pure comment lines
        text = stripped.lstrip()
        if text.startswith("!"):
            continue

        rstripped = stripped.rstrip()
        if rstripped.endswith("\\"):
            buf.append(rstripped[:-1])
        else:
            buf.append(stripped)
            merged.append(" ".join(buf))
            buf = []

    # Flush any trailing buffer (file ended mid-continuation)
    if buf:
        merged.append(" ".join(buf))

    return " ".join(merged)


# ---------------------------------------------------------------------------
# Tuple parsing
# ---------------------------------------------------------------------------

def _parse_tuple(s, start):
    """Parse a parenthesised tuple starting at s[start] == '('.

    Returns (list_of_float_or_str, index_after_close_paren).
    """
    assert s[start] == "("
    depth = 1
    i = start + 1
    n = len(s)
    while i < n and depth > 0:
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
        i += 1
    if depth:
        raise ValueError("Unclosed tuple")
    inner = s[start + 1 : i - 1]
    tokens = inner.split(",")
    if any(not tok.strip() for tok in tokens):
        raise ValueError("Empty tuple element")
    elements = [_try_number(tok.strip()) for tok in tokens]
    return elements, i


def _try_number(s):
    """Try to parse as float, then int; fall back to stripped string."""
    s = s.strip()
    if not s:
        return s
    try:
        f = float(s)
        if math.isfinite(f) and f == int(f) and "." not in s and "e" not in s.lower():
            return int(f)
        return f
    except ValueError:
        return s


# ---------------------------------------------------------------------------
# Key=Value extraction from the joined line
# ---------------------------------------------------------------------------

def _extract_pairs(text, header_only=False, strict=False):
    """Parse KEY = VALUE pairs from the joined PVTTABLE line.

    Returns dict of {KEY: value}.  Values can be:
      - str for simple tokens
      - list for tuples
      - dict {"value": list, "unit": str} for tuples with trailing unit
      - dict {"value": number, "unit": str} for number with unit

    If header_only is True, property arrays are scanned by name only.
    """
    pairs = {}
    n = len(text)
    i = 0

    # Skip leading whitespace
    while i < n and text[i] in (" ", "\t"):
        i += 1

    # Strip leading "PVTTABLE" keyword if present
    if text[i:i + 8].upper() == "PVTTABLE":
        i += 8
        # Skip whitespace after PVTTABLE
        while i < n and text[i] in (" ", "\t"):
            i += 1

    while i < n:
        # Skip whitespace and commas
        while i < n and text[i] in (" ", "\t", ","):
            i += 1
        if i >= n:
            break

        # Find '='
        eq = text.find("=", i)
        if eq == -1:
            if strict:
                raise ValueError("Unexpected trailing header content")
            break

        key_start = i
        key = text[i:eq].strip().upper()
        if strict and (not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in pairs):
            raise ValueError(f"Invalid or duplicate header key: {key}")
        if header_only and key in _PROPERTY_KEYWORDS:
            _scan_property_names(text, key_start, pairs)
            break
        i = eq + 1

        # Skip whitespace after '='
        while i < n and text[i] in (" ", "\t"):
            i += 1
        if i >= n:
            if strict:
                raise ValueError(f"Missing value for {key}")
            pairs[key] = None
            break

        # Parse value
        if text[i] == "(":
            elements, i = _parse_tuple(text, i)
            # Check for trailing unit token
            while i < n and text[i] == " ":
                i += 1
            unit = _scan_unit(text, i)
            if unit:
                i += len(unit)
                pairs[key] = {"value": elements, "unit": unit}
            else:
                pairs[key] = elements
        else:
            # Bare token -- read to next comma or '=' boundary
            token, i = _read_bare_token(text, i)
            pairs[key] = _parse_bare(token)

    return pairs


def _scan_unit(text, i):
    """If text[i:] starts with a unit token (letter-leading), return it."""
    n = len(text)
    if i >= n:
        return ""
    if not text[i].isalpha():
        return ""
    j = i
    while j < n and text[j] not in (" ", ",", "\t", "=", "("):
        j += 1
    candidate = text[i:j]
    # Reject if it looks like a KEY (followed by '=' after optional spaces)
    k = j
    while k < n and text[k] in (" ", "\t"):
        k += 1
    if k < n and text[k] == "=":
        return ""
    # Reject known keywords
    if candidate.upper() in _PROPERTY_KEYWORDS or candidate.upper() == "PVTTABLE":
        return ""
    return candidate


def _read_bare_token(text, start):
    """Read a bare (unquoted, non-tuple) token from text[start:].

    Returns (token_string, new_index).
    """
    n = len(text)
    i = start
    while i < n and text[i] not in (",",):
        # Stop if we hit something that looks like ' KEY =' boundary
        if text[i] == "=":
            # Backtrack to find the key start
            j = i - 1
            while j >= start and text[j] in (" ", "\t"):
                j -= 1
            key_end = j + 1
            while j >= start and text[j] not in (" ", "\t", ","):
                j -= 1
            key_start = j + 1
            candidate = text[key_start:key_end].strip()
            if candidate and candidate[0].isalpha():
                # This '=' belongs to the next KEY=VALUE pair
                return text[start:key_start].strip(), key_start
        i += 1
    token = text[start:i].strip()
    return token, i


def _parse_bare(token):
    """Parse a bare token: number+unit, plain number, or string."""
    token = token.strip()
    if not token:
        return None
    # Try number + unit: "101325 PA"
    m = re.match(
        r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+([A-Za-z][A-Za-z0-9/]*)\s*$",
        token,
    )
    if m:
        num = _try_number(m.group(1))
        return {"value": num, "unit": m.group(2)}
    # Plain number
    num = _try_number(token)
    if isinstance(num, (int, float)):
        return num
    return token


def _scan_property_names(text, start, pairs):
    """Quick scan for property keyword names in text[start:] without loading data.

    Adds a special key '_available_properties' to pairs.
    """
    found = []
    for kw in _PROPERTY_KEYWORDS:
        # Look for ' KW =' or ',KW =' patterns
        pattern = kw + r"\s*="
        if re.search(pattern, text[start:]):
            found.append(kw)
    pairs["_available_properties"] = sorted(found)


# ---------------------------------------------------------------------------
# TabParser
# ---------------------------------------------------------------------------

class TabParser:
    """Parse an OLGA .tab PVT table file.

    Parameters
    ----------
    tab_path : str
        Path to .tab file.
    header_only : bool
        If True, only parse the header (components, grid sizes) without
        loading full property tables. Much faster for large files.
    """

    def __init__(self, tab_path, header_only=False):
        self.filepath = str(tab_path)
        self._header_only = header_only
        self._pairs = {}
        self.point_rows = None
        self._raw_size = 0
        self.header_at_top = True
        self.leading_comments = 0
        self._parse()

    def _parse(self):
        path = Path(self.filepath)
        self._raw_size = path.stat().st_size if path.exists() else 0

        with open(self.filepath, "r", encoding="utf-8", errors="replace") as fh:
            raw_lines = fh.readlines()

        for line in raw_lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("!"):
                self.leading_comments += 1
                self.header_at_top = False
                continue
            self.header_at_top = self.leading_comments == 0 and bool(
                re.match(r"PVTTABLE\s+LABEL\b", stripped, re.IGNORECASE)
            )
            break

        text = _join_continuation_lines(raw_lines)
        point = re.search(r"\bPVTTABLE\s+POINT\b", text, re.IGNORECASE)
        header = text[:point.start()] if point else text
        self._pairs = _extract_pairs(header, header_only=self._header_only)
        if point or "COLUMNS" in self._pairs or self.mesh_type.upper() == "STANDARD":
            self._pairs = _extract_pairs(header, strict=True)
            self._parse_standard(text[point.start():] if point else "")

    def _parse_standard(self, records):
        phase = self.phase.upper()
        if self.mesh_type.upper() != "STANDARD" or phase not in {"TWO", "THREE"}:
            raise ValueError(
                "Column/POINT support requires MESHTYPE=STANDARD and PHASE=TWO or PHASE=THREE"
            )
        if not self.formulation:
            return
        if self.formulation.upper() != "PT":
            raise ValueError("STANDARD support requires a pressure-temperature grid")
        columns = self.columns
        if (not isinstance(self._pairs.get("COLUMNS"), list)
                or not columns or len(set(columns)) != len(columns)
                or any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", c) for c in columns)
                or not {"PT", "TM"}.issubset(columns)):
            raise ValueError("COLUMNS must contain unique names including PT and TM")
        for key, unit in (("PRESSURE", "PA"), ("TEMPERATURE", "C")):
            field = self._pairs.get(key)
            found = str(field.get("unit", "")).upper() if isinstance(field, dict) else ""
            if not isinstance(field, dict) or found != unit:
                seen = f" (found {found})" if found else ""
                raise ValueError(f"STANDARD {key} requires explicit {unit} units{seen}")
            values = _finite_values(field, key)
            if len(values) < 2 or any(a >= b for a, b in zip(values, values[1:])):
                raise ValueError(f"{key} grid must have at least two strictly increasing points")
            if key == "PRESSURE" and values[0] <= 0:
                raise ValueError("PRESSURE grid must be positive absolute pressure")
        fraction_field = self._pairs.get("TOTWATERFRACTION")
        if phase == "THREE" or fraction_field is not None:
            fraction = _finite_values(fraction_field, "TOTWATERFRACTION")
            if (not isinstance(fraction_field, list)
                    or len(fraction) != 1 or not 0 <= fraction[0] <= 1):
                raise ValueError("Only a single TOTWATERFRACTION in [0, 1] is supported")
            if phase == "TWO" and fraction[0] != 0:
                raise ValueError("PHASE=TWO accepts only a zero TOTWATERFRACTION")
        _finite_values(self._pairs.get("MOLES"), "MOLES")
        if self._header_only:
            return
        rows = []
        seen = set()
        p_index, t_index = columns.index("PT"), columns.index("TM")
        pressures, temperatures = set(self.pressure_grid), set(self.temperature_grid)
        for record in re.split(r"\bPVTTABLE\b", records, flags=re.IGNORECASE)[1:]:
            match = re.fullmatch(r"\s*POINT\s*=\s*(\([^()]*\))\s*,?\s*", record, re.IGNORECASE)
            if not match:
                raise ValueError(f"Malformed POINT record {len(rows) + 1}")
            values, _ = _parse_tuple(match.group(1), 0)
            row = _finite_values(values, f"POINT {len(rows) + 1}")
            if len(row) != len(columns):
                raise ValueError(f"POINT {len(rows) + 1} width does not match COLUMNS")
            coordinate = row[p_index], row[t_index]
            if coordinate[0] not in pressures or coordinate[1] not in temperatures:
                raise ValueError(f"POINT {len(rows) + 1} coordinate is outside the declared grid")
            if coordinate in seen:
                raise ValueError(f"Duplicate POINT coordinate: {coordinate}")
            seen.add(coordinate)
            rows.append(row)
        if len(rows) != len(pressures) * len(temperatures):
            raise ValueError("POINT records do not cover the complete pressure-temperature grid")
        self.point_rows = rows

    # ------------------------------------------------------------------
    # Properties -- header fields
    # ------------------------------------------------------------------

    @property
    def label(self):
        """PVT table label, e.g. 'FLUID-A'."""
        v = self._pairs.get("LABEL")
        return str(v) if v is not None else ""

    @property
    def phase(self):
        """Phase type, e.g. 'TWO'."""
        v = self._pairs.get("PHASE")
        return str(v) if v is not None else ""

    @property
    def formulation(self):
        """PVT formulation, e.g. 'PH'."""
        v = self._pairs.get("PVTFORMULATION")
        if v is not None:
            return str(v)
        if (self.mesh_type.upper() == "STANDARD"
                and self._pairs.get("PRESSURE") is not None
                and self._pairs.get("TEMPERATURE") is not None):
            return "PT"
        return ""

    @property
    def components(self):
        """List of component names."""
        v = self._pairs.get("COMPONENTS")
        return _as_list(v)

    @property
    def moles(self):
        """List of mole fractions (floats)."""
        v = self._pairs.get("MOLES")
        return _as_float_list(v)

    @property
    def mol_weights(self):
        """List of molecular weights."""
        v = self._pairs.get("MOLWEIGHT")
        return _as_float_list(v)

    @property
    def densities(self):
        """List of densities with unit, as dict."""
        v = self._pairs.get("DENSITY")
        if isinstance(v, dict) and "value" in v:
            return v
        if isinstance(v, list):
            return {"value": v, "unit": ""}
        return {"value": [], "unit": ""}

    @property
    def pressure_grid(self):
        """Pressure grid array (floats, Pa)."""
        v = self._pairs.get("PRESSURE")
        return _as_float_list(v)

    @property
    def n_pressures(self):
        """Number of pressure points."""
        return len(self.pressure_grid)

    @property
    def temperature_grid(self):
        return _as_float_list(self._pairs.get("TEMPERATURE"))

    @property
    def columns(self):
        return [str(c).upper() for c in _as_list(self._pairs.get("COLUMNS"))]

    @property
    def n_enthalpies(self):
        """List of enthalpy count per pressure (typically all same value)."""
        v = self._pairs.get("NOENTHALPY")
        result = _as_float_list(v)
        return [int(x) for x in result]

    @property
    def mesh_type(self):
        """Mesh type, e.g. 'FREEENTHALPY'."""
        v = self._pairs.get("MESHTYPE")
        return str(v) if v is not None else ""

    @property
    def bubble_pressures(self):
        """Bubble point pressures array."""
        v = self._pairs.get("BUBBLEPRESSURES")
        return _as_float_list(v)

    @property
    def bubble_temperatures(self):
        """Bubble point temperatures array."""
        v = self._pairs.get("BUBBLETEMPERATURES")
        return _as_float_list(v)

    @property
    def std_pressure(self):
        """Standard pressure with unit."""
        return self._pairs.get("STDPRESSURE")

    @property
    def std_temperature(self):
        """Standard temperature with unit."""
        return self._pairs.get("STDTEMPERATURE")

    @property
    def available_properties(self):
        """List of property table names found in file."""
        if self.columns:
            return [c for c in self.columns if c not in {"PT", "TM"}]
        # If header_only, we scanned for names without loading data
        scanned = self._pairs.get("_available_properties")
        if scanned is not None:
            return scanned
        # Full parse: check which property keywords exist
        found = []
        for kw in sorted(_PROPERTY_KEYWORDS):
            if kw in self._pairs:
                found.append(kw)
        return found

    def get_property(self, name):
        """Get a property table array by name (e.g. 'ROG', 'VISL').

        Returns list of floats, or None if not found / not loaded.
        """
        name = name.upper()
        if self.columns:
            if self.point_rows is None or name not in self.columns:
                return None
            index = self.columns.index(name)
            return [row[index] for row in self.point_rows]
        v = self._pairs.get(name)
        if v is None:
            return None
        return _as_float_list(v)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_dict(self):
        """Return all header data as dict (without full property tables)."""
        return {
            "filepath": self.filepath,
            "label": self.label,
            "phase": self.phase,
            "formulation": self.formulation,
            "components": self.components,
            "moles": self.moles,
            "mol_weights": self.mol_weights,
            "densities": self.densities,
            "mesh_type": self.mesh_type,
            "std_pressure": self.std_pressure,
            "std_temperature": self.std_temperature,
            "n_pressures": self.n_pressures,
            "pressure_range": {
                "min": min(self.pressure_grid) if self.pressure_grid else None,
                "max": max(self.pressure_grid) if self.pressure_grid else None,
            },
            "n_enthalpies": self.n_enthalpies,
            "n_temperatures": len(self.temperature_grid),
            "temperature_range": {
                "min": min(self.temperature_grid) if self.temperature_grid else None,
                "max": max(self.temperature_grid) if self.temperature_grid else None,
            },
            "columns": self.columns,
            "point_count": len(self.point_rows) if self.point_rows is not None else None,
            "point_data_loaded": self.point_rows is not None,
            "bubble_pressures_count": len(self.bubble_pressures),
            "bubble_temperatures_count": len(self.bubble_temperatures),
            "available_properties": self.available_properties,
            "file_size_bytes": self._raw_size,
        }

    def to_json(self, indent=2):
        """Serialize header to JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _as_list(v):
    """Coerce value to a plain list."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, dict) and "value" in v:
        inner = v["value"]
        return inner if isinstance(inner, list) else [inner]
    return [v]


def _as_float_list(v):
    """Coerce value to a list of floats."""
    raw = _as_list(v)
    result = []
    for x in raw:
        if isinstance(x, (int, float)):
            result.append(float(x))
        else:
            try:
                result.append(float(x))
            except (ValueError, TypeError):
                pass
    return result


def _finite_values(value, name):
    raw = _as_list(value)
    if not raw or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in raw):
        raise ValueError(f"{name} must contain finite numbers only")
    return [float(x) for x in raw]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: python tab_parser.py <file.tab> [--json|--components|--pressure-range|--properties]",
            file=sys.stderr,
        )
        sys.exit(1)

    filepath = args[0]
    if not Path(filepath).exists():
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    flags = set(args[1:])

    try:
        header_only = "--json" in flags or "--components" in flags or \
                      "--pressure-range" in flags or "--properties" in flags
        parser = TabParser(filepath, header_only=header_only)
    except Exception as exc:
        print(f"Error: failed to parse {filepath}: {exc}", file=sys.stderr)
        sys.exit(2)

    if "--json" in flags:
        print(parser.to_json())
    elif "--components" in flags:
        comps = parser.components
        moles = parser.moles
        for i, c in enumerate(comps):
            mol = f" ({moles[i]:.6f})" if i < len(moles) else ""
            print(f"  {c}{mol}")
    elif "--pressure-range" in flags:
        grid = parser.pressure_grid
        if grid:
            print(f"  Pressure range: {min(grid):.1f} - {max(grid):.1f} Pa ({len(grid)} points)")
        else:
            print("  No pressure grid found.")
    elif "--properties" in flags:
        props = parser.available_properties
        if props:
            print(f"  Properties ({len(props)}): {', '.join(props)}")
        else:
            print("  No property tables found.")
    else:
        # Default: compact text summary
        print(f"PVT Table: {filepath}")
        print(f"  Label:        {parser.label}")
        print(f"  Phase:        {parser.phase}")
        print(f"  Formulation:  {parser.formulation}")
        print(f"  Components:   {', '.join(parser.components)}")
        print(f"  Pressures:    {parser.n_pressures} points")
        props = parser.available_properties
        print(f"  Properties:   {len(props)} tables")


if __name__ == "__main__":
    main()
