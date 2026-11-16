"""Stage 1 fluid-table backend (plans/tab-generation.md T1–T4).

Drafts a Multiflash ``.mfl`` from an explicit user composition, opens the
bundled Multiflash GUI on an explicit user action only, and picks up the
produced ``.tab`` for validation. No guessed physics: components resolve
against the read-only Multiflash databank, the composition must sum to 1
within 1e-6, the EOS model is an explicit user choice, and no BIPs or
property values are ever invented.
"""

from __future__ import annotations

import difflib
import glob
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

SUPPORTED_MODELS = ("PR", "PRA", "SRK", "RKSA", "CPA")

# Exact unit keywords from the mfcmd.pdf units table (p.84). Anything else —
# including "C", "bara" and "psia" — is rejected or mapped below, because the
# GUI rejected them (Fix-up 2: "temperature C" fails with MFL 1154, "degC" loads).
SUPPORTED_TEMPERATURE_UNITS = ("K", "degC", "degF", "degR")
SUPPORTED_PRESSURE_UNITS = (
    "Pa", "kPa", "Mpa", "bar", "barg", "atm", "atmg",
    "psi", "psig", "mmHg", "inwg", "at", "atg",
)
_TEMPERATURE_ALIASES = {"C": "degC"}

# Each user-facing EOS choice maps to the vendor sample shipped with OLGA
# whose model/pd/keys/bipdata/puredata lines the draft copies verbatim.
# Samples are read read-only from the installed OLGA at runtime (never
# vendored, never written); line ranges cover the whole sample file.
# RKS is the Redlich-Kwong-Soave (SRK) equation, RKSA its advanced variant,
# and MASSOC is Multiflash's CPA-family (ASSOC) model (hydcpa.mfl: "Define
# the CPA model as the thermodynamic model MASSOC"). Drafts substitute only
# components, amounts, units, the label, the output path and the T/P grids.
_MODEL_TEMPLATES: dict[str, dict[str, object]] = {
    "PR": {"file": "PR.MFL", "sample_lines": "1-62", "kind": "config", "handles_water": True},
    "PRA": {"file": "PRA.MFL", "sample_lines": "1-65", "kind": "config", "handles_water": True},
    "SRK": {"file": "RKS.MFL", "sample_lines": "1-62", "kind": "config", "handles_water": True},
    "RKSA": {"file": "RKSA.MFL", "sample_lines": "1-66", "kind": "config", "handles_water": True},
    "CPA": {"file": "OLGA.MFL", "sample_lines": "1-58", "kind": "full", "handles_water": True},
}


def _sample_dir() -> Path:
    """The read-only vendor sample directory under the detected OLGA install."""
    for pattern in _install_globs():
        for exe in sorted(glob.glob(pattern)):
            candidate = Path(exe).parent / "MFL files"
            if candidate.is_dir():
                return candidate
    raise FluidTableError(
        "Multiflash sample templates are unavailable: MFBJ01.exe was not "
        "found under the detected OLGA install."
    )


def multiflash_path(path_value: str) -> str:
    """Render a path the way Multiflash on Windows expects it.

    A WSL-style ``/mnt/c/...`` path becomes ``C:\\...``; anything else
    passes through unchanged. Drafts must never carry /mnt/c paths.
    """
    text = str(path_value).replace("\\", "/")
    match = re.match(r"^/mnt/([A-Za-z])/(.*)$", text)
    if match:
        return f"{match.group(1).upper()}:\\" + match.group(2).replace("/", "\\")
    return str(path_value)


def canonical_temperature_unit(unit: object) -> str:
    """Map a user temperature unit to exactly the mfcmd p.84 keyword."""
    token = unit.strip() if isinstance(unit, str) else ""
    for alias, canonical in _TEMPERATURE_ALIASES.items():
        if token.casefold() == alias.casefold():
            return canonical
    for canonical in SUPPORTED_TEMPERATURE_UNITS:
        if token.casefold() == canonical.casefold():
            return canonical
    raise FluidTableError(
        f"Unknown temperature unit {unit!r}; use one of: "
        f"{', '.join(SUPPORTED_TEMPERATURE_UNITS)} (mfcmd p.84)."
    )


def canonical_pressure_unit(unit: object) -> str:
    """Map a user pressure unit to exactly the mfcmd p.84 keyword."""
    token = unit.strip() if isinstance(unit, str) else ""
    for canonical in SUPPORTED_PRESSURE_UNITS:
        if token.casefold() == canonical.casefold():
            return canonical
    raise FluidTableError(
        f"Unknown pressure unit {unit!r}; use one of: "
        f"{', '.join(SUPPORTED_PRESSURE_UNITS)} (mfcmd p.84)."
    )
COMPOSITION_TOLERANCE = 1e-6

_FLUID_LABEL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")
_COMPONENT_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_ .,#+/-]{0,127}")
_PVT_LABEL = re.compile(r'PVTTABLE\s+LABEL\s*=\s*"?([^",\s]+)"?', re.IGNORECASE)
_TAB_PATH_IN_MFL = re.compile(r'"([^"]+\.tab)"', re.IGNORECASE)
_HEADER_BYTES = 262_144


class FluidTableError(ValueError):
    """A user-correctable fluid-table request error."""


class UnknownComponentError(FluidTableError):
    """A component name outside the Multiflash databank, with suggestions."""

    def __init__(self, name: str, suggestions: Sequence[str]) -> None:
        self.name = name
        self.suggestions = list(suggestions)
        hint = f" Did you mean: {', '.join(self.suggestions)}?" if self.suggestions else ""
        super().__init__(f"Unknown component {name!r}.{hint}")


def _install_globs() -> list[str]:
    home = os.environ.get("MULTIFLASH_HOME", "").strip()
    patterns = [os.path.join(home, "MFBJ01.exe")] if home else []
    patterns.extend([
        "/mnt/c/Program Files/Schlumberger/OLGA*/Tools/Multiflash/MFBJ01.exe",
        "/mnt/c/Program Files (x86)/Schlumberger/OLGA*/Tools/Multiflash/MFBJ01.exe",
        "/mnt/c/Program Files/SLB/OLGA*/Tools/Multiflash/MFBJ01.exe",
        "C:/Program Files/Schlumberger/OLGA*/Tools/Multiflash/MFBJ01.exe",
        "C:/Program Files/SLB/OLGA*/Tools/Multiflash/MFBJ01.exe",
    ])
    return patterns


def find_multiflash() -> dict[str, Any]:
    """Locate MFBJ01.exe under the detected OLGA install, without launching it."""
    for pattern in _install_globs():
        matches = sorted(glob.glob(pattern))
        if matches:
            exe = matches[-1]
            return {
                "found": True,
                "exe": exe,
                "home": str(Path(exe).parent),
                "message": f"Multiflash found at {exe}.",
            }
    return {
        "found": False,
        "exe": None,
        "home": None,
        "message": (
            "Multiflash (MFBJ01.exe) was not found under the detected OLGA "
            "install. Set MULTIFLASH_HOME to its Tools\\Multiflash folder."
        ),
    }


def databank_path(explicit: str | None = None) -> str | None:
    """Resolve the read-only component databank, or None when unavailable."""
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate)
        raise FluidTableError(f"Databank not found: {candidate}")
    home = os.environ.get("MULTIFLASH_HOME", "").strip()
    if home and (Path(home) / "infodata.db").is_file():
        return str(Path(home) / "infodata.db")
    for pattern in _install_globs():
        for exe in sorted(glob.glob(pattern)):
            candidate = Path(exe).parent / "infodata.db"
            if candidate.is_file():
                return str(candidate)
    return None


def databank_names(db_path: str | None = None) -> dict[str, str]:
    """Upper-cased synonym map to canonical databank names, opened read-only."""
    resolved = databank_path(db_path)
    if resolved is None:
        raise FluidTableError(
            "The Multiflash component databank (infodata.db) is unavailable."
        )
    uri = f"file:{resolved}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        names: dict[str, str] = {}
        for (canonical,) in connection.execute("SELECT COMPONENTName FROM Components"):
            names[str(canonical).upper()] = str(canonical)
        try:
            rows = connection.execute(
                "SELECT ID, Synonyms FROM Synonyms"
            ).fetchall()
            canonical_by_id = {
                row[0]: row[1]
                for row in connection.execute("SELECT ID, COMPONENTName FROM Components")
            }
            for ident, synonym in rows:
                canonical = canonical_by_id.get(ident)
                if canonical:
                    names.setdefault(str(synonym).upper(), str(canonical))
        except sqlite3.Error:
            pass
        return names
    finally:
        connection.close()


def databank_spelling(name: str, names: Mapping[str, str]) -> str:
    """Databank key for an engine formula or alias. A missing engine returns ``name``.

    A name that is already a databank key is returned unchanged (``CO2``, ``iC4``,
    ``nC4``). Otherwise the first one-word engine alias the databank knows is used
    (``C3H8`` becomes ``PROPANE``, ``i-C4`` becomes ``ISOBUTANE``). Release builds
    omit ``olga_companion.pvt_engine``; that import failure leaves the name unchanged.
    """
    if name.upper() in names:
        return name
    try:
        from olga_companion.pvt_engine.components import UnknownComponentError, get_component
    except ImportError:
        return name
    try:
        aliases = get_component(name).aliases
    except UnknownComponentError:
        return name
    for alias in aliases:
        if " " not in alias and alias.upper() in names:
            return alias.upper()
    return name


def spell_components(components: Sequence[Any], names: Mapping[str, str]) -> list[Any]:
    """Copy ``components``, spelling each string name with ``databank_spelling``."""
    prepared: list[Any] = []
    for entry in components:
        if isinstance(entry, Mapping) and isinstance(entry.get("name"), str):
            prepared.append({**entry, "name": databank_spelling(entry["name"], names)})
        else:
            prepared.append(entry)
    return prepared


def suggest_names(name: str, names: Mapping[str, str], count: int = 3) -> list[str]:
    """Closest databank names for an unknown component."""
    candidates = sorted(set(names.values()))
    return difflib.get_close_matches(name.upper(), candidates, n=count, cutoff=0.5)


_PLAIN_MFL_NAME = re.compile(r"[A-Za-z0-9_]+")
_SHORT_MFL_ID = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _databank_lookup() -> dict[str, str]:
    """The databank synonym map, looked up at call time."""
    return databank_names()


def mfl_component_name(canonical: str, names: Mapping[str, str]) -> str:
    """The component spelling an ``.mfl`` draft writes for a databank entry.

    A plain one-word name is written as it is (``PROPANE``). Multiflash 7.3
    failed to load ``CARBON DIOXIDE`` written bare (10067/10423) while the vendor
    samples name the same entry ``CO2``, so an entry with a space or punctuation is
    written by its shortest letters-and-digits databank synonym when one exists
    (``CO2``, ``H2S``, ``MEG``). Without one it is written in double quotes, the
    way the vendor sample GERG-2008_template.mfl writes ``"carbon dioxide"``.
    """
    if _PLAIN_MFL_NAME.fullmatch(canonical):
        return canonical
    shorts = sorted(
        (synonym for synonym, target in names.items()
         if target == canonical and _SHORT_MFL_ID.fullmatch(synonym)),
        key=lambda synonym: (len(synonym), synonym),
    )
    return shorts[0] if shorts else f'"{canonical}"'


def validate_label(label: object) -> str:
    """A fluid label must match the PVT label grammar the toolkit can resolve."""
    if not isinstance(label, str) or not label.strip():
        raise FluidTableError("A fluid label is required.")
    canonical = label.strip()
    if _FLUID_LABEL.fullmatch(canonical) is None:
        raise FluidTableError(
            f"Invalid fluid label {label!r}; use letters, digits, and _ . - only."
        )
    try:
        float(canonical)
    except ValueError:
        pass
    else:
        raise FluidTableError(
            f"Invalid fluid label {label!r}; it must not look numeric."
        )
    return canonical


def validate_model(model: object, supported: Sequence[str] = SUPPORTED_MODELS) -> str:
    """The EOS model is an explicit documented choice; there is no default."""
    if not isinstance(model, str) or not model.strip():
        raise FluidTableError(
            f"An EOS model is required. Choose one of: {', '.join(supported)}"
        )
    choice = model.strip()
    if choice not in supported:
        raise FluidTableError(
            f"Unknown model {choice!r}. Choose one of: {', '.join(supported)}"
        )
    return choice


def validate_composition(
    components: Sequence[Mapping[str, Any]],
    names: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Canonicalize names via the databank and require fractions summing to 1."""
    if not components:
        raise FluidTableError("At least one component with a mole fraction is required.")
    lookup = dict(names) if names is not None else databank_names()
    resolved: list[dict[str, Any]] = []
    for entry in components:
        if not isinstance(entry, Mapping):
            raise FluidTableError("Each component must name a databank entry and a mole fraction.")
        raw_name = entry.get("name")
        fraction = entry.get("mole_fraction")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise FluidTableError("Each component must name a databank entry.")
        token = raw_name.strip()
        if _COMPONENT_TOKEN.fullmatch(token) is None:
            raise FluidTableError(f"Invalid component name {raw_name!r}.")
        canonical = lookup.get(token.upper())
        if canonical is None:
            raise UnknownComponentError(token, suggest_names(token, lookup))
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
            raise FluidTableError(f"Mole fraction for {token!r} must be a number.")
        value = float(fraction)
        if value < 0.0 or value > 1.0 or value != value:
            raise FluidTableError(f"Mole fraction for {token!r} must be within [0, 1].")
        resolved.append({"name": canonical, "mole_fraction": value})
    total = sum(item["mole_fraction"] for item in resolved)
    if abs(total - 1.0) > COMPOSITION_TOLERANCE:
        raise FluidTableError(
            f"Mole fractions sum to {total:.9f}, not 1 (tolerance {COMPOSITION_TOLERANCE:g})."
        )
    return resolved


def validate_grid(values: object, kind: str) -> list[float]:
    """A temperature or pressure grid: at least two finite points."""
    if not isinstance(values, (list, tuple)) or len(values) < 2:
        raise FluidTableError(f"At least two {kind} grid points are required.")
    points: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FluidTableError(f"Each {kind} grid point must be a number.")
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise FluidTableError(f"Each {kind} grid point must be finite.")
        points.append(number)
    return points


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return format(value, ".12g")


def build_table_command(
    tab_abs_path: str,
    fluid_label: str,
    temperatures: Sequence[float],
    temperature_unit: str,
    pressures: Sequence[float],
    pressure_unit: str,
    hawater: bool = False,
) -> str:
    """Render the exact ``table Olga ...`` command per mfcmd p.80."""
    label = validate_label(fluid_label)
    temperature_unit = canonical_temperature_unit(temperature_unit)
    pressure_unit = canonical_pressure_unit(pressure_unit)
    temps = validate_grid(temperatures, "temperature")
    press = validate_grid(pressures, "pressure")
    if not tab_abs_path or not str(tab_abs_path).strip():
        raise FluidTableError("An absolute .tab path is required for the table command.")
    options = " HAWATER" if hawater else ""
    return (
        f'table Olga "{multiflash_path(tab_abs_path)}"{options} title "{label}" '
        f"temperatures {temperature_unit} "
        + " ".join(_format_number(value) for value in temps)
        + f"; pressures {pressure_unit} "
        + " ".join(_format_number(value) for value in press)
        + "; ;"
    )


def template_name(model: str) -> str:
    """File name of the vendor sample for a user-facing EOS choice."""
    choice = validate_model(model)
    return str(_MODEL_TEMPLATES[choice]["file"])


def template_text(model: str) -> str:
    """The verbatim vendor template for a user-facing EOS choice.

    Read read-only from the installed OLGA sample directory at runtime;
    universal newlines give LF endings in the returned text.
    """
    choice = validate_model(model)
    entry = _MODEL_TEMPLATES[choice]
    return (_sample_dir() / str(entry["file"])).read_text(encoding="utf-8", errors="replace")


def _reference_block(
    resolved: Sequence[Mapping[str, Any]],
    temperatures: Sequence[float],
    temperature_unit: str,
    pressures: Sequence[float],
    pressure_unit: str,
    spelled: Sequence[str] | None = None,
) -> list[str]:
    """Composition, reference conditions and mole units in vendor order."""
    spelled = list(spelled) if spelled is not None else [item["name"] for item in resolved]
    lines = ["Components overwrite"]
    for index, name in enumerate(spelled, start=1):
        lines.append(f"{index} {name}")
    lines[-1] += " ;"
    lines.append(
        "amounts " + " ".join(_format_number(item["mole_fraction"]) for item in resolved) + ";"
    )
    lines.append("Temperature 293.15;")
    lines.append("Pressure 101325;")
    lines.append(
        f"units temperature {temperature_unit} pressure {pressure_unit} enthalpy J/mol "
        "entropy J/mol/K volume m3/mol amounts mole viscosity Pas thcond W/m/K "
        "surten N/m diffusion m2/s GOR sm3/sm3;"
    )
    return lines


def _wrap_values(values: Sequence[float], per_line: int) -> list[str]:
    tokens = [_format_number(value) for value in values]
    return [
        " ".join(tokens[index:index + per_line])
        for index in range(0, len(tokens), per_line)
    ]


def _olga_table_block(
    tab_abs_path: str,
    fluid_label: str,
    temperatures: Sequence[float],
    pressures: Sequence[float],
) -> str:
    """Rebuild OLGA.MFL's bare-number table command with substituted fields.

    No hydrate file: CPA drafts carry no hydrate or ice phase.
    """
    win_tab = multiflash_path(tab_abs_path)
    temp_lines = _wrap_values(temperatures, 8)
    press_lines = _wrap_values(pressures, 5)
    lines = [f'table olga "{win_tab}" title "{fluid_label}" temperatures ' + temp_lines[0]]
    lines.extend("  " + line for line in temp_lines[1:])
    lines[-1] += " ; pressures"
    lines.extend("  " + line for line in press_lines)
    lines[-1] += " ; ;"
    return "\n".join(lines)


_COMPONENTS_PATTERN = re.compile(r"components overwrite\s+.*?;", re.IGNORECASE | re.DOTALL)
_AMOUNTS_PATTERN = re.compile(r"(?m)^amounts\s+[0-9.][^;]*;")
_TABLE_PATTERN = re.compile(r"table\s+olga\s+.*?\s*;\s*;[ \t]*\n?", re.IGNORECASE | re.DOTALL)
_MOLE_UNITS_PATTERN = re.compile(r"(?m)^(units temperature )K( pressure )bar( enthalpy.*)$")
# The hydrate and ice phase set of the vendor CPA file, removed as one set
# (models and the phase descriptors that use them), as in air_water_cpa.mfl.
_HYDRATE_ICE_PATTERN = re.compile(
    r"(?im)^(?:model\s+MHYD2MASSOC\b|model\s+MICEMASSOC\b|pd\s+HYDRATE2\b|pd\s+ICE\b)[^\n]*;[ \t]*\n"
)


def build_mfl_text(
    fluid_label: str,
    components: Sequence[Mapping[str, Any]],
    model: str,
    temperatures: Sequence[float],
    temperature_unit: str,
    pressures: Sequence[float],
    pressure_unit: str,
    tab_abs_path: str,
    databank_names: Mapping[str, str] | None = None,
    hawater: bool = False,
) -> str:
    """Render a draft from the choice's vendor template with only the user
    fields substituted (components, amounts, units, label, output path, T/P
    grids). Model/pd/keys/bipdata/puredata lines stay vendor-verbatim, except
    that a CPA draft drops the hydrate and ice phase set. That set must be
    exactly the four expected lines; a vendor template that differs fails the
    draft on purpose rather than leave a partial hydrate model behind."""
    label = validate_label(fluid_label)
    choice = validate_model(model)
    lookup = dict(databank_names) if databank_names is not None else _databank_lookup()
    resolved = validate_composition(components, lookup)
    spelled = [mfl_component_name(item["name"], lookup) for item in resolved]
    entry = _MODEL_TEMPLATES[choice]
    if "WATER" in [item["name"] for item in resolved] and not entry["handles_water"]:
        raise FluidTableError(
            f"Model {choice} has no aqueous-phase template; remove WATER or choose another model."
        )
    if not tab_abs_path or not str(tab_abs_path).strip():
        raise FluidTableError("An absolute .tab path is required for the table command.")
    temperature_unit = canonical_temperature_unit(temperature_unit)
    pressure_unit = canonical_pressure_unit(pressure_unit)
    template = template_text(choice)
    if entry["kind"] == "config":
        command = build_table_command(
            tab_abs_path, label, temperatures, temperature_unit,
            pressures, pressure_unit, hawater=hawater,
        )
        temps = validate_grid(temperatures, "temperature")
        press = validate_grid(pressures, "pressure")
        block = _reference_block(resolved, temps, temperature_unit, press, pressure_unit, spelled)
        block.append(command)
        return template.rstrip("\n") + "\n" + "\n".join(block) + "\n"
    if hawater:
        raise FluidTableError(
            "The CPA template (OLGA.MFL) has no HAWATER slot; "
            "enable high-accuracy water in the Multiflash GUI."
        )
    temps = validate_grid(temperatures, "temperature")
    press = validate_grid(pressures, "pressure")
    draft, count = _COMPONENTS_PATTERN.subn(
        "components overwrite\n"
        + "\n".join(f"{index} {name}" for index, name in enumerate(spelled, start=1))
        + " ;",
        template,
        count=1,
    )
    if count != 1:
        raise FluidTableError("The CPA template has no replaceable components block.")
    draft, count = _AMOUNTS_PATTERN.subn(
        "amounts " + " ".join(_format_number(item["mole_fraction"]) for item in resolved) + ";",
        draft,
        count=1,
    )
    if count != 1:
        raise FluidTableError("The CPA template has no replaceable amounts line.")
    # The vendor file is a recorded session with its table command first; run
    # as a script that is an empty system under K/Pa. Lift it out and emit it
    # last, after the model, components and the user's units (as the
    # Multiflash GUI-made air_water_cpa.mfl does).
    draft, count = _TABLE_PATTERN.subn("", draft, count=1)
    if count != 1:
        raise FluidTableError("The CPA template has no replaceable table command.")
    draft, count = _MOLE_UNITS_PATTERN.subn(
        lambda match: match.group(1) + temperature_unit + match.group(2) + pressure_unit + match.group(3),
        draft,
        count=1,
    )
    if count != 1:
        raise FluidTableError("The CPA template has no replaceable mole-units line.")
    draft, count = _HYDRATE_ICE_PATTERN.subn("", draft)
    if count != 4:
        raise FluidTableError("The CPA template's hydrate and ice lines are not the expected set of four.")
    return draft.rstrip() + "\n" + _olga_table_block(tab_abs_path, label, temps, press) + "\n"


def write_draft_mfl(mfl_path: str, mfl_text: str) -> dict[str, Any]:
    """Write a new .mfl exclusively; an existing path is never overwritten."""
    path = Path(mfl_path).expanduser()
    if path.suffix.casefold() != ".mfl":
        raise FluidTableError("The draft path must end in .mfl.")
    if not path.parent.is_dir():
        raise FluidTableError("The selected draft folder does not exist.")
    if os.path.lexists(path):
        raise FluidTableError(f"Draft destination already exists: {path.name}")
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(mfl_text)
    return {"mfl_path": str(path), "ok": True}


def expected_tab_for_mfl(mfl_path: str) -> str | None:
    """Extract the quoted .tab path from the draft's table command."""
    try:
        text = Path(mfl_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise FluidTableError(f"File not found: {Path(mfl_path).name}") from exc
    match = _TAB_PATH_IN_MFL.search(text)
    return match.group(1) if match else None


def launch_multiflash(exe: str, mfl_path: str | None = None) -> dict[str, Any]:
    """Start the Multiflash GUI. Call only from an explicit user action."""
    program = Path(exe)
    if not program.is_file():
        raise FluidTableError(f"Multiflash not found: {exe}")
    args = [str(program)]
    if mfl_path is not None:
        candidate = Path(mfl_path)
        if candidate.suffix.casefold() != ".mfl" or not candidate.is_file():
            raise FluidTableError(f"Draft .mfl not found: {mfl_path}")
        args.append(multiflash_path(str(candidate)))
    try:
        # The draft's relative "puredata Infodata" resolves against the working directory.
        process = subprocess.Popen(args, cwd=str(program.parent))  # noqa: S603
    except OSError as exc:
        raise FluidTableError(f"Multiflash did not start: {program.name}") from exc
    manual = (
        "In Multiflash: open the drafted .mfl and run it, then confirm "
        "the .tab appears at the table-command path."
        if mfl_path is None else
        "In Multiflash: run the opened .mfl script, then confirm the .tab "
        "appears at the table-command path."
    )
    return {"launched": True, "exe": str(program), "args": args,
            "pid": process.pid, "manual_steps": manual}


def declared_label(table: Path) -> str | None:
    """Read PVTTABLE LABEL without mutating the table."""
    with table.open("rb") as stream:
        header = stream.read(_HEADER_BYTES).decode("utf-8", errors="replace")
    found = _PVT_LABEL.search(header)
    return found[1] if found else None


def pickup_tab(tab_path: str, fluid_label: str | None = None) -> dict[str, Any]:
    """Validate a produced .tab and check its label; never mutates anything."""
    from . import fluids

    candidate = Path(tab_path).expanduser()
    if candidate.suffix.casefold() != ".tab" or not candidate.is_file():
        return {"found": False, "valid": False, "declared_label": None,
                "label_match": False, "errors": [{"message": f"File not found: {candidate.name}"}],
                "warnings": [], "link_proposal": None}
    before = candidate.read_bytes()
    inspection = fluids.inspect_tab(str(candidate))
    after = candidate.read_bytes()
    assert before == after, "pickup must not mutate the .tab"
    label = declared_label(candidate)
    expected = validate_label(fluid_label) if fluid_label else None
    match = expected is None or label == expected
    valid = bool(inspection.get("valid")) and match
    proposal = None
    if valid:
        proposal = {
            "tab_path": str(candidate),
            "fluid_label": label,
            "next_steps": (
                "Link the table with the normal edit + approval path: "
                "case_edit_plan set_fluid for the label (new cases set "
                "pvt_reference in the CaseSpec), then case_publish."
            ),
        }
    return {
        "found": True,
        "valid": valid,
        "declared_label": label,
        "label_match": match,
        "errors": inspection.get("validation_errors", []),
        "warnings": inspection.get("validation_warnings", []),
        "link_proposal": proposal,
    }
