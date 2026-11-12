"""Read a pipe table from CSV or xlsx with the standard library only.

An xlsx file is a zip of XML parts; only cached cell values are read, formulas are
never evaluated. Column headers are matched to the template names, their synonyms,
or an explicit column map, and length-type values are converted to metres.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree
from xml.parsers import expat

MAX_FILE_BYTES = 20 * 1024 * 1024
# OLE compound-document signature: a password-protected workbook starts
# with these 8 bytes instead of the zip magic.
_OLE2_SIGNATURE = bytes((0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1))
# Zip local-file-header magic: a real workbook is a zip, so the DRM-marker
# rule below must exclude it.
_ZIP_MAGIC = b"PK\x03\x04"
MAX_ZIP_ENTRIES = 2000
MAX_UNZIPPED_BYTES = 200 * 1024 * 1024
MAX_ROWS = 20_000
_MAX_COLUMNS = 16_384
# A row wider than this is refused instead of padded: padding every row out to
# a far column (XFD is column 16384) turns a kilobyte file into gigabytes.
_MAX_ROW_COLUMNS = 256
# Elements started inside one top-level row or shared string. Direct junk
# children refuse at once (see below), so this only bounds floods of allowed
# tags; a 32k-character string formatted one character per run starts about
# 131k elements (r, rPr, sz and t per run), while 200k-element floods refuse.
_MAX_SUBTREE_ELEMENTS = 150_000
# Params cut long header units to this display length; the full unit stays in
# the English reason. Twenty issues carrying a 30k-character unit must still
# fit the 16 KiB tool result cap.
_MAX_UNIT_DISPLAY = 48
_MAX_PART_BYTES = 50 * 1024 * 1024
# xlsx caps (Must-have C1): the sheet and the shared strings are streamed, so a
# hostile workbook cannot exhaust memory by quoting a huge shared string table.
MAX_SHARED_STRINGS = 200_000
MAX_SHARED_STRING_CHARS = 32_767
MAX_SHARED_STRING_TOTAL = 20_000_000
MAX_WORKBOOK_BYTES = 1024 * 1024
_CHUNK_BYTES = 64 * 1024
_HEADER_SCAN_ROWS = 50
_MIN_HEADER_MATCHES = 4
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

# Allowed children on the strict data path: only these elements are read.
# Anything else under a data parent is refused at its start event. Anything
# outside the data path (worksheet siblings of sheetData, extLst regions)
# is an opaque subtree: depth-capped, detached at close, never read.
# Only extLst regions are additionally counted, against per-region caps.
_DATA_CHILDREN: dict[str, frozenset[str]] = {
    "sst": frozenset({"si"}),
    "si": frozenset({"t", "r", "rPh", "phoneticPr"}),
    "r": frozenset({"rPr", "t"}),
    "rPh": frozenset({"t"}),
    "rPr": frozenset({
        "rFont", "charset", "family", "b", "i", "strike", "outline",
        "shadow", "condense", "extend", "color", "sz", "u", "vertAlign",
        "scheme",
    }),
    "sheetData": frozenset({"row"}),
    "row": frozenset({"c"}),
    "c": frozenset({"v", "f", "is"}),
    "is": frozenset({"t", "r", "rPh", "phoneticPr"}),
}
_M = _NS["m"]
_DATA_CHILD_TAGS: dict[str, frozenset[str]] = {
    f"{{{_M}}}{parent}": frozenset(f"{{{_M}}}{child}" for child in children)
    for parent, children in _DATA_CHILDREN.items()
}
_EXTLST_TAG = f"{{{_M}}}extLst"
# An opaque region nests this deep at most; deeper nesting refuses.
_MAX_OPAQUE_DEPTH = 32
# An extLst-rooted opaque region holds this many elements at most.
_MAX_OPAQUE_ELEMENTS = 100_000
# An extLst directly under sheetData is never legitimate: bound it tightly.
_MAX_SHEETDATA_EXT_ELEMENTS = 1_000


def _refuse_child(parent_tag: str, tag: str) -> None:
    """Refuse an element that is not an allowed child on the data path."""
    parent_local = parent_tag.split("}", 1)[-1]
    local = tag.split("}", 1)[-1]
    raise PipeTableError(f"{parent_local} holds {local}, which is not allowed here")


def _run_text(
    elem: ElementTree.Element | None, text_tag: str, run_tag: str,
) -> str:
    """Text of a shared or inline string, skipping phonetic guides.

    Only direct `t` children and direct `t` under `r` runs count; `rPh`
    text (furigana) and anything else never does. A missing element reads
    as empty text.
    """
    if elem is None:
        return ""
    parts: list[str] = []
    for child in elem:
        if child.tag == text_tag:
            parts.append(child.text or "")
        elif child.tag == run_tag:
            parts.extend(
                node.text or "" for node in child if node.tag == text_tag
            )
    return "".join(parts)

# Template field -> header spellings it also answers to (compared after normalising).
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "flowpath": ("flowpath", "flow_path", "line", "branch", "flowpath_name"),
    "pipe": ("pipe", "pipe_no", "pipe_name", "pipe_label", "pipe_id"),
    "from_node": ("from_node", "from", "start_node", "upstream", "upstream_node"),
    "to_node": ("to_node", "to", "end_node", "downstream", "downstream_node"),
    "length": ("length", "len", "pipe_length", "長さ"),
    "elevation": ("elevation", "height", "elevation_change", "dz", "rise"),
    "x": ("x", "end_x", "x_end", "x2", "x_to", "配管終点_x座標"),
    "y": ("y", "end_y", "y_end", "y2", "y_to", "配管終点_y座標"),
    "z": ("z", "end_z", "z_end", "z2", "z_to", "配管終点_z座標"),
    "x_start": ("x_start", "start_x", "x1", "x_from", "配管始点_x座標"),
    "y_start": ("y_start", "start_y", "y1", "y_from", "配管始点_y座標"),
    "z_start": ("z_start", "start_z", "z1", "z_from", "配管始点_z座標"),
    # Not "id": that is usually a row identifier; map it explicitly when it means a diameter.
    "inner_diameter": ("inner_diameter", "inner_diameter_actual", "internal_diameter", "diameter", "内径"),
    "roughness": ("roughness", "粗度"),
    "valve": ("valve", "valve_label", "valve_name"),
    "valve_position": ("valve_position",),
    "valve_diameter": ("valve_diameter",),
    # Not "schedule": a pipe schedule (Sch 40) column would be read as valve openings.
    "valve_schedule": ("valve_schedule",),
    "node": ("node", "node_label", "node_name", "boundary"),
    "node_kind": ("node_kind", "kind", "boundary_kind"),
    "pressure": ("pressure",),
    "temperature": ("temperature",),
    "gas_fraction": ("gas_fraction",),
    "water_fraction": ("water_fraction", "total_water_fraction"),
    "initial_void_fraction": ("initial_void_fraction", "start_void_fraction", "initial_void"),
    "mass_flow_kg_s": ("mass_flow", "mass_flow_kg_s", "massflow", "mass_flow_rate"),
}
_LENGTH_FIELDS = {"length", "elevation", "x", "y", "z", "x_start", "y_start", "z_start",
                  "inner_diameter", "roughness", "valve_diameter"}
# Coordinate columns only count when they carry a unit: a bare X/Y/Z header is
# informational (ignored), while x_m or x (m) is a pipe end point.
_UNIT_REQUIRED = {"x", "y", "z", "x_start", "y_start", "z_start"}
_TEXT_FIELDS = {"flowpath", "pipe", "from_node", "to_node", "valve", "valve_schedule", "node", "node_kind"}
_LENGTH_UNITS = {"m": 1.0, "mm": 0.001, "cm": 0.01}
_PRESSURE_UNITS = {"pa": 1.0, "kpa": 1e3, "mpa": 1e6, "bar": 1e5, "bara": 1e5}
_LOOKUP = {spelling: name for name, spellings in _SYNONYMS.items() for spelling in spellings}


class PipeTableError(ValueError):
    """The table cannot be read safely."""

    def __init__(self, reason: str, code: str = "") -> None:
        super().__init__(reason)
        self.code = code


# Stable codes for every reader refusal, so the app can show each problem in
# the user's language while the English reason stays for the model.
READER_ISSUE_CODES: tuple[str, ...] = (
    "reader_formula_no_cached",
    "reader_unknown_length_unit",
    "reader_not_a_number",
    "reader_missing_pressure_unit",
    "reader_unknown_temperature_unit",
    "reader_unknown_mass_flow_unit",
)


@dataclass(frozen=True)
class TableIssue:
    row: int
    column: str
    reason: str
    code: str = ""
    params: dict[str, object] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class PipeTable:
    rows: tuple[dict[str, object], ...]
    issues: tuple[TableIssue, ...]
    header_row: int
    ignored_columns: tuple[str, ...]
    sheet: str | None = None
    # 1-based line or sheet row of each entry in `rows`.
    lines: tuple[int, ...] = ()


@dataclass(frozen=True)
class _Column:
    field: str
    unit: str | None


def _split_header(text: str) -> tuple[str, str | None]:
    # Compatibility decomposition first, so full-width （ｍ） Ｘ ｍ read
    # as their ASCII halves before matching and unit extraction.
    lowered = unicodedata.normalize("NFKC", text).strip().lower()
    unit = None
    bracket = re.search(r"[\(\[]\s*([a-z]+)\s*[\)\]]", lowered)
    if bracket:
        unit = bracket.group(1)
        lowered = lowered[: bracket.start()] + lowered[bracket.end():]
    base = "_".join(re.findall(r"[a-z0-9\u3040-\u30ff\u4e00-\u9fff]+", lowered))
    if base not in _LOOKUP and re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", lowered):
        # A CJK header reads the same however its words are spaced or
        # line-broken, so drop the whitespace and re-read it.
        compact = re.sub(r"\s+", "", lowered)
        base = "_".join(re.findall(r"[a-z0-9\u3040-\u30ff\u4e00-\u9fff]+", compact))
    if base not in _LOOKUP:
        # Fall back to the ASCII-only reading, so a header that mixes CJK
        # with a known English spelling keeps mapping as before.
        base = "_".join(re.findall(r"[a-z0-9]+", lowered))
    if unit is None:
        suffix = re.fullmatch(r"(.+)_(mm|cm|m|pa|kpa|mpa|bar|bara|c|degc|k)", base)
        if suffix and suffix.group(1) in _LOOKUP:
            base, unit = suffix.group(1), suffix.group(2)
    return base, unit


def _column(text: str, column_map: Mapping[str, str] | None) -> _Column | None:
    if column_map is not None and text in column_map:
        base, unit = _split_header(column_map[text])
    else:
        base, unit = _split_header(text)
    field = _LOOKUP.get(base)
    if field is None:
        return None
    if field in _UNIT_REQUIRED and unit is None:
        return None
    return _Column(field, unit)


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        # "1,500" could be 1500 or 1.5; refuse it rather than guess. "0,05" is a decimal comma.
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+", text):
            return None
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return None


def _converted(
    column: _Column, value: object, unit_length: str | None,
) -> tuple[str, object | None, str | None, str, dict[str, object]]:
    """Return (output key, value, problem, code, params)."""
    if column.field in _TEXT_FIELDS:
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        text = str(value).strip()
        return column.field, text or None, None, "", {}
    number = _number(value)
    if column.field in _LENGTH_FIELDS:
        unit = column.unit or unit_length or "m"
        factor = _LENGTH_UNITS.get(unit)
        key = f"{column.field}_m"
        if factor is None:
            return key, None, f"unknown length unit {unit}", "reader_unknown_length_unit", {"unit": unit[:_MAX_UNIT_DISPLAY]}
        if number is None:
            return key, None, "not a number", "reader_not_a_number", {}
        return key, number * factor, None, "", {}
    if column.field == "pressure":
        factor = _PRESSURE_UNITS.get(column.unit or "")
        if factor is None:
            return "pressure_pa", None, "state the pressure unit in the header (for example pressure_bar)", "reader_missing_pressure_unit", {}
        if number is None:
            return "pressure_pa", None, "not a number", "reader_not_a_number", {}
        return "pressure_pa", number * factor, None, "", {}
    if column.field == "temperature":
        unit = column.unit or "c"
        if unit not in {"c", "degc", "k"}:
            return "temperature_c", None, f"unknown temperature unit {unit}", "reader_unknown_temperature_unit", {"unit": unit[:_MAX_UNIT_DISPLAY]}
        value_c = None if number is None else (number - 273.15 if unit == "k" else number)
        if number is None:
            return "temperature_c", None, "not a number", "reader_not_a_number", {}
        return "temperature_c", value_c, None, "", {}
    if column.field == "mass_flow_kg_s":
        if column.unit not in (None, "kg_s"):
            return "mass_flow_kg_s", None, f"unknown mass-flow unit {column.unit}; state the flow in kg/s", "reader_unknown_mass_flow_unit", {"unit": str(column.unit)[:_MAX_UNIT_DISPLAY]}
        if number is None:
            return "mass_flow_kg_s", number, "not a number", "reader_not_a_number", {}
        return "mass_flow_kg_s", number, None, "", {}
    if number is None:
        return column.field, number, "not a number", "reader_not_a_number", {}
    return column.field, number, None, "", {}


def _check_xml(data: bytes, name: str) -> bytes:
    """Refuse DOCTYPE and entity declarations in any encoding before the real parse."""
    if len(data) > _MAX_PART_BYTES:
        raise PipeTableError(f"{name} is too large")

    def refuse(*_args: object) -> None:
        raise PipeTableError(f"{name} contains a DOCTYPE or entity declaration")

    scanner = expat.ParserCreate()
    scanner.StartDoctypeDeclHandler = refuse
    scanner.EntityDeclHandler = refuse
    try:
        scanner.Parse(data, True)
    except expat.ExpatError as exc:
        raise PipeTableError(f"{name} is not valid XML") from exc
    return data


def _capped_part(archive: zipfile.ZipFile, name: str) -> bytes:
    """Read a small workbook part, refusing oversize parts before the parse.

    The declared size is checked first, so a part that claims 150 MB is never
    decompressed; ZipFile truncates a lying size and the CRC check catches it.
    """
    if archive.getinfo(name).file_size > MAX_WORKBOOK_BYTES:
        raise PipeTableError(f"{name} is over the 1 MiB part limit")
    data = archive.read(name)
    if len(data) > MAX_WORKBOOK_BYTES:
        raise PipeTableError(f"{name} is over the 1 MiB part limit")
    return _check_xml(data, name)


def _refuse_doctype_stream(stream: object, name: str) -> None:
    """Refuse DOCTYPE and entity declarations in a part read as a stream.

    A second pass parses the part for real; this pass only runs the expat
    scanner, so a huge part is never held in memory to be checked.
    """
    def refuse(*_args: object) -> None:
        raise PipeTableError(f"{name} contains a DOCTYPE or entity declaration")

    scanner = expat.ParserCreate()
    scanner.StartDoctypeDeclHandler = refuse
    scanner.EntityDeclHandler = refuse
    read = getattr(stream, "read")
    try:
        while True:
            chunk = read(_CHUNK_BYTES)
            if not chunk:
                break
            scanner.Parse(chunk, False)
        scanner.Parse(b"", True)
    except expat.ExpatError as exc:
        raise PipeTableError(f"{name} is not valid XML") from exc


def _limited_stream(archive: zipfile.ZipFile, name: str) -> object:
    """Open a streamed part, refusing it when its uncompressed size is absurd."""
    if archive.getinfo(name).file_size > _MAX_PART_BYTES:
        raise PipeTableError(f"{name} is too large")
    return archive.open(name)


def _stream_shared_strings(archive: zipfile.ZipFile, name: str) -> list[str]:
    """Read the shared string table without holding its XML in memory.

    Only the strict data path is read: `sst > si`, `si` text holders, `r`
    properties and `t` text (see `_DATA_CHILDREN`). Anything else under a
    data parent is refused at its start event. Anything outside the data
    path is an opaque subtree: elements are counted and depth-capped, each
    is cleared or detached at close, and nothing inside is ever read — even
    a fake `si` nested deep. A top-level `si` is anchored by `parent is
    root`; anything else tagged `si` never opens. Below a top-level `si`,
    non-kept elements are emptied with `elem.clear()`; the finished `si`
    itself is dropped with `del parent[-1]`, which is safe because values
    are read from `elem`, `stack` and `keep`, never from the parent's
    child list. Detachment uses only `elem.clear()` and `del parent[-1]`.
    """
    with _limited_stream(archive, name) as stream:
        _refuse_doctype_stream(stream, name)
    shared: list[str] = []
    total = 0
    pending = 0
    si_tag = f"{{{_NS['m']}}}si"
    sst_tag = f"{{{_NS['m']}}}sst"
    text_tag = f"{{{_NS['m']}}}t"
    run_tag = f"{{{_NS['m']}}}r"
    extlst_tag = _EXTLST_TAG
    # The `t` text the `si` keeps stays attached until the `si` is read.
    keep = {text_tag, run_tag}
    with _limited_stream(archive, name) as stream:
        context = ElementTree.iterparse(stream, events=("start", "end"))
        _event, root = next(context)
        if root.tag != sst_tag:
            local = root.tag.split("}", 1)[-1]
            raise PipeTableError(f"the shared strings part starts with {local}, not sst")
        stack = [root]
        # Per-element roles: "D" data or structural, "E" opaque extLst region.
        ox = ["D"]
        odepth = 0
        ocount = 0
        for event, elem in context:
            if event == "start":
                stack.append(elem)
                parent = stack[-2]
                parent_ox = ox[-1]
                if parent_ox != "D":
                    ox.append(parent_ox)
                    odepth += 1
                    if odepth > _MAX_OPAQUE_DEPTH:
                        raise PipeTableError(
                            f"element nested deeper than {_MAX_OPAQUE_DEPTH} levels "
                            "inside an opaque part")
                    if parent_ox == "E":
                        ocount += 1
                        if ocount > _MAX_OPAQUE_ELEMENTS:
                            raise PipeTableError(
                                f"more than {_MAX_OPAQUE_ELEMENTS} elements "
                                "inside one opaque part")
                elif elem.tag == extlst_tag and parent is root:
                    ox.append("E")
                    if odepth == 0:
                        ocount = 0
                    odepth += 1
                    ocount += 1
                    if odepth > _MAX_OPAQUE_DEPTH:
                        raise PipeTableError(
                            f"element nested deeper than {_MAX_OPAQUE_DEPTH} levels "
                            "inside an opaque part")
                    if ocount > _MAX_OPAQUE_ELEMENTS:
                        raise PipeTableError(
                            f"more than {_MAX_OPAQUE_ELEMENTS} elements "
                            "inside one opaque part")
                else:
                    ox.append("D")
                    if elem.tag == si_tag and parent is root:
                        pending = 0
                        continue
                    allowed = _DATA_CHILD_TAGS.get(parent.tag)
                    if allowed is None or elem.tag not in allowed:
                        _refuse_child(parent.tag, elem.tag)
                    pending += 1
                    if pending > _MAX_SUBTREE_ELEMENTS:
                        raise PipeTableError(
                            f"a shared string holds more than {_MAX_SUBTREE_ELEMENTS} elements")
                continue
            is_opaque = ox.pop()
            if is_opaque == "E":
                odepth -= 1
            parent = stack[-2] if len(stack) > 1 else None
            stack.pop()
            if elem.tag == si_tag and parent is root:
                text = _run_text(elem, text_tag, run_tag)
                shared.append(text)
                total += len(text)
                if len(shared) > MAX_SHARED_STRINGS:
                    raise PipeTableError(f"{name} holds more than {MAX_SHARED_STRINGS} shared strings")
                if len(text) > MAX_SHARED_STRING_CHARS:
                    raise PipeTableError(
                        f"a shared string is longer than {MAX_SHARED_STRING_CHARS} characters")
                if total > MAX_SHARED_STRING_TOTAL:
                    raise PipeTableError(
                        f"{name} holds more than {MAX_SHARED_STRING_TOTAL} characters in total")
                del parent[-1]
            elif parent is None:
                pass
            elif is_opaque == "E":
                del parent[-1]
            elif elem.tag not in keep:
                elem.clear()
    return shared


def _stream_sheet_rows(
    archive: zipfile.ZipFile, name: str, shared: list[str],
) -> tuple[list[list[object]], set[tuple[int, int]]]:
    """Read the sheet row by row, with the same values the DOM parse gave.

    Only the strict data path is read: `worksheet > sheetData > row > c >
    {v, f, is}` (see `_DATA_CHILDREN`). Anything else under a data parent
    is refused at its start event. Anything outside the data path is an
    opaque subtree: worksheet siblings of `sheetData` in any namespace and
    `extLst` regions anywhere are depth-capped, cleared or detached at
    close, and never read — even a fake `sheetData > row` smuggled inside
    an `ext`. Only `extLst` regions are additionally counted, against
    per-region caps. A top-level row is anchored by stack depth 2 under
    `worksheet > sheetData`; anything else tagged `row` never opens a
    data row. Below a top-level row, non-kept elements are emptied with
    `elem.clear()`; the finished row itself is dropped with `del
    parent[-1]`, which is safe because values are read from `elem`,
    `stack` and `keep`, never from the parent's child list. Detachment
    uses only `elem.clear()` and `del parent[-1]`.
    """
    with _limited_stream(archive, name) as stream:
        _refuse_doctype_stream(stream, name)
    rows: list[list[object]] = []
    missing: set[tuple[int, int]] = set()
    row_tag = f"{{{_NS['m']}}}row"
    cell_tag = f"{{{_NS['m']}}}c"
    value_tag = f"{{{_NS['m']}}}v"
    formula_tag = f"{{{_NS['m']}}}f"
    text_tag = f"{{{_NS['m']}}}t"
    sheetdata_tag = f"{{{_NS['m']}}}sheetData"
    worksheet_tag = f"{{{_NS['m']}}}worksheet"
    run_tag = f"{{{_NS['m']}}}r"
    is_tag = f"{{{_NS['m']}}}is"
    extlst_tag = _EXTLST_TAG
    # Cells and the wrappers holding their text stay until the row is read.
    keep = {
        cell_tag, value_tag, formula_tag, text_tag,
        f"{{{_NS['m']}}}is", f"{{{_NS['m']}}}r",
    }
    with _limited_stream(archive, name) as stream:
        context = ElementTree.iterparse(stream, events=("start", "end"))
        _event, root = next(context)
        if root.tag != worksheet_tag:
            local = root.tag.split("}", 1)[-1]
            raise PipeTableError(f"the sheet part starts with {local}, not worksheet")
        stack = [root]
        # Per-element roles: "D" data or structural, "C" opaque container,
        # "E" opaque extLst region.
        ox = ["D"]
        open_rows = 0
        cells = 0
        pending = 0
        odepth = 0
        ocount = 0
        ocap = _MAX_OPAQUE_ELEMENTS
        edata_depth = 0
        seen_sheetdata = False
        for event, elem in context:
            if event == "start":
                stack.append(elem)
                parent = stack[-2]
                parent_ox = ox[-1]
                if parent_ox != "D":
                    ox.append(parent_ox)
                    odepth += 1
                    if odepth > _MAX_OPAQUE_DEPTH:
                        raise PipeTableError(
                            f"element nested deeper than {_MAX_OPAQUE_DEPTH} levels "
                            "inside an opaque part")
                    if parent_ox == "E":
                        ocount += 1
                        if ocount > ocap:
                            raise PipeTableError(
                                f"more than {ocap} elements "
                                "inside one opaque part")
                    if edata_depth:
                        pending += 1
                        if pending > _MAX_SUBTREE_ELEMENTS:
                            raise PipeTableError(
                                f"a table row holds more than {_MAX_SUBTREE_ELEMENTS} elements")
                elif elem.tag == extlst_tag and parent.tag in (
                    row_tag, cell_tag, sheetdata_tag, worksheet_tag,
                ):
                    ox.append("E")
                    if parent.tag in (row_tag, cell_tag):
                        edata_depth += 1
                    if parent.tag == sheetdata_tag:
                        ocap = _MAX_SHEETDATA_EXT_ELEMENTS
                    else:
                        ocap = _MAX_OPAQUE_ELEMENTS
                    ocount = 0
                    odepth += 1
                    ocount += 1
                    if odepth > _MAX_OPAQUE_DEPTH:
                        raise PipeTableError(
                            f"element nested deeper than {_MAX_OPAQUE_DEPTH} levels "
                            "inside an opaque part")
                    if ocount > ocap:
                        raise PipeTableError(
                            f"more than {ocap} elements "
                            "inside one opaque part")
                    if edata_depth:
                        pending += 1
                        if pending > _MAX_SUBTREE_ELEMENTS:
                            raise PipeTableError(
                                f"a table row holds more than {_MAX_SUBTREE_ELEMENTS} elements")
                elif parent.tag == worksheet_tag and elem.tag == sheetdata_tag:
                    if seen_sheetdata:
                        raise PipeTableError(
                            "the sheet part has a second sheetData element")
                    seen_sheetdata = True
                    ox.append("D")
                elif parent.tag == worksheet_tag:
                    ox.append("C")
                    odepth += 1
                    if odepth > _MAX_OPAQUE_DEPTH:
                        raise PipeTableError(
                            f"element nested deeper than {_MAX_OPAQUE_DEPTH} levels "
                            "inside an opaque part")
                else:
                    ox.append("D")
                    if elem.tag == row_tag and parent.tag == sheetdata_tag:
                        open_rows += 1
                        cells = 0
                        pending = 0
                        continue
                    allowed = _DATA_CHILD_TAGS.get(parent.tag)
                    if allowed is None or elem.tag not in allowed:
                        _refuse_child(parent.tag, elem.tag)
                    pending += 1
                    if pending > _MAX_SUBTREE_ELEMENTS:
                        raise PipeTableError(
                            f"a table row holds more than {_MAX_SUBTREE_ELEMENTS} elements")
                    if elem.tag == cell_tag:
                        cells += 1
                        if cells > _MAX_ROW_COLUMNS:
                            ref = elem.get("r", "")
                            raise PipeTableError(
                                f"cell {ref} is beyond the 256-column limit; "
                                "keep the table within 256 columns"
                            )
                continue
            is_opaque = ox.pop()
            if is_opaque in ("C", "E"):
                odepth -= 1
            parent = stack[-2] if len(stack) > 1 else None
            stack.pop()
            if elem.tag == row_tag and is_opaque == "D" and parent is not None and parent.tag == sheetdata_tag:
                open_rows -= 1
            if elem.tag == row_tag and parent is not None and parent.tag == sheetdata_tag and len(stack) == 2 and stack[0] is root and stack[1] is parent:
                # Excel leaves empty rows out; pad them so row numbers match the sheet.
                number = elem.get("r", "")
                if number.isdigit() and len(rows) < int(number) - 1 <= MAX_ROWS + _HEADER_SCAN_ROWS:
                    rows.extend([] for _ in range(int(number) - 1 - len(rows)))
                values: list[object] = []
                for cell in elem:
                    if cell.tag != cell_tag:
                        continue
                    ref = cell.get("r", "")
                    index = _column_index(ref, len(values))
                    if index >= _MAX_ROW_COLUMNS:
                        raise PipeTableError(
                            f"cell {ref} is beyond the 256-column limit; "
                            "keep the table within 256 columns"
                        )
                    while len(values) < index:
                        values.append("")
                    kind = cell.get("t")
                    cached = cell.find(value_tag)
                    if kind == "inlineStr":
                        value: object = _run_text(
                            cell.find(is_tag), text_tag, run_tag)
                    elif cached is None:
                        value = ""
                        if cell.find(formula_tag) is not None:
                            missing.add((len(rows), index))
                    elif kind == "s":
                        position = int(cached.text or "0")
                        value = shared[position] if 0 <= position < len(shared) else ""
                    elif kind in {"str", "b", "e"}:
                        value = cached.text or ""
                    else:
                        value = _number(cached.text or "") if cached.text else ""
                    values.append(value)
                rows.append(values)
                if len(rows) > MAX_ROWS + _HEADER_SCAN_ROWS:
                    raise PipeTableError(f"the table has more than {MAX_ROWS} rows")
                del parent[-1]
            elif parent is None:
                pass
            elif is_opaque == "E" and elem.tag == extlst_tag and ox[-1] != "E":
                if parent is not None and parent.tag in (row_tag, cell_tag):
                    edata_depth -= 1
                if parent is root or (
                    parent is not None and parent.tag == sheetdata_tag
                ):
                    del parent[-1]
                elif parent is not None:
                    elem.clear()
            elif is_opaque in ("C", "E"):
                del parent[-1]
            elif elem.tag not in keep and open_rows:
                elem.clear()
    return rows, missing


def _xlsx_rows(path: Path, sheet: str | None) -> tuple[list[list[object]], set[tuple[int, int]], str]:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise PipeTableError("the .xlsx file is not a valid workbook") from exc
    with archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_ENTRIES:
            raise PipeTableError(f"the workbook has more than {MAX_ZIP_ENTRIES} entries")
        if sum(member.file_size for member in members) > MAX_UNZIPPED_BYTES:
            raise PipeTableError("the workbook is too large uncompressed")
        names = {member.filename for member in members}

        workbook = ElementTree.fromstring(_capped_part(archive, "xl/workbook.xml"))
        rels = ElementTree.fromstring(_capped_part(archive, "xl/_rels/workbook.xml.rels"))
        targets = {item.get("Id"): item.get("Target", "") for item in rels}
        sheets = [(item.get("name", ""), item.get(_REL_NS)) for item in workbook.findall("m:sheets/m:sheet", _NS)]
        if not sheets:
            raise PipeTableError("the workbook has no sheets")
        chosen = next((item for item in sheets if item[0] == sheet), None) if sheet else sheets[0]
        if chosen is None:
            raise PipeTableError(f"the workbook has no sheet named {sheet}")
        target = targets.get(chosen[1], "")
        sheet_path = str(PurePosixPath("xl") / target.lstrip("/").removeprefix("xl/"))
        if ".." in PurePosixPath(sheet_path).parts or sheet_path not in names:
            raise PipeTableError("the sheet part is missing")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            shared = _stream_shared_strings(archive, "xl/sharedStrings.xml")
        rows, missing = _stream_sheet_rows(archive, sheet_path, shared)
    return rows, missing, chosen[0]


def _column_index(reference: str, fallback: int) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if not letters:
        return fallback
    index = 0
    for letter in letters.group(0):
        index = index * 26 + (ord(letter) - 64)
    if index > _MAX_COLUMNS:
        raise PipeTableError(f"cell {reference} is beyond the last spreadsheet column")
    return index - 1


def _csv_rows(path: Path) -> list[list[object]]:
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PipeTableError("save the CSV as UTF-8 (Excel: CSV UTF-8) and import it again") from exc
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)]


def read_table(
    path: Path | str,
    *,
    column_map: Mapping[str, str] | None = None,
    sheet: str | None = None,
    unit_length: str | None = None,
) -> PipeTable:
    """Read rows of a pipe table as template fields in SI units, plus row issues."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise PipeTableError("a pipe table must be a .csv or .xlsx file")
    if source.stat().st_size > MAX_FILE_BYTES:
        raise PipeTableError("the table file is larger than 20 MiB")
    with source.open("rb") as handle:
        magic = handle.read(16)
    is_workbook = suffix in (".xlsx", ".xlsm")
    if magic[:8] == _OLE2_SIGNATURE or (
        is_workbook and b"DRM" in magic and not magic.startswith(_ZIP_MAGIC)
    ):
        raise PipeTableError(
            "the file is protected (encrypted or DRM); save an unprotected copy",
            code="table_encrypted")
    if unit_length is not None and unit_length not in _LENGTH_UNITS:
        raise PipeTableError("unit_length must be m, cm or mm")
    missing: set[tuple[int, int]] = set()
    sheet_name = None
    try:
        if suffix == ".csv":
            raw = _csv_rows(source)
        else:
            raw, missing, sheet_name = _xlsx_rows(source, sheet)
    except PipeTableError:
        raise
    # RuntimeError covers encrypted members and unsupported compression verbs
    # (NotImplementedError subclasses RuntimeError); zlib.error and EOFError
    # are the corrupt- and truncated-stream counterparts.
    except (OSError, KeyError, ValueError, csv.Error, zipfile.BadZipFile, ElementTree.ParseError,
            RuntimeError, zlib.error, EOFError) as exc:
        raise PipeTableError(f"the table could not be read ({type(exc).__name__})") from exc
    header_index, columns = _header(raw, column_map)
    data = [
        (index, row) for index, row in enumerate(raw[header_index + 1:], start=header_index + 1)
        if any(str(value).strip() for value in row)
    ]
    if len(data) > MAX_ROWS:
        raise PipeTableError(f"the table has more than {MAX_ROWS} rows")
    rows: list[dict[str, object]] = []
    issues: list[TableIssue] = []
    for index, row in data:
        record: dict[str, object] = {}
        for position, column in columns.items():
            value = row[position] if position < len(row) else ""
            key = column.field if column.field in _TEXT_FIELDS else _converted(column, 0, unit_length)[0]
            if (index, position) in missing:
                issues.append(TableIssue(index + 1, key, "formula cell without a cached value; save the file in Excel first", "reader_formula_no_cached", {}))
                continue
            if str(value).strip() == "":
                continue
            key, converted, problem, code, params = _converted(column, value, unit_length)
            if problem is not None:
                issues.append(TableIssue(index + 1, key, problem, code, params))
                continue
            record[key] = converted
        rows.append(record)
    ignored = tuple(
        str(raw[header_index][position]).strip()
        for position in range(len(raw[header_index]))
        if position not in columns and str(raw[header_index][position]).strip()
    )
    return PipeTable(
        tuple(rows), tuple(issues), header_index + 1, ignored, sheet_name,
        tuple(index + 1 for index, _ in data),
    )


def _header(raw: list[list[object]], column_map: Mapping[str, str] | None) -> tuple[int, dict[int, _Column]]:
    for index, row in enumerate(raw[:_HEADER_SCAN_ROWS]):
        columns: dict[int, _Column] = {}
        seen: set[str] = set()
        for position, cell in enumerate(row):
            column = _column(str(cell), column_map)
            if column is not None and column.field not in seen:
                columns[position] = column
                seen.add(column.field)
        if len(columns) >= _MIN_HEADER_MATCHES:
            return index, columns
    raise PipeTableError(
        "no header row found; use the template column names or pass a column map"
    )
