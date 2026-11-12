"""
mfl_parser.py -- Parser for Multiflash .mfl command files.

Multiflash .mfl files are semicolon-delimited command scripts that define
thermodynamic models, components, compositions, and table-generation settings
for the Multiflash engine (used to produce .tab PVT tables for OLGA).

Usage as a library:
    from mfl_parser import MflParser
    p = MflParser('Case1.mfl')
    print(p.components)     # ['CO2', 'N2']
    print(p.amounts)        # [99.7, 0.3]
    print(p.table_config)   # {'output_path': '...', 'Pmin': 0.01, ...}

Standalone usage:
    python mfl_parser.py Case1.mfl
    python mfl_parser.py Case1.mfl --json
    python mfl_parser.py Case1.mfl --components
    python mfl_parser.py Case1.mfl --table-config

Exit codes: 0=success, 1=domain error, 2=I/O error.
"""

import argparse
import json
import os
import re
import sys


# ---------------------------------------------------------------------------
# MflParser
# ---------------------------------------------------------------------------

class MflParser:
    """Parse a Multiflash .mfl command file.

    Parameters
    ----------
    mfl_path : str
        Path to .mfl file.
    """

    def __init__(self, mfl_path: str):
        self._path = mfl_path
        self._raw = ""
        self._commands = []

        # Parsed data stores
        self._version = None
        self._date = None
        self._components = []
        self._amounts = []
        self._tolamounts = []
        self._eos_model = None
        self._models = []
        self._phases = []
        self._units = {}
        self._table_config = {}
        self._temperature = None
        self._pressure = None
        self._bipdata = None
        self._bipsets = []
        self._keys = {}
        self._chardata = []
        self._puredata = None
        self._datum = {}

        self._read_and_parse(mfl_path)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def version(self) -> str:
        """Multiflash version string from header."""
        return self._version or ""

    @property
    def date(self) -> str:
        """Date string from header."""
        return self._date or ""

    @property
    def components(self) -> list:
        """List of component names, e.g. ['CO2', 'N2']."""
        return list(self._components)

    @property
    def amounts(self) -> list:
        """List of mole fractions, e.g. [99.7, 0.3]."""
        return list(self._amounts)

    @property
    def eos_model(self) -> str:
        """Primary EOS model name, e.g. 'MCPA'."""
        return self._eos_model or ""

    @property
    def phases(self) -> list:
        """List of phase definitions (PD commands).

        Each entry is a dict with keys: name, type, models.
        e.g. [{'name': 'GAS', 'type': 'gas', 'models': ['MCPA', ...]}, ...]
        """
        return list(self._phases)

    @property
    def units(self) -> dict:
        """Dict of unit settings, e.g. {'temperature': 'K', 'pressure': 'Pa', ...}."""
        return dict(self._units)

    @property
    def table_config(self) -> dict:
        """Table output config: output_path, Pmin, Pmax, Tmin, Tmax, minHPoints, etc."""
        return dict(self._table_config)

    @property
    def temperature(self) -> float:
        """Reference temperature value."""
        return self._temperature

    @property
    def pressure(self) -> float:
        """Reference pressure value."""
        return self._pressure

    @property
    def models(self) -> list:
        """All model definitions (model commands)."""
        return list(self._models)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return all parsed data as dict."""
        return {
            "path": self._path,
            "version": self.version,
            "date": self.date,
            "components": self.components,
            "amounts": self.amounts,
            "eos_model": self.eos_model,
            "models": self.models,
            "phases": self.phases,
            "units": self.units,
            "table_config": self.table_config,
            "temperature": self.temperature,
            "pressure": self.pressure,
            "bipdata": self._bipdata,
            "bipsets": self._bipsets,
            "keys": self._keys,
            "chardata": self._chardata,
            "puredata": self._puredata,
            "datum": self._datum,
            "tolamounts": self._tolamounts,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=True)

    # ------------------------------------------------------------------
    # Internal: read and parse
    # ------------------------------------------------------------------

    def _read_and_parse(self, mfl_path: str):
        """Read .mfl file and parse all commands."""
        try:
            with open(mfl_path, "r", encoding="utf-8") as f:
                self._raw = f.read()
        except UnicodeDecodeError:
            with open(mfl_path, "r", encoding="latin-1") as f:
                self._raw = f.read()

        # Step 1: Extract header comments (lines starting with #)
        self._parse_headers(self._raw)

        # Step 2: Strip header comment lines
        lines = self._raw.splitlines()
        body_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            body_lines.append(line)
        body = "\n".join(body_lines)

        # Step 3: Split on semicolons to get individual commands
        raw_commands = body.split(";")
        self._commands = []
        for cmd in raw_commands:
            cleaned = " ".join(cmd.split())  # collapse whitespace
            if cleaned:
                self._commands.append(cleaned)

        # Step 4: Parse each command
        for cmd in self._commands:
            self._dispatch_command(cmd)

    def _parse_headers(self, text: str):
        """Extract version and date from #-delimited header lines."""
        # Version: #Multiflash version: 7.3.32  October 2022  #
        m = re.search(
            r"#\s*Multiflash\s+version:\s*(.+?)\s*#", text, re.IGNORECASE
        )
        if m:
            self._version = m.group(1).strip()

        # Date: #Date: Wed 14 June 2023        Time:   17:17:40  #
        m = re.search(r"#\s*Date:\s*(.+?)\s*#", text, re.IGNORECASE)
        if m:
            self._date = m.group(1).strip()

    def _dispatch_command(self, cmd: str):
        """Route a command string to the appropriate parser."""
        # Identify the first keyword (case-insensitive)
        first = cmd.split()[0].lower() if cmd.split() else ""

        dispatch = {
            "components": self._parse_components,
            "amounts": self._parse_amounts,
            "tolamounts": self._parse_tolamounts,
            "model": self._parse_model,
            "pd": self._parse_pd,
            "units": self._parse_units,
            "table": self._parse_table,
            "temperature": self._parse_temperature,
            "pressure": self._parse_pressure,
            "bipdata": self._parse_bipdata,
            "bipset": self._parse_bipset,
            "keys": self._parse_keys,
            "chardata": self._parse_chardata,
            "puredata": self._parse_puredata,
            "datum": self._parse_datum,
        }

        handler = dispatch.get(first)
        if handler:
            handler(cmd)
        else:
            # Handle fragments that result from semicolons inside a
            # table block (e.g. "Pmin 0.01 Pmax 200 Tmin -10 ...")
            self._parse_table_fragment(cmd)

    # ------------------------------------------------------------------
    # Individual command parsers
    # ------------------------------------------------------------------

    def _parse_components(self, cmd: str):
        """Parse: Components overwrite 1 CO2 2 N2"""
        # Remove leading keyword and optional 'overwrite'
        tokens = cmd.split()
        # Skip 'Components' and 'overwrite' if present
        start = 1
        if len(tokens) > 1 and tokens[1].lower() == "overwrite":
            start = 2

        # Remaining tokens are: index name index name ...
        names = []
        i = start
        while i < len(tokens):
            token = tokens[i]
            # If it's a number, skip it (it's the index); next token is the name
            try:
                int(token)
                if i + 1 < len(tokens):
                    names.append(tokens[i + 1])
                    i += 2
                else:
                    i += 1
            except ValueError:
                # Not a number -- treat as a component name
                names.append(token)
                i += 1

        self._components = names

    def _parse_amounts(self, cmd: str):
        """Parse: amounts 99.7 0.3"""
        tokens = cmd.split()
        values = []
        for t in tokens[1:]:
            try:
                values.append(float(t))
            except ValueError:
                pass
        self._amounts = values

    def _parse_tolamounts(self, cmd: str):
        """Parse: tolamounts 0. 0."""
        tokens = cmd.split()
        values = []
        for t in tokens[1:]:
            try:
                values.append(float(t))
            except ValueError:
                pass
        self._tolamounts = values

    def _parse_model(self, cmd: str):
        """Parse: model MCPA ASSOC PSAT CPABIP1 CPABIP2 CPABIP3"""
        tokens = cmd.split()
        if len(tokens) < 2:
            return
        model_name = tokens[1]
        model_args = tokens[2:] if len(tokens) > 2 else []
        self._models.append({"name": model_name, "args": model_args})

        # The first 'model' command with EOS-like name is the primary EOS
        if self._eos_model is None:
            self._eos_model = model_name

    def _parse_pd(self, cmd: str):
        """Parse: PD GAS gas MCPA MCPA MCPA VSuperTRAPP TCSuperTRAPP STMCSA"""
        tokens = cmd.split()
        if len(tokens) < 3:
            return
        phase = {
            "name": tokens[1],
            "type": tokens[2],
            "models": tokens[3:],
        }
        self._phases.append(phase)

    def _parse_units(self, cmd: str):
        """Parse: units temperature K pressure Pa enthalpy J/mol ...

        Tokens alternate between quantity-name and unit-value.
        """
        tokens = cmd.split()
        i = 1  # skip 'units'
        current_key = None
        while i < len(tokens):
            token = tokens[i]
            if current_key is None:
                current_key = token
                i += 1
            else:
                # Value may be multi-word (e.g. 'J/mol/K') -- but typically single
                # Check if next token looks like a unit key (lowercase alpha word)
                # Heuristic: known quantity names
                self._units[current_key] = token
                current_key = None
                i += 1

    def _parse_table(self, cmd: str):
        """Parse table command with output path and range parameters.

        Example:
            table OLGAPH "C:/path/to/Case1.tab" info
            units temperature degC pressure bar enthalpy J/mol
            Pmin 0.01 Pmax 200 Tmin -10 Tmax 150 minHPoints 600
            pressure 0.01 enthalpy [values...]
        """
        config = {}

        # Extract table type (OLGAPH, etc.)
        tokens = cmd.split()
        if len(tokens) >= 2:
            config["table_type"] = tokens[1]

        # Extract quoted output path
        m = re.search(r'"([^"]+)"', cmd)
        if m:
            config["output_path"] = m.group(1)

        # Extract numeric parameters: Pmin, Pmax, Tmin, Tmax, minHPoints
        for param in ("Pmin", "Pmax", "Tmin", "Tmax", "minHPoints"):
            m = re.search(
                r"\b" + param + r"\s+([-+]?\d*\.?\d+(?:[eE][+-]?\d+)?)",
                cmd, re.IGNORECASE,
            )
            if m:
                config[param] = float(m.group(1))

        # Check for 'info' keyword
        if re.search(r"\binfo\b", cmd, re.IGNORECASE):
            config["info"] = True

        # Extract enthalpy grid values (large numeric block after 'enthalpy')
        # Find the last occurrence of 'enthalpy' followed by numbers
        m = re.search(
            r"\benthalpy\s+([-+]?\d[\d.eE+\-\s]+)$", cmd, re.IGNORECASE
        )
        if m:
            nums = re.findall(
                r"[-+]?\d*\.?\d+(?:[eE][+-]?\d+)?", m.group(1)
            )
            if nums:
                config["enthalpy_values"] = [float(n) for n in nums]
                config["enthalpy_count"] = len(config["enthalpy_values"])

        # Extract pressure grid value (single value after 'pressure' keyword
        # before 'enthalpy')
        m = re.search(
            r"\bpressure\s+([-+]?\d*\.?\d+(?:[eE][+-]?\d+)?)", cmd,
            re.IGNORECASE,
        )
        if m:
            config["pressure_value"] = float(m.group(1))

        self._table_config = config

    def _parse_temperature(self, cmd: str):
        """Parse: Temperature 293.15"""
        tokens = cmd.split()
        if len(tokens) >= 2:
            try:
                self._temperature = float(tokens[1])
            except ValueError:
                pass

    def _parse_pressure(self, cmd: str):
        """Parse: Pressure 101325"""
        tokens = cmd.split()
        if len(tokens) >= 2:
            try:
                self._pressure = float(tokens[1])
            except ValueError:
                pass

    def _parse_bipdata(self, cmd: str):
        """Parse: bipdata INFOBIPS OILANDGAS4"""
        tokens = cmd.split()
        self._bipdata = tokens[1:] if len(tokens) > 1 else []

    def _parse_bipset(self, cmd: str):
        """Parse: BipSet CPABIP1 1 constant eos none"""
        tokens = cmd.split()
        if len(tokens) >= 2:
            self._bipsets.append({
                "name": tokens[1],
                "args": tokens[2:],
            })

    def _parse_keys(self, cmd: str):
        """Parse: keys LIQUID1 '*'"""
        tokens = cmd.split()
        if len(tokens) >= 3:
            phase_name = tokens[1]
            key_value = " ".join(tokens[2:]).strip('"').strip("'")
            self._keys[phase_name] = key_value

    def _parse_chardata(self, cmd: str):
        """Parse: chardata INFOCHAR TBSOEREIDE"""
        tokens = cmd.split()
        if len(tokens) > 1:
            self._chardata.append(tokens[1:])

    def _parse_puredata(self, cmd: str):
        """Parse: puredata Infodata"""
        tokens = cmd.split()
        self._puredata = tokens[1] if len(tokens) > 1 else None

    def _parse_datum(self, cmd: str):
        """Parse: datum enthalpy compound entropy compound"""
        tokens = cmd.split()
        i = 1
        while i < len(tokens) - 1:
            self._datum[tokens[i]] = tokens[i + 1]
            i += 2

    def _parse_table_fragment(self, cmd: str):
        """Handle leftover fragments from table blocks split by inner semicolons.

        When a table block contains embedded semicolons (e.g. a 'units' line
        inside the table command), the split produces fragments like:
            "Pmin 0.01 Pmax 200 Tmin -10 Tmax 150 minHPoints 600"
        This method scans for known table parameters in any unrecognized command.
        """
        for param in ("Pmin", "Pmax", "Tmin", "Tmax", "minHPoints"):
            m = re.search(
                r"\b" + param + r"\s+([-+]?\d*\.?\d+(?:[eE][+-]?\d+)?)",
                cmd, re.IGNORECASE,
            )
            if m:
                self._table_config[param] = float(m.group(1))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mfl_parser.py",
        description="Parse a Multiflash .mfl command file.",
    )
    p.add_argument("mfl", help="Path to .mfl file")
    p.add_argument("--json", action="store_true",
                   help="Output full parsed data as JSON")
    p.add_argument("--components", action="store_true",
                   help="Print components only")
    p.add_argument("--table-config", action="store_true",
                   help="Print table configuration only")
    return p


def main():
    ap = _build_parser()
    args = ap.parse_args()

    if not os.path.isfile(args.mfl):
        print("Error: file not found: %s" % args.mfl, file=sys.stderr)
        sys.exit(2)

    try:
        parser = MflParser(args.mfl)
    except Exception as exc:
        print("Error parsing %s: %s" % (args.mfl, exc), file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(parser.to_json())
        sys.exit(0)

    if args.components:
        for i, name in enumerate(parser.components):
            amt = parser.amounts[i] if i < len(parser.amounts) else "?"
            print("  %d. %s  (%.4g)" % (i + 1, name, amt))
        sys.exit(0)

    if args.table_config:
        tc = parser.table_config
        if not tc:
            print("No table command found in %s" % args.mfl)
            sys.exit(1)
        for k, v in tc.items():
            if k == "enthalpy_values":
                print("  %s: [%d values]" % (k, len(v)))
            else:
                print("  %s: %s" % (k, v))
        sys.exit(0)

    # Default: summary
    print("Multiflash .mfl Summary")
    print("=" * 40)
    print("File:       %s" % os.path.basename(args.mfl))
    if parser.version:
        print("Version:    %s" % parser.version)
    if parser.date:
        print("Date:       %s" % parser.date)
    print()

    print("Components (%d):" % len(parser.components))
    for i, name in enumerate(parser.components):
        amt = parser.amounts[i] if i < len(parser.amounts) else "?"
        print("  %d. %-10s  %.4g" % (i + 1, name, amt))
    print()

    print("EOS Model:  %s" % parser.eos_model)
    if parser.models:
        print("All models (%d):" % len(parser.models))
        for m in parser.models:
            print("  %s  %s" % (m["name"], " ".join(m["args"])))
    print()

    if parser.phases:
        print("Phases (%d):" % len(parser.phases))
        for ph in parser.phases:
            print("  %s (%s) -> %s" % (
                ph["name"], ph["type"], ", ".join(ph["models"])))
    print()

    if parser.units:
        print("Units:")
        for k, v in parser.units.items():
            print("  %-14s %s" % (k, v))
    print()

    tc = parser.table_config
    if tc:
        print("Table config:")
        for k, v in tc.items():
            if k == "enthalpy_values":
                print("  %-14s [%d values]" % (k, len(v)))
            else:
                print("  %-14s %s" % (k, v))

    sys.exit(0)


if __name__ == "__main__":
    main()
