"""
mfl_writer.py -- Create or modify Multiflash .mfl command files.

Builds .mfl scripts for the Multiflash thermodynamic engine that generate
.tab PVT tables consumed by OLGA simulations.

Usage as a library:
    from mfl_writer import MflWriter
    w = MflWriter.from_scratch(['CO2', 'N2'], [99.7, 0.3])
    w.set_table_config('C:/output/Case1.tab', pmin=0.01, pmax=200)
    w.save('Case1.mfl')

    w2 = MflWriter.from_file('existing.mfl')
    w2.set_components(['CO2', 'H2'], [99.7, 0.3])
    w2.save('modified.mfl')

Standalone usage:
    python mfl_writer.py --components CO2,N2 --amounts 99.7,0.3 --output new.mfl
    python mfl_writer.py --modify existing.mfl --amounts 95.0,5.0 --output modified.mfl

Exit codes: 0=success, 1=domain error, 2=I/O error.
"""

import argparse
import os
import re
import sys
from datetime import datetime


# ---------------------------------------------------------------------------
# Ensure mfl_parser is importable (same scripts/ directory)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

# CPA-based template (for polar/associating fluids: CO2, MeOH, water)
_TEMPLATE_CPA = """\
#Multiflash version: 7.3.32  October 2022  #
#Date: {date}  #
remove all;
units temperature K pressure Pa enthalpy J/mol entropy J/mol/K volume m3/mol \
amounts mol viscosity Pas thcond W/m/K surten N/m diffusion m2/s;
datum enthalpy compound entropy compound;
set fractions; chardata INFOCHAR TBSOEREIDE;
puredata Infodata;
chardata Infochar TbSoereide;
Components overwrite
{components_block};
bipdata INFOBIPS OILANDGAS4;
BipSet CPABIP1 1 constant eos none;
BipSet CPABIP2 1 constant association J/mol;
BipSet CPABIP3 1 constant association J/mol;
model MCPA ASSOC PSAT CPABIP1 CPABIP2 CPABIP3;
model VSuperTRAPP SPVISC LFIT;
model TCSuperTRAPP SPTHCOND SPTHCOND;
model STMCSA MCSA MCS2P MCPA;
PD GAS gas MCPA MCPA MCPA VSuperTRAPP TCSuperTRAPP STMCSA;
PD LIQUID1 liquid MCPA MCPA MCPA VSuperTRAPP TCSuperTRAPP STMCSA;
keys LIQUID1 "*";
amounts {amounts_block};
tolamounts {tolamounts_block};
Temperature {temperature};
Pressure {pressure};
units temperature degC pressure bar enthalpy J/mol entropy J/mol/K \
volume m3/mol density mol/m3 amounts mole viscosity Pas thcond W/m/K \
surten N/m diffusion m2/s GOR sm3/sm3;
{table_block}"""

# SRK-based template (for hydrocarbon systems)
_TEMPLATE_SRK = """\
#Multiflash version: 7.3.32  October 2022  #
#Date: {date}  #
remove all;
units temperature K pressure Pa enthalpy J/mol entropy J/mol/K volume m3/mol \
amounts mol viscosity Pas thcond W/m/K surten N/m diffusion m2/s;
datum enthalpy compound entropy compound;
set fractions;
puredata Infodata;
Components overwrite
{components_block};
bipdata INFOBIPS OILANDGAS4;
model SRK;
model LVIS SPVISC;
model LTHC SPTHCOND;
model STNBS;
PD GAS gas SRK SRK SRK LVIS LTHC STNBS;
PD LIQUID1 liquid SRK SRK SRK LVIS LTHC STNBS;
keys LIQUID1 "*";
amounts {amounts_block};
tolamounts {tolamounts_block};
Temperature {temperature};
Pressure {pressure};
units temperature degC pressure bar enthalpy J/mol entropy J/mol/K \
volume m3/mol density mol/m3 amounts mole viscosity Pas thcond W/m/K \
surten N/m diffusion m2/s GOR sm3/sm3;
{table_block}"""

# OLGA 2025.1 / Multiflash 7.5 water-compatible template.
# Use this only when H2O is present. Legacy non-water cases keep the older
# OLGAPH path because PH tables can still be intentional for some workflows.
_TEMPLATE_OLGA2025_WATER = """\
#Multiflash version: 7.5.19  December 2024  #
#Date: {date}  #
remove all;
units temperature K pressure Pa enthalpy J/mol entropy J/mol/K volume m3/mol \
amounts mol viscosity Pas thcond W/m/K surten N/m diffusion m2/s;
datum enthalpy compound entropy compound;
set fractions; chardata INFOCHAR TBSOEREIDE;
puredata Infodata;
chardata Infochar TbSoereide;
Components overwrite
{components_block};
bipdata INFOBIPS OILANDGAS4;
BipSet CPABIP1 1 constant eos none;
BipSet CPABIP2 1 constant association J/mol;
BipSet CPABIP3 1 constant association J/mol;
BipSet LGSTBIP 1 constant eos none;
model MCPA ASSOC PSAT CPABIP1 CPABIP2 CPABIP3;
model VSuperTRAPP SPVISC LFIT;
model TCSuperTRAPP SPTHCOND SPTHCOND;
model STLGST LGST MCPA LGSTBIP;
PD GAS gas MCPA MCPA MCPA VSuperTRAPP TCSuperTRAPP STLGST;
PD LIQUID1 liquid MCPA MCPA MCPA VSuperTRAPP TCSuperTRAPP STLGST;
keys LIQUID1 "*";
PD WATER liquid MCPA MCPA MCPA VSuperTRAPP TCSuperTRAPP STLGST;
keys WATER AQUEOUS;
amounts {amounts_block};
tolamounts {tolamounts_block};
Temperature {temperature};
Pressure {pressure};
units temperature degC pressure barg enthalpy J/mol entropy J/mol/K \
volume m3/mol density g/cm3 amounts mole viscosity cP thcond W/m/K \
surten N/m diffusion m2/s GOR sm3/sm3;
{table_block}"""

# Map EOS names to templates
_TEMPLATE_MAP = {
    "MCPA": _TEMPLATE_CPA,
    "CPA": _TEMPLATE_CPA,
    "SRK": _TEMPLATE_SRK,
    "PR": _TEMPLATE_SRK,  # PR uses same structure as SRK
}


class PathLikeTitle:
    """Tiny helper to derive safe Multiflash table titles from output paths."""

    @staticmethod
    def from_path(path: str) -> str:
        base = os.path.splitext(os.path.basename(path.replace("\\", "/")))[0]
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_")
        return cleaned or "OLGA_Table"


def _wrap_values(values, per_line=8):
    """Format numeric grid values into wrapped Multiflash lines."""
    tokens = ["%g" % value for value in values]
    chunks = [" ".join(tokens[i:i + per_line]) for i in range(0, len(tokens), per_line)]
    return "\n".join(chunks)

# ---------------------------------------------------------------------------
# MflWriter
# ---------------------------------------------------------------------------

class MflWriter:
    """Create or modify Multiflash .mfl files.

    Can either modify an existing .mfl or build one from scratch.
    """

    def __init__(self):
        self._components = []
        self._amounts = []
        self._eos = "MCPA"
        self._output_path = ""
        self._pmin = 0.01
        self._pmax = 200
        self._tmin = -10
        self._tmax = 150
        self._min_h_points = 600
        self._temperature = 293.15
        self._pressure = 101325
        self._raw_text = None  # set when loaded from file

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, mfl_path: str):
        """Load an existing .mfl file for modification."""
        from mfl_parser import MflParser

        obj = cls()
        parser = MflParser(mfl_path)

        obj._components = parser.components
        obj._amounts = parser.amounts
        obj._eos = parser.eos_model or "MCPA"
        obj._temperature = parser.temperature if parser.temperature is not None else 293.15
        obj._pressure = parser.pressure if parser.pressure is not None else 101325

        tc = parser.table_config
        if tc:
            obj._output_path = tc.get("output_path", "")
            obj._pmin = tc.get("Pmin", 0.01)
            obj._pmax = tc.get("Pmax", 200)
            obj._tmin = tc.get("Tmin", -10)
            obj._tmax = tc.get("Tmax", 150)
            obj._min_h_points = int(tc.get("minHPoints", 600))

        # Keep raw text for modify-in-place operations
        try:
            with open(mfl_path, "r", encoding="utf-8") as f:
                obj._raw_text = f.read()
        except UnicodeDecodeError:
            with open(mfl_path, "r", encoding="latin-1") as f:
                obj._raw_text = f.read()

        return obj

    @classmethod
    def from_scratch(cls, components, amounts, eos="MCPA",
                     pmin=0.01, pmax=200, tmin=-10, tmax=150,
                     min_h_points=600):
        """Create a new .mfl from parameters.

        Parameters
        ----------
        components : list[str]
            Component names, e.g. ['CO2', 'N2'].
        amounts : list[float]
            Mole fractions, e.g. [99.7, 0.3].
        eos : str
            Equation of state model name (default 'MCPA').
        pmin, pmax : float
            Pressure range in bar.
        tmin, tmax : float
            Temperature range in degC.
        min_h_points : int
            Minimum enthalpy grid points.
        """
        obj = cls()
        obj._components = list(components)
        obj._amounts = list(amounts)
        obj._eos = eos
        obj._pmin = pmin
        obj._pmax = pmax
        obj._tmin = tmin
        obj._tmax = tmax
        obj._min_h_points = min_h_points
        return obj

    # ------------------------------------------------------------------
    # Setters
    # ------------------------------------------------------------------

    def set_components(self, components, amounts):
        """Set components and mole fractions."""
        self._components = list(components)
        self._amounts = list(amounts)

    def set_table_config(self, output_path, pmin=None, pmax=None,
                         tmin=None, tmax=None, min_h_points=None):
        """Set table output configuration."""
        self._output_path = output_path
        if pmin is not None:
            self._pmin = pmin
        if pmax is not None:
            self._pmax = pmax
        if tmin is not None:
            self._tmin = tmin
        if tmax is not None:
            self._tmax = tmax
        if min_h_points is not None:
            self._min_h_points = min_h_points

    def set_eos(self, model_name):
        """Set equation of state model."""
        self._eos = model_name

    def set_temperature(self, value):
        """Set reference temperature (K)."""
        self._temperature = value

    def set_pressure(self, value):
        """Set reference pressure (Pa)."""
        self._pressure = value

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> str:
        """Return the .mfl text content."""
        if self._raw_text is not None:
            return self._build_modified()
        return self._build_from_template()

    def save(self, filepath: str):
        """Write .mfl to disk."""
        content = self.build()
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    # ------------------------------------------------------------------
    # Internal: build from template
    # ------------------------------------------------------------------

    def _build_from_template(self) -> str:
        """Generate .mfl from template."""
        if self._uses_olga2025_water_table():
            template = _TEMPLATE_OLGA2025_WATER
        else:
            template = _TEMPLATE_MAP.get(self._eos.upper(), _TEMPLATE_CPA)

        # Components block: "1 CO2 \n2 N2"
        comp_lines = []
        for i, name in enumerate(self._components):
            comp_lines.append("%d %s" % (i + 1, name))
        components_block = " \n".join(comp_lines)

        # Amounts block
        amounts_block = " ".join("%.6g" % a for a in self._amounts)

        # Tolamounts block (zeros)
        tolamounts_block = " ".join("0." for _ in self._amounts)

        # Table block
        table_block = self._build_table_block()

        # Date
        now = datetime.now()
        date_str = now.strftime("%a %d %B %Y        Time:   %H:%M:%S")

        text = template.format(
            date=date_str,
            components_block=components_block,
            amounts_block=amounts_block,
            tolamounts_block=tolamounts_block,
            temperature=self._temperature,
            pressure=self._pressure,
            table_block=table_block,
        )

        # For PR model, replace SRK with PR in the generated text
        if self._eos.upper() == "PR":
            text = text.replace("model SRK", "model PR")
            text = text.replace(" SRK ", " PR ")

        return text

    def _uses_olga2025_water_table(self) -> bool:
        """Return True when the component set needs OLGA 2025 water syntax."""
        return any(c.upper() in {"H2O", "WATER"} for c in self._components)

    def _build_table_block(self) -> str:
        """Build the appropriate Multiflash table command block."""
        if not self._output_path:
            return ""

        if self._uses_olga2025_water_table():
            return self._build_olga2025_water_table_block()
        return self._build_legacy_olgaph_table_block()

    def _build_legacy_olgaph_table_block(self) -> str:
        """Build the legacy pressure-enthalpy table OLGAPH command block."""
        out_path = self._output_path.replace("\\", "/")
        lines = [
            'table OLGAPH',
            '"%s" info' % out_path,
            'units temperature degC pressure bar enthalpy J/mol;',
            'Pmin %.6g Pmax %.6g' % (self._pmin, self._pmax),
            'Tmin %.6g Tmax %.6g' % (self._tmin, self._tmax),
            'minHPoints %d' % self._min_h_points,
        ]
        return " \n".join(lines) + ";"

    def _build_olga2025_water_table_block(self) -> str:
        """Build an OLGA 2025-compatible PT table block for aqueous water cases."""
        out_path = self._output_path.replace("\\", "/")
        title = PathLikeTitle.from_path(out_path)
        tmin = self._tmin
        tmax = 50 if self._tmax == 150 else self._tmax
        pmin = 0 if self._pmin == 0.01 else self._pmin
        pmax = 5 if self._pmax == 200 else self._pmax
        temperatures = list(range(int(tmin), int(tmax) + 1))
        if not temperatures:
            temperatures = list(range(-10, 51))
        pressures = [round(pmin + 0.05 * i, 10) for i in range(int(round((pmax - pmin) / 0.05)) + 1)]
        if not pressures:
            pressures = [round(0.05 * i, 10) for i in range(101)]
        lines = [
            'table OLGA "%s" info HAWATER title %s' % (out_path, title),
            ' temperatures degC ' + _wrap_values(temperatures, per_line=8),
            ' pressures barg ' + _wrap_values(pressures, per_line=10) + ';',
            'set physprops 2VCS',
        ]
        return "\n".join(lines) + ";"

    # ------------------------------------------------------------------
    # Internal: build modified from existing
    # ------------------------------------------------------------------

    def _build_modified(self) -> str:
        """Modify the raw text in-place, replacing known sections."""
        text = self._raw_text

        # Replace components block
        text = self._replace_components(text)

        # Replace amounts
        text = self._replace_amounts(text)

        # Replace table config output path and ranges
        text = self._replace_table_config(text)

        return text

    def _replace_components(self, text: str) -> str:
        """Replace Components ... ; block."""
        comp_lines = []
        for i, name in enumerate(self._components):
            comp_lines.append("%d %s" % (i + 1, name))
        new_block = "Components overwrite\n" + " \n".join(comp_lines)

        pattern = re.compile(
            r"Components\s+overwrite\s+.*?(?=;)", re.DOTALL | re.IGNORECASE
        )
        result = pattern.sub(new_block, text, count=1)
        return result

    def _replace_amounts(self, text: str) -> str:
        """Replace amounts ... ; line."""
        new_amounts = "amounts " + " ".join("%.6g" % a for a in self._amounts)

        # Match 'amounts' at start of command (not 'tolamounts')
        pattern = re.compile(
            r"(?<!\w)amounts\s+[\d.\s]+(?=;)", re.IGNORECASE
        )
        result = pattern.sub(new_amounts, text, count=1)

        # Also fix tolamounts to match component count
        new_tol = "tolamounts " + " ".join("0." for _ in self._amounts)
        tol_pattern = re.compile(
            r"tolamounts\s+[\d.\s]+(?=;)", re.IGNORECASE
        )
        result = tol_pattern.sub(new_tol, result, count=1)

        return result

    def _replace_table_config(self, text: str) -> str:
        """Replace table output path and P/T range parameters."""
        if self._output_path:
            out_path = self._output_path.replace("\\", "/")
            # Replace quoted path in table command
            # Match the first quoted string after table OLGAPH or table OLGA.
            pattern = re.compile(
                r'(table\s+(?:OLGAPH|OLGA)\s*\n?\s*)"[^"]*"',
                re.IGNORECASE,
            )
            text = pattern.sub(r'\1"%s"' % out_path, text, count=1)

        # Replace numeric parameters
        for param, value in [
            ("Pmin", self._pmin), ("Pmax", self._pmax),
            ("Tmin", self._tmin), ("Tmax", self._tmax),
            ("minHPoints", self._min_h_points),
        ]:
            pattern = re.compile(
                r"\b" + param + r"\s+[-+]?\d*\.?\d+(?:[eE][+-]?\d+)?",
                re.IGNORECASE,
            )
            text = pattern.sub("%s %g" % (param, value), text, count=1)

        return text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mfl_writer.py",
        description="Create or modify Multiflash .mfl files.",
    )
    p.add_argument("--modify", metavar="MFL_FILE", default=None,
                   help="Existing .mfl file to modify")
    p.add_argument("--components", metavar="LIST", default=None,
                   help="Comma-separated component names (e.g. CO2,N2)")
    p.add_argument("--amounts", metavar="LIST", default=None,
                   help="Comma-separated mole fractions (e.g. 99.7,0.3)")
    p.add_argument("--eos", metavar="MODEL", default="MCPA",
                   help="EOS model name (default: MCPA)")
    p.add_argument("--pmin", type=float, default=0.01,
                   help="Minimum pressure in bar (default: 0.01)")
    p.add_argument("--pmax", type=float, default=200,
                   help="Maximum pressure in bar (default: 200)")
    p.add_argument("--tmin", type=float, default=-10,
                   help="Minimum temperature in degC (default: -10)")
    p.add_argument("--tmax", type=float, default=150,
                   help="Maximum temperature in degC (default: 150)")
    p.add_argument("--min-h-points", type=int, default=600,
                   help="Minimum enthalpy grid points (default: 600)")
    p.add_argument("--tab-path", metavar="PATH", default=None,
                   help="Output .tab file path for table command")
    p.add_argument("--output", "-o", metavar="MFL_FILE", required=True,
                   help="Output .mfl file path")
    return p


def main():
    ap = _build_parser()
    args = ap.parse_args()

    if args.modify:
        # Modify existing file
        if not os.path.isfile(args.modify):
            print("Error: file not found: %s" % args.modify, file=sys.stderr)
            sys.exit(2)

        try:
            writer = MflWriter.from_file(args.modify)
        except Exception as exc:
            print("Error loading %s: %s" % (args.modify, exc),
                  file=sys.stderr)
            sys.exit(1)

        if args.components:
            comp_list = [c.strip() for c in args.components.split(",")]
            if args.amounts:
                amt_list = [float(a.strip()) for a in args.amounts.split(",")]
            else:
                amt_list = writer._amounts
            if len(comp_list) != len(amt_list):
                print("Error: components count (%d) != amounts count (%d)"
                      % (len(comp_list), len(amt_list)), file=sys.stderr)
                sys.exit(1)
            writer.set_components(comp_list, amt_list)
        elif args.amounts:
            amt_list = [float(a.strip()) for a in args.amounts.split(",")]
            if len(amt_list) != len(writer._components):
                print("Error: amounts count (%d) != existing components count (%d)"
                      % (len(amt_list), len(writer._components)),
                      file=sys.stderr)
                sys.exit(1)
            writer._amounts = amt_list

        if args.tab_path:
            writer.set_table_config(args.tab_path, args.pmin, args.pmax,
                                    args.tmin, args.tmax, args.min_h_points)

    else:
        # Create from scratch
        if not args.components or not args.amounts:
            print("Error: --components and --amounts are required "
                  "when creating a new .mfl", file=sys.stderr)
            sys.exit(1)

        comp_list = [c.strip() for c in args.components.split(",")]
        amt_list = [float(a.strip()) for a in args.amounts.split(",")]

        if len(comp_list) != len(amt_list):
            print("Error: components count (%d) != amounts count (%d)"
                  % (len(comp_list), len(amt_list)), file=sys.stderr)
            sys.exit(1)

        writer = MflWriter.from_scratch(
            components=comp_list,
            amounts=amt_list,
            eos=args.eos,
            pmin=args.pmin,
            pmax=args.pmax,
            tmin=args.tmin,
            tmax=args.tmax,
            min_h_points=args.min_h_points,
        )

        if args.tab_path:
            writer.set_table_config(args.tab_path)

    try:
        writer.save(args.output)
    except OSError as exc:
        print("Error writing %s: %s" % (args.output, exc), file=sys.stderr)
        sys.exit(2)

    print("Saved: %s" % args.output)
    print("  Components: %s" % ", ".join(writer._components))
    print("  Amounts:    %s" % ", ".join("%.6g" % a for a in writer._amounts))
    print("  EOS:        %s" % writer._eos)
    sys.exit(0)


if __name__ == "__main__":
    main()
