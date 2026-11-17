"""Pipe tables from CSV and xlsx with the stdlib only."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from olga_companion.pipe_table import PipeTableError, read_table

TEMPLATE = (
    "flowpath,pipe,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m\n"
    "FP_A,P1,IN,J1,10,0,0.05,0.00005\n"
    "FP_A,P2,IN,J1,4,-1,0.05,0.00005\n"
)


def _xlsx(path: Path, rows: list[list[object]], *, shared: bool = True, extra: dict[str, str] | None = None) -> Path:
    strings: list[str] = []

    def cell(ref: str, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"><v>{value}</v></c>'
        if isinstance(value, tuple):  # (formula, cached)
            formula, cached = value
            cached_xml = "" if cached is None else f"<v>{cached}</v>"
            return f'<c r="{ref}"><f>{formula}</f>{cached_xml}</c>'
        if not shared:
            return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
        strings.append(str(value))
        return f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>'

    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    body = "".join(
        f'<row r="{r}">' + "".join(cell(f"{letters[c]}{r}", v) for c, v in enumerate(row)) + "</row>"
        for r, row in enumerate(rows, start=1)
    )
    sheet = f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{body}</sheetData></worksheet>'
    sst = (
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{text}</t></si>" for text in strings) + "</sst>"
    )
    workbook = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Pipes" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        if shared:
            archive.writestr("xl/sharedStrings.xml", sst)
        for name, text in (extra or {}).items():
            archive.writestr(name, text)
    return path


HEADER = ["flowpath", "pipe", "from_node", "to_node", "length_m", "elevation_m", "inner_diameter_m", "roughness_m"]


def test_template_csv_reads_numbers(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_text(TEMPLATE, encoding="utf-8")

    table = read_table(path)

    assert table.rows[0]["length_m"] == 10.0
    assert table.rows[1]["elevation_m"] == -1.0
    assert table.rows[0]["flowpath"] == "FP_A"
    assert table.issues == ()


def test_semicolon_csv_with_bom(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_bytes(("﻿" + TEMPLATE.replace(",", ";")).encode("utf-8"))
    assert read_table(path).rows[1]["length_m"] == 4.0


def test_xlsx_with_shared_strings_and_a_late_header(tmp_path: Path) -> None:
    rows = [["Pipe data"], [], ["note"], HEADER, ["FP_A", "P1", "IN", "J1", 10, 0, 0.05, 5e-05]]
    table = read_table(_xlsx(tmp_path / "pipes.xlsx", rows))
    assert table.rows == ({
        "flowpath": "FP_A", "pipe": "P1", "from_node": "IN", "to_node": "J1",
        "length_m": 10.0, "elevation_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05,
    },)
    assert table.header_row == 4


def test_xlsx_inline_strings(tmp_path: Path) -> None:
    rows = [HEADER, ["FP_A", "P1", "IN", "J1", 10, 0, 0.05, 5e-05]]
    assert read_table(_xlsx(tmp_path / "pipes.xlsx", rows, shared=False)).rows[0]["pipe"] == "P1"


def test_synonyms_and_mm_suffix_convert_to_metres(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_text(
        "Line,Pipe No.,From,To,Length (mm),Height (mm),Inner Diameter (mm),Roughness (mm)\n"
        "FP_A,Pipe 01,IN,J1,179,0,53.5,0.05\n",
        encoding="utf-8",
    )
    row = read_table(path).rows[0]
    assert row["length_m"] == pytest.approx(0.179)
    assert row["inner_diameter_m"] == pytest.approx(0.0535)
    assert row["roughness_m"] == pytest.approx(5e-05)
    assert row["pipe"] == "Pipe 01"


def test_explicit_column_map_and_unit(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_text("a,b,c,d,e,f,g,h\nFP_A,P1,IN,J1,179,0,53.5,0.05\n", encoding="utf-8")
    column_map = dict(zip("abcdefgh", ["flowpath", "pipe", "from_node", "to_node", "length", "elevation", "inner_diameter", "roughness"]))
    row = read_table(path, column_map=column_map, unit_length="mm").rows[0]
    assert row["length_m"] == pytest.approx(0.179)


def test_formula_without_cached_value_is_reported(tmp_path: Path) -> None:
    rows = [HEADER, ["FP_A", "P1", "IN", "J1", ("B2*2", None), 0, 0.05, 5e-05]]
    table = read_table(_xlsx(tmp_path / "pipes.xlsx", rows))
    assert table.issues[0].column == "length_m"
    assert "cached" in table.issues[0].reason


def test_unknown_columns_are_noted(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_text(TEMPLATE.replace("roughness_m\n", "roughness_m,colour\n").replace("0.00005\n", "0.00005,red\n"), encoding="utf-8")
    table = read_table(path)
    assert table.ignored_columns == ("colour",)


@pytest.mark.parametrize("payload", ["<!DOCTYPE x>", '<!ENTITY a "b">'])
def test_xml_doctype_and_entities_are_refused(tmp_path: Path, payload: str) -> None:
    path = _xlsx(tmp_path / "pipes.xlsx", [HEADER])
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", payload + "<worksheet/>")
    with pytest.raises(PipeTableError, match="DOCTYPE|entity|valid XML"):
        read_table(path)


def test_a_utf16_doctype_is_refused_too(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "pipes.xlsx", [HEADER])
    payload = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE w [<!ENTITY a "b">]><worksheet/>'
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", payload.encode("utf-16"))
    with pytest.raises(PipeTableError, match="DOCTYPE"):
        read_table(path)


def test_a_cell_beyond_the_last_column_is_refused(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "pipes.xlsx", [HEADER])
    sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             '<row r="1"><c r="ZZZZZZZZZ1"><v>1</v></c></row></sheetData></worksheet>')
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    with pytest.raises(PipeTableError, match="last spreadsheet column"):
        read_table(path)


def test_xlsx_row_numbers_follow_the_sheet_when_rows_are_skipped(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "pipes.xlsx", [HEADER])
    cells = "".join(f'<c r="{chr(65 + i)}{{r}}" t="inlineStr"><is><t>{name}</t></is></c>' for i, name in enumerate(HEADER))
    data = "".join(f'<c r="{chr(65 + i)}7"><v>{v}</v></c>' for i, v in enumerate([0, 0, 0, 0, 10, 0, 0.05, 5e-05]))
    sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             f'<row r="3">{cells.format(r=3)}</row><row r="7">{data}</row></sheetData></worksheet>')
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    table = read_table(path)
    assert table.header_row == 3 and table.lines == (7,)


def test_a_non_utf8_csv_names_the_fix(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_bytes((TEMPLATE + "FP_가,P3,IN,J1,1,0,0.05,0.00005\n").encode("cp949"))
    with pytest.raises(PipeTableError, match="UTF-8"):
        read_table(path)


def test_a_thousands_comma_is_not_read_as_a_decimal(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_text(TEMPLATE.replace("FP_A,P1,IN,J1,10,", 'FP_A,P1,IN,J1,"1,500",'), encoding="utf-8")
    table = read_table(path)
    assert "length_m" not in table.rows[0] and table.issues[0].column == "length_m"


def test_id_and_schedule_columns_are_not_guessed(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_text(TEMPLATE.replace("roughness_m\n", "roughness_m,ID,Schedule\n").replace("0.00005\n", "0.00005,7,40\n"), encoding="utf-8")
    table = read_table(path)
    assert table.rows[0]["inner_diameter_m"] == 0.05 and "valve_schedule" not in table.rows[0]
    assert table.ignored_columns == ("ID", "Schedule")


def test_too_many_zip_entries_are_refused(tmp_path: Path) -> None:
    extra = {f"junk/{index}.xml": "<a/>" for index in range(2001)}
    with pytest.raises(PipeTableError, match="entries"):
        read_table(_xlsx(tmp_path / "pipes.xlsx", [HEADER], extra=extra))


def test_oversize_and_row_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import olga_companion.pipe_table as module

    path = tmp_path / "pipes.csv"
    path.write_text(TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(module, "MAX_FILE_BYTES", 10)
    with pytest.raises(PipeTableError, match="larger"):
        read_table(path)
    monkeypatch.setattr(module, "MAX_FILE_BYTES", 20 * 1024 * 1024)
    monkeypatch.setattr(module, "MAX_ROWS", 1)
    with pytest.raises(PipeTableError, match="rows"):
        read_table(path)


def test_uncompressed_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import olga_companion.pipe_table as module

    monkeypatch.setattr(module, "MAX_UNZIPPED_BYTES", 100)
    with pytest.raises(PipeTableError, match="uncompressed"):
        read_table(_xlsx(tmp_path / "pipes.xlsx", [HEADER, ["x"] * 8]))


def test_missing_header_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(PipeTableError, match="header"):
        read_table(path)


def _workbook_with_sheet(path: Path, sheet: str) -> Path:
    workbook = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Pipes" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


def _sheet(rows: list[str]) -> str:
    body = "".join(f"<row r=\"{number}\">{cells}</row>" for number, cells in enumerate(rows, start=1))
    return (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{body}</sheetData></worksheet>"
    )


def _inline(cells: list[str]) -> str:
    """Inline-string cells with a `{r}` placeholder for the sheet row number."""
    return "".join(
        f'<c r="{chr(65 + position)}{{r}}" t="inlineStr"><is><t>{text}</t></is></c>'
        for position, text in enumerate(cells)
    )


def test_a_far_column_cell_is_refused_naming_the_cell(tmp_path: Path) -> None:
    # One XFD cell per row: padding every row out to column 16384 would need
    # gigabytes for a small file, so the parse must refuse the cell instead.
    header = _inline(HEADER).format(r=1)
    body = [header]
    for number in range(2, 202):
        body.append(
            f'<c r="A{number}" t="inlineStr"><is><t>FP_A</t></is></c>'
            f'<c r="XFD{number}"><v>1</v></c>'
        )
    path = _workbook_with_sheet(tmp_path / "pipes.xlsx", _sheet(body))
    with pytest.raises(PipeTableError, match="XFD2"):
        read_table(path)


def test_rows_past_the_cap_are_never_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The poison row past the cap must never be reached: the parse stops with
    # the row-cap refusal instead of tripping over the far cell below it.
    import olga_companion.pipe_table as module

    monkeypatch.setattr(module, "MAX_ROWS", 3)
    body = [_inline(HEADER).format(r=1)]
    for number in range(2, 62):
        body.append(f'<c r="A{number}" t="inlineStr"><is><t>FP_A</t></is></c>')
    body.append(f'<c r="A62" t="inlineStr"><is><t>FP_A</t></is></c><c r="ZZZZZZZZZ62"><v>1</v></c>')
    path = _workbook_with_sheet(tmp_path / "pipes.xlsx", _sheet(body))
    with pytest.raises(PipeTableError, match="more than 3 rows"):
        read_table(path)


def _patch_sheet_entry(path: Path, *, flag_or: int = 0, method: int | None = None) -> None:
    """Flip flag bits or the method of the sheet entry in the central directory."""
    import struct

    name = b"xl/worksheets/sheet1.xml"
    raw = bytearray(path.read_bytes())
    position = 0
    while True:
        position = raw.find(b"PK\x01\x02", position)
        assert position >= 0, "sheet entry not found"
        name_length = struct.unpack("<H", raw[position + 28:position + 30])[0]
        if raw[position + 46:position + 46 + name_length] == name:
            if method is not None:
                raw[position + 10:position + 12] = struct.pack("<H", method)
            if flag_or:
                flags = struct.unpack("<H", raw[position + 8:position + 10])[0]
                raw[position + 8:position + 10] = struct.pack("<H", flags | flag_or)
            path.write_bytes(bytes(raw))
            return
        position += 1


def _valid_sheet_writes(path: Path) -> None:
    body = [_inline(HEADER).format(r=1), _inline(["FP_A", "P1", "IN", "J1", "10", "0", "0.05", "0.00005"]).format(r=2)]
    _workbook_with_sheet(path, _sheet(body))


def test_an_encrypted_member_is_a_readable_refusal(tmp_path: Path) -> None:
    path = tmp_path / "pipes.xlsx"
    _valid_sheet_writes(path)
    _patch_sheet_entry(path, flag_or=0x1)
    with pytest.raises(PipeTableError, match="could not be read"):
        read_table(path)


def test_an_unsupported_compression_member_is_a_readable_refusal(tmp_path: Path) -> None:
    path = tmp_path / "pipes.xlsx"
    _valid_sheet_writes(path)
    _patch_sheet_entry(path, method=96)
    with pytest.raises(PipeTableError, match="could not be read"):
        read_table(path)


def test_a_corrupt_deflate_member_is_a_readable_refusal(tmp_path: Path) -> None:
    import struct

    path = tmp_path / "pipes.xlsx"
    _valid_sheet_writes(path)
    with zipfile.ZipFile(path, "a", compresslevel=9) as archive:
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            _sheet([_inline(HEADER).format(r=1)]),
            compress_type=zipfile.ZIP_DEFLATED,
        )
    raw = bytearray(path.read_bytes())
    name = b"xl/worksheets/sheet1.xml"
    position = raw.rfind(name)
    local = raw.rfind(b"PK\x03\x04", 0, position)
    name_length = struct.unpack("<H", raw[local + 26:local + 28])[0]
    extra_length = struct.unpack("<H", raw[local + 28:local + 30])[0]
    start = local + 30 + name_length + extra_length
    size = struct.unpack("<I", raw[local + 18:local + 22])[0]
    raw[start:start + size] = b"\xff" * size
    path.write_bytes(bytes(raw))
    with pytest.raises(PipeTableError, match="could not be read"):
        read_table(path)


def test_a_dying_member_stream_is_a_readable_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A member whose stream dies mid-read (truncated storage, dying drive)
    # surfaces as EOFError; the table must still refuse readably. The reader
    # streams members through open, so the fault is injected there.
    path = tmp_path / "pipes.xlsx"
    _valid_sheet_writes(path)
    real_open = zipfile.ZipFile.open

    def _dying(self, name, mode="r", pwd=None):
        if name == "xl/worksheets/sheet1.xml":
            raise EOFError("unexpected end of stream")
        return real_open(self, name, mode, pwd)

    monkeypatch.setattr(zipfile.ZipFile, "open", _dying)
    with pytest.raises(PipeTableError, match="could not be read"):
        read_table(path)


def test_other_extensions_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "pipes.txt"
    path.write_text(TEMPLATE, encoding="utf-8")
    with pytest.raises(PipeTableError, match="csv"):
        read_table(path)


_SST_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _xlsx_raw(
    path: Path, sheet: str, sst: str | None = None, *, workbook_pad: int = 0,
) -> Path:
    workbook = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Pipes" sheetId="1" r:id="rId1"/></sheets>'
        + ("<!--" + "x" * workbook_pad + "-->" if workbook_pad else "")
        + "</workbook>"
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        if sst is not None:
            archive.writestr("xl/sharedStrings.xml", sst)
    return path


def _sst(items: list[str]) -> str:
    return (
        f'<sst xmlns="{_SST_NS}">'
        + "".join(f"<si><t>{text}</t></si>" for text in items)
        + "</sst>"
    )


def _shared_cell(ref: str, index: int) -> str:
    return f'<c r="{ref}" t="s"><v>{index}</v></c>'


def test_shared_strings_over_the_entry_cap_are_refused(tmp_path: Path) -> None:
    import olga_companion.pipe_table as module

    sheet = _sheet([_inline(HEADER).format(r=1)])
    path = _xlsx_raw(
        tmp_path / "pipes.xlsx", sheet,
        _sst(["x"] * (module.MAX_SHARED_STRINGS + 1)),
    )
    with pytest.raises(PipeTableError, match="200000"):
        read_table(path)


def test_a_shared_string_over_the_character_cap_is_refused(tmp_path: Path) -> None:
    import olga_companion.pipe_table as module

    sheet = _sheet([_inline(HEADER).format(r=1)])
    path = _xlsx_raw(
        tmp_path / "pipes.xlsx", sheet,
        _sst(["y" * (module.MAX_SHARED_STRING_CHARS + 1)]),
    )
    with pytest.raises(PipeTableError, match="32767"):
        read_table(path)


def test_shared_strings_over_the_total_character_cap_are_refused(tmp_path: Path) -> None:
    import olga_companion.pipe_table as module

    per_string = 30_000
    count = module.MAX_SHARED_STRING_TOTAL // per_string + 1
    sheet = _sheet([_inline(HEADER).format(r=1)])
    path = _xlsx_raw(
        tmp_path / "pipes.xlsx", sheet,
        _sst(["z" * per_string] * count),
    )
    with pytest.raises(PipeTableError, match="20000000"):
        read_table(path)


def test_an_oversize_workbook_part_is_refused(tmp_path: Path) -> None:
    import olga_companion.pipe_table as module

    sheet = _sheet([_inline(HEADER).format(r=1)])
    path = _xlsx_raw(
        tmp_path / "pipes.xlsx", sheet, _sst([]), workbook_pad=module.MAX_WORKBOOK_BYTES + 1,
    )
    with pytest.raises(PipeTableError, match="1 MiB"):
        read_table(path)


def test_the_streamed_sheet_parses_identical_rows(tmp_path: Path) -> None:
    from olga_companion.pipe_table import TableIssue

    sst = _sst(["FP_A", "IN"])
    row = (
        _shared_cell("A3", 0)
        + '<c r="B3" t="inlineStr"><is><t>P1</t></is></c>'
        + _shared_cell("C3", 1)
        + '<c r="D3" t="inlineStr"><is><t>J1</t></is></c>'
        + '<c r="E3"><v>10</v></c>'
        + '<c r="F3"><f>SUM(1,-1)</f><v>0</v></c>'
        + '<c r="G3"><v>0.05</v></c>'
        + '<c r="H3"><f>NOW()</f></c>'
    )
    # The data row keeps its sheet row number, leaving row 2 out.
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{_inline(HEADER).format(r=1)}</row>"
        f"<row r=\"3\">{row}</row>"
        "</sheetData></worksheet>"
    )
    table = read_table(_xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst))

    assert table.rows == ({
        "flowpath": "FP_A", "pipe": "P1", "from_node": "IN", "to_node": "J1",
        "length_m": 10.0, "elevation_m": 0.0, "inner_diameter_m": 0.05,
    },)
    assert table.issues == (TableIssue(
        3, "roughness_m",
        "formula cell without a cached value; save the file in Excel first",
        "reader_formula_no_cached", {},
    ),)
    assert table.header_row == 1 and table.lines == (3,)


def test_a_doctype_in_shared_strings_is_refused(tmp_path: Path) -> None:
    sheet = _sheet([_inline(HEADER).format(r=1)])
    path = _xlsx_raw(
        tmp_path / "pipes.xlsx", sheet,
        "<!DOCTYPE x>" + _sst(["FP_A"]),
    )
    with pytest.raises(PipeTableError, match="DOCTYPE"):
        read_table(path)


def test_a_flood_of_non_matching_elements_is_refused(tmp_path: Path) -> None:
    import time

    # Junk is not an allowed child of sheetData: the first junk element
    # refuses at once, so no bound on retained rows is needed anymore.
    header = _inline(HEADER).format(r=1)
    data = "".join(
        f'<c r="{chr(65 + position)}2" t="inlineStr"><is><t>{text}</t></is></c>'
        for position, text in enumerate(["FP_A", "P1", "IN", "J1", "10", "0", "0.05", "0.00005"])
    )
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{header}</row>"
        f"<row r=\"2\">{data}</row>"
        + "<junk/>" * 200_000
        + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="which is not allowed here"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_20k_empty_rows_then_junk_are_refused(tmp_path: Path) -> None:
    import time

    # Junk is not an allowed child of sheetData, so the first junk element
    # refuses at once instead of scanning past the 20k retained rows.
    header = _inline(HEADER).format(r=1)
    rows = "".join(f"<row r=\"{number}\"/>" for number in range(2, 20002))
    junk = "<junk/>" * 500_000
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{header}</row>'
        + rows + junk + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="which is not allowed here"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_20k_filled_rows_stay_bounded(tmp_path: Path) -> None:
    import tracemalloc

    header = _inline(HEADER).format(r=1)
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{header}</row>'
        + "".join(
            f"<row r=\"{number}\">" + "".join(
                f'<c r="{chr(65 + position)}{number}" t="inlineStr"><is><t>{text}</t></is></c>'
                for position, text in enumerate(["FP_A", "P1", "IN", "J1", "10", "0", "0.05", "0.00005"])
            ) + "</row>"
            for number in range(2, 20002)
        )
        + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    tracemalloc.start()
    try:
        table = read_table(path)
    finally:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert len(table.rows) == 20000
    assert peak < 60 * 1024 * 1024


def test_merge_cells_descendants_stay_bounded(tmp_path: Path) -> None:
    import tracemalloc

    # mergeCells sits outside any row, so its children are detached as they
    # close instead of accumulating under the worksheet.
    header = _inline(HEADER).format(r=1)
    merge = "<mergeCells>" + "".join(
        f'<mergeCell ref="A{number}:B{number}"/>' for number in range(1, 200001)
    ) + "</mergeCells>"
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{header}</row></sheetData>'
        + merge + "</worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    tracemalloc.start()
    try:
        table = read_table(path)
    finally:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert len(table.rows) == 0
    assert peak < 5 * 1024 * 1024


def test_junk_children_inside_a_row_are_refused(tmp_path: Path) -> None:
    import time

    # 200k non-cell children inside one row: row holds only cells, so the
    # first junk child refuses at once.
    header = _inline(HEADER).format(r=1)
    data = _inline(["FP_A", "P1", "IN", "J1", "10", "0", "0.05", "0.00005"]).format(r=2)
    row = f"<row r=\"2\">{data}" + "<junk>abc</junk>" * 200_000 + "</row>"
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{header}</row>'
        + row + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="which is not allowed here"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_junk_children_inside_a_shared_string_are_refused(tmp_path: Path) -> None:
    import time

    # 200k same-namespace junk elements inside one si: an si holds only
    # text holders, so the first junk child refuses at once.
    si = "<si><t>x</t>" + "<junk/>" * 200_000 + "</si>"
    sst = f'<sst xmlns="{_SST_NS}">' + si + "</sst>"
    sheet = _sheet([_inline(HEADER).format(r=1)])
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst)
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="which is not allowed here"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_junk_children_inside_a_cell_are_refused(tmp_path: Path) -> None:
    import time

    # 200k non-value children inside one cell: a cell holds only v, f, is
    # and extLst, so the first junk child refuses at once.
    header = _inline(HEADER).format(r=1)
    cell = "<c r=\"A2\"><v>1</v>" + "<junk/>" * 200_000 + "</c>"
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{header}</row>'
        + f"<row r=\"2\">{cell}</row>" + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="which is not allowed here"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_a_nested_row_is_refused(tmp_path: Path) -> None:
    import time

    # A row holds only cells: a nested row refuses at once, so it never
    # reaches the 256-cell counter. The open_rows == 1 reset stays as
    # defense in depth.
    header = _inline(HEADER).format(r=1)
    outer = _inline(["FP_A", "P1", "IN", "J1", "10", "0", "0.05", "0.00005"]).format(r=2)
    nested = "<row r=\"3\"><c/></row>"
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{header}</row>'
        + f"<row r=\"2\">{outer}{nested}</row>" + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="which is not allowed here"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_a_keep_heavy_row_still_parses(tmp_path: Path) -> None:
    import time

    # 256 rich-text cells: every wrapper is a keep tag, so nothing is
    # detached and the element count stays near 1.5k, far under the cap.
    def rich(text: str) -> str:
        return (
            "<c t=\"inlineStr\"><is><r><rPr><sz val=\"11\"/></rPr>"
            f"<t>{text}</t></r></is></c>"
        )
    header = _inline(HEADER).format(r=1)
    data = "".join(
        rich(text) for text in ["FP_A", "P1", "IN", "J1", "10", "0", "0.05", "0.00005"]
    ) + rich("pad") * 248
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{header}</row>'
        + f"<row r=\"2\">{data}</row>" + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 5
    assert [row["flowpath"] for row in table.rows] == ["FP_A"]


def test_a_deep_row_nest_is_refused(tmp_path: Path) -> None:
    import time

    # A row holds only cells: the first nested row refuses at once, so the
    # 200k flood behind it is never built.
    header = _inline(HEADER).format(r=1)
    nest = "<row>" * 200_000 + "</row>" * 200_000
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{header}</row>'
        + f"<row r=\"2\">{nest}</row>" + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="which is not allowed here"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_a_nested_si_is_refused(tmp_path: Path) -> None:
    import time

    # Excel never writes an si inside an si: the first nested open refuses,
    # so the 200k flood behind it is never built.
    si = "<si><t>x</t>" + "<si/>" * 200_000 + "</si>"
    sst = f'<sst xmlns="{_SST_NS}">' + si + "</sst>"
    sheet = _sheet([_inline(HEADER).format(r=1)])
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst)
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="which is not allowed here"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_a_stray_wrapper_in_sst_is_refused(tmp_path: Path) -> None:
    import time

    # A stray si cannot open anymore: only sst children named si pass the
    # table, so the foreign wrapper refuses at once before any si opens.
    # (This replaces the BER6 stray-detach test; strays are refused now.)
    sst = (
        f'<sst xmlns="{_SST_NS}"><x>' + "<si/>" * 200_000 + "</x></sst>"
    )
    sheet = _sheet([_inline(HEADER).format(r=1)])
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst)
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="which is not allowed here"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_keep_then_junk_inside_a_run_is_refused(tmp_path: Path) -> None:
    import time

    # Valid text first, then junk: an r holds only rPr and t, so the first
    # junk child refuses at once.
    header = _inline(HEADER).format(r=1)
    cell = (
        '<c r="A2" t="inlineStr"><is><r><t>x</t>' + "<junk/>" * 1000 + "</r></is></c>"
    )
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{header}</row>'
        + f"<row r=\"2\">{cell}</row>" + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="which is not allowed here"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_a_fake_sst_nested_deep_is_refused(tmp_path: Path) -> None:
    import time

    # An sst element is only valid as the part root: the fake one refuses
    # at once, so its 50k inner si never open.
    si = "<si><t>x</t><r><t>a</t><sst>" + "<si/>" * 50_000 + "</sst></r></si>"
    sst = f'<sst xmlns="{_SST_NS}">' + si + "</sst>"
    sheet = _sheet([_inline(HEADER).format(r=1)])
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst)
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="which is not allowed here"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_a_fake_sheet_data_nested_deep_is_refused(tmp_path: Path) -> None:
    import tracemalloc

    # A sheetData element is only valid under the worksheet root. Each 90k
    # block of t stays under the element cap and the fake row between the
    # blocks resets it, so only the allowed-children rule refuses.
    block = "<t/>" * 90_000
    cell = (
        "<c><is><r><t>x</t><sheetData>" + block + "<row/>" + block
        + "</sheetData></r></is></c>"
    )
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{_inline(HEADER).format(r=1)}</row>'
        + f"<row r=\"2\">{cell}</row>" + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    tracemalloc.start()
    try:
        with pytest.raises(PipeTableError, match="which is not allowed here"):
            read_table(path)
    finally:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert peak < 5 * 1024 * 1024


def test_a_row_with_ext_lst_still_imports(tmp_path: Path) -> None:
    import time

    # CT_Row allows extLst: a row extension with vendor content imports, and
    # the extension payload is dropped at close.
    header = _inline(HEADER).format(r=1)
    data = _inline(["FP_A", "P1", "IN", "J1", "10", "0", "0.05", "0.00005"]).format(r=2)
    ext = (
        '<extLst><ext uri="{B025F937-C7B1-47D3-BEBA-D7CE9E37}">'
        + '<x:foo xmlns:x="urn:x"><x:bar>1</x:bar></x:foo></ext></extLst>'
    )
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{header}</row>'
        + f"<row r=\"2\">{data}{ext}</row>" + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 5
    assert [row["flowpath"] for row in table.rows] == ["FP_A"]


def test_openpyxl_shaped_parts_still_import(tmp_path: Path) -> None:
    import time

    # The worksheet wrapper openpyxl writes: sheetPr, dimension, sheetViews,
    # sheetFormatPr, cols, mergeCells and pageMargins around the sheetData.
    cols = "".join(
        f'<c r="{chr(65 + position)}1" t="inlineStr"><is><t>{text}</t></is></c>'
        for position, text in enumerate(HEADER)
    )
    data = "".join(
        f'<c r="{chr(65 + position)}2" t="inlineStr"><is><t>{text}</t></is></c>'
        for position, text in enumerate(["FP_A", "P1", "IN", "J1", "10", "0", "0.05", "0.00005"])
    )
    sheet = (
        f'<worksheet xmlns="{_SST_NS}">'
        '<sheetPr><outlinePr summaryBelow="1" summaryRight="1"/></sheetPr>'
        '<dimension ref="A1:H4"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<selection activeCell="A1" sqref="A1"/></sheetView></sheetViews>'
        '<sheetFormatPr baseColWidth="8" defaultRowHeight="15"/>'
        '<cols><col width="20" customWidth="1" min="1" max="1"/></cols>'
        f"<sheetData><row r=\"1\">{cols}</row>"
        f"<row r=\"2\">{data}</row><row r=\"4\"></row></sheetData>"
        '<mergeCells count="1"><mergeCell ref="A4:B4"/></mergeCells>'
        '<pageMargins left="0.75" right="0.75" top="1" bottom="1" header="0.5" footer="0.5"/>'
        "</worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 5
    assert [row["flowpath"] for row in table.rows] == ["FP_A"]


def test_a_deep_ext_nest_is_refused(tmp_path: Path) -> None:
    import time

    # A worksheet-level ext that nests 100 deep refuses past the opaque
    # depth cap instead of building the chain to the 50 MB part cap.
    nest = "<a>" * 100 + "</a>" * 100
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{_inline(HEADER).format(r=1)}</row>"
        "</sheetData>"
        f"<extLst><ext uri=\"urn:x\">{nest}</ext></extLst></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="deeper than"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_a_wide_ext_flood_is_refused(tmp_path: Path) -> None:
    import time

    # 200k same-namespace children inside one worksheet-level ext pass the
    # depth cap but not the per-subtree element count.
    flood = "<junk/>" * 200_000
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{_inline(HEADER).format(r=1)}</row>"
        "</sheetData>"
        f"<extLst><ext uri=\"urn:x\">{flood}</ext></extLst></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="one opaque part"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_rows_inside_an_opaque_ext_are_never_read(tmp_path: Path) -> None:
    import time

    # A fake sheetData smuggled inside an ext opens as opaque content: its
    # rows fail the stack-depth anchor, so the table stays empty.
    inner = "".join(
        f"<row><c><v>{number}</v></c></row>" for number in range(3)
    )
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{_inline(HEADER).format(r=1)}</row>"
        "</sheetData>"
        f"<extLst><ext uri=\"urn:x\"><sheetData>{inner}</sheetData></ext></extLst>"
        "</worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 5
    assert len(table.rows) == 0


def test_mixed_kept_and_removable_siblings_in_si(tmp_path: Path) -> None:
    import time

    # 20k runs kept for the text, then 60k phoneticPr cleared at close: the
    # old quadratic remove scanned past all kept runs for every detach.
    runs = "".join("<r><t>x</t></r>" for _ in range(20000))
    runs += "<phoneticPr/>" * 60000
    sst = f'<sst xmlns="{_SST_NS}"><si>' + runs + "</si></sst>"
    sheet = _sheet([_inline(HEADER).format(r=1)] + ['<c r="A2" t="s"><v>0</v></c>'])
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst)
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 5
    assert table.rows[0]["flowpath"] == "x" * 20000


def test_mixed_kept_and_removable_siblings_in_r(tmp_path: Path) -> None:
    import time

    # 20k kept t, then 60k rPr cleared at close inside one run wrapper.
    runs = "".join("<t>x</t>" for _ in range(20000))
    runs += '<rPr><sz val="11"/></rPr>' * 60000
    sst = f'<sst xmlns="{_SST_NS}"><si><r>' + runs + "</r></si></sst>"
    sheet = _sheet([_inline(HEADER).format(r=1)] + ['<c r="A2" t="s"><v>0</v></c>'])
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst)
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 5
    assert table.rows[0]["flowpath"] == "x" * 20000


def test_mixed_kept_and_removable_siblings_in_c(tmp_path: Path) -> None:
    import time

    # 40k kept values plus 40k row extensions cleared at close in one cell.
    kids = "".join("<v>1</v><extLst><ext/></extLst>" for _ in range(40000))
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData><row r="1">{_inline(HEADER).format(r=1)}</row>'
        + f"<row r=\"2\"><c>{kids}</c></row>" + "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 5
    assert len(table.rows) == 1


def test_an_excel_365_shaped_workbook_still_imports(tmp_path: Path) -> None:
    import time

    # The worksheet wrapper Excel 365 writes: controls in
    # mc:AlternateContent, tableParts, hyperlinks, drawing, legacyDrawing,
    # frozen panes with a sheetView extLst, autoFilter with extLst,
    # customSheetViews, protectedRanges, oleObjects and an sst extLst.
    mc = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    cols = "".join(
        f'<c r="{chr(65 + position)}1" t="inlineStr"><is><t>{text}</t></is></c>'
        for position, text in enumerate(HEADER)
    )
    data = "".join(
        f'<c r="{chr(65 + position)}2" t="inlineStr"><is><t>{text}</t></is></c>'
        for position, text in enumerate(["FP_A", "P1", "IN", "J1", "10", "0", "0.05", "0.00005"])
    )
    sheet = (
        f'<worksheet xmlns="{_SST_NS}" xmlns:mc="{mc}" xmlns:r="{rel}">'
        '<dimension ref="A1:H3"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane xSplit="1" ySplit="1" topLeftCell="B2" activePane="bottomRight" state="frozen"/>'
        '<selection pane="bottomRight" activeCell="B2" sqref="B2"/>'
        '<extLst><ext uri="{B025F937-C7B1-47D3-BEBA-D7CE9E37}">'
        '<x:foo xmlns:x="urn:x"/></ext></extLst>'
        "</sheetView></sheetViews>"
        '<sheetFormatPr baseColWidth="8" defaultRowHeight="15"/>'
        '<cols><col width="20" customWidth="1" min="1" max="1"/></cols>'
        f"<sheetData><row r=\"1\">{cols}</row>"
        f"<row r=\"2\">{data}</row><row r=\"4\"></row></sheetData>"
        '<mergeCells count="1"><mergeCell ref="A4:B4"/></mergeCells>'
        '<phoneticPr fontId="1"/>'
        '<conditionalFormatting sqref="E2:E3">'
        '<cfRule type="cellIs" operator="greaterThan" priority="1">'
        "<formula>5</formula></cfRule></conditionalFormatting>"
        '<dataValidations count="1">'
        '<dataValidation type="whole" operator="between" allowBlank="1" showDropDown="1" sqref="B2">'
        "<formula1>0</formula1><formula2>10</formula2></dataValidation></dataValidations>"
        '<hyperlinks><hyperlink ref="B2" r:id="rIdH1"/></hyperlinks>'
        '<pageMargins left="0.75" right="0.75" top="1" bottom="1" header="0.5" footer="0.5"/>'
        '<pageSetup paperSize="9" orientation="portrait" fitToWidth="1"/>'
        "<headerFooter><oddHeader>&amp;CHeader</oddHeader></headerFooter>"
        '<rowBreaks><brk id="0" max="2" man="1"/></rowBreaks>'
        '<autoFilter ref="A1:H2"><filterColumn colId="1">'
        '<filters blank="1"><filter val="P1"/></filters></filterColumn>'
        '<extLst><ext uri="{B025F937-C7B1-47D3-BEBA-D7CE9E37}"/></extLst></autoFilter>'
        '<customSheetViews><customSheetView guid="{B025F937-C7B1-47D3-BEBA-D7CE9E37}">'
        '<pageSetup paperSize="9"/></customSheetView></customSheetViews>'
        '<protectedRanges><protectedRange password="DAA7" sqref="A1:A2" name="r1"/>'
        "</protectedRanges>"
        '<drawing r:id="rIdD1"/><legacyDrawing r:id="rIdL1"/>'
        '<oleObjects><oleObject progId="Forms.CheckBox.1" shapeId="1" r:id="rIdO1"/>'
        "</oleObjects>"
        '<tableParts count="1"><tablePart r:id="rIdT1"/></tableParts>'
        '<extLst><ext uri="{B025F937-C7B1-47D3-BEBA-D7CE9E37}">'
        '<x:bar xmlns:x="urn:x">1</x:bar></ext></extLst>'
        "<mc:AlternateContent>"
        '<mc:Choice Requires="x14"><controls><control shapeId="1" r:id="rIdC1" name="cbx"/>'
        "</controls></mc:Choice>"
        "<mc:Fallback><oleObjects/></mc:Fallback>"
        "</mc:AlternateContent>"
        "</worksheet>"
    )
    sst = (
        f'<sst xmlns="{_SST_NS}"><si><t>FP_B</t></si>'
        '<extLst><ext uri="{B025F937-C7B1-47D3-BEBA-D7CE9E37}"/></extLst></sst>'
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst)
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 2
    assert [row["flowpath"] for row in table.rows] == ["FP_A"]


def test_a_32k_rich_text_string_still_imports(tmp_path: Path) -> None:
    import time

    # About 32k characters formatted one character per run: 32,000 runs
    # with real run properties start about 131k elements, so this pins the
    # subtree cap above that worst legitimate case.
    runs = "".join(
        "<r><rPr><sz val=\"11\"/></rPr><t>x</t></r>" for _ in range(32000)
    )
    sst = f'<sst xmlns="{_SST_NS}"><si>' + runs + "</si></sst>"
    sheet = _sheet([_inline(HEADER).format(r=1)] + ['<c r="A2" t="s"><v>0</v></c>'])
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst)
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 5
    assert table.rows[0]["flowpath"] == "x" * 32000


def test_a_row_with_more_cells_than_columns_is_refused(tmp_path: Path) -> None:
    header = _inline(HEADER).format(r=1)
    cells = "".join(f'<c r="A{number}"><v>1</v></c>' for number in range(2, 302))
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{header}</row>"
        f"<row r=\"2\">{cells}</row>"
        "</sheetData></worksheet>"
    )
    with pytest.raises(PipeTableError, match="256-column"):
        read_table(_xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([])))


def test_an_entity_chain_is_refused_without_expansion(tmp_path: Path) -> None:
    import time

    # A billion-laughs chain: nested entities that would expand to about
    # 0.8 MB. The scan must refuse the declarations, never expand them.
    lol = "<!DOCTYPE lolz [<!ENTITY lol \"lollollollollollollollol\">" + "".join(
        f"<!ENTITY lol{rank} \"{'&lol%d;' % (rank - 1) * 8}\">"
        for rank in range(1, 6)
    ) + "]>"
    sheet = _sheet([_inline(HEADER).format(r=1)])
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, lol + _sst(["&lol5;"]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="DOCTYPE|entity"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_an_oversized_bracket_unit_is_cut_in_params(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_text(
        "flowpath,pipe,from_node,to_node,length (UNIT),elevation_m,inner_diameter_m,roughness_m\n".replace(
            "UNIT", "u" * 30_000)
        + "FP_A,P1,IN,J1,10,0,0.05,0.00005\n",
        encoding="utf-8",
    )
    table = read_table(path)
    assert len(table.rows) == 1 and "length_m" not in table.rows[0]
    assert len(table.issues) == 1
    assert table.issues[0].code == "reader_unknown_length_unit"
    assert table.issues[0].params == {"unit": "u" * 48}
    assert len(table.issues[0].reason) > 30_000


def _patch_part_size(path: Path, name: str, size: int) -> None:
    """Lie about an entry's uncompressed size in the central directory."""
    import struct

    raw = bytearray(path.read_bytes())
    encoded = name.encode()
    position = 0
    while True:
        position = raw.find(b"PK\x01\x02", position)
        assert position >= 0, "part entry not found"
        name_length = struct.unpack("<H", raw[position + 28:position + 30])[0]
        if raw[position + 46:position + 46 + name_length] == encoded:
            raw[position + 20:position + 24] = struct.pack("<I", size)
            raw[position + 24:position + 28] = struct.pack("<I", size)
            path.write_bytes(bytes(raw))
            return
        position += 1


def test_an_oversize_declared_part_is_refused_before_reading(tmp_path: Path) -> None:
    sheet = _sheet([_inline(HEADER).format(r=1)])
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    _patch_part_size(path, "xl/workbook.xml", 150_000_000)
    with pytest.raises(PipeTableError, match="1 MiB"):
        read_table(path)


def test_fake_rows_before_a_column_flood_still_refuse(tmp_path: Path) -> None:
    import time

    # HIGH-1: a fake row inside sheetPr and one inside an extLst must not
    # disturb the per-row accounting, so the real row that floods past 256
    # cells still refuses with the column message.
    header = _inline(HEADER).format(r=1)
    flood = "".join(f'<c r="X{number}"><v>1</v></c>' for number in range(2, 302))
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetPr><row/></sheetPr>'
        f'<extLst><ext uri="urn:x"><row/></ext></extLst>'
        f"<sheetData><row r=\"1\">{header}</row>"
        f"<row r=\"2\">{flood}</row></sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="cell X258 is beyond the 256-column limit"):
        read_table(path)
    assert time.perf_counter() - started < 2


def test_fake_rows_before_legitimate_data_still_import(tmp_path: Path) -> None:
    import time

    # HIGH-1: two fake rows before the real table must not disturb the
    # per-row accounting, so the legitimate data still imports.
    header = _inline(HEADER).format(r=1)
    data = _inline(["FP_A", "P1", "IN", "J1", "10", "0", "0.05", "0.00005"]).format(r=2)
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetPr><row/></sheetPr>'
        f'<extLst><ext uri="urn:x"><row/></ext></extLst>'
        f"<sheetData><row r=\"1\">{header}</row>"
        f"<row r=\"2\">{data}</row></sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 2
    assert [row["flowpath"] for row in table.rows] == ["FP_A"]


def test_a_fake_row_does_not_suppress_the_row_cap(tmp_path: Path) -> None:
    import time

    # HIGH-1: one fake row drove the old row counter to exactly zero for the
    # next real row, so its children were never counted and 200k values were
    # imported as one row. The gated counter refuses instead in about 0.7 s.
    junk = "<v>1</v>" * 200_000
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetPr><row/></sheetPr>'
        f"<sheetData><row r=\"1\">{_inline(HEADER).format(r=1)}</row>"
        f"<row r=\"3\"><c>{junk}</c></row></sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="a table row holds more than"):
        read_table(path)
    assert time.perf_counter() - started < 5


def test_an_ext_lst_flood_under_a_row_is_refused(tmp_path: Path) -> None:
    import tracemalloc

    # MEDIUM-1: row extensions count toward the row cap, so 2000 small extLst
    # regions (82 counted elements each) refuse instead of accumulating.
    region = "<extLst><ext uri=\"urn:x\">" + "<junk/>" * 80 + "</ext></extLst>"
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{_inline(HEADER).format(r=1)}</row>"
        f"<row r=\"2\">" + region * 2000 + "</row></sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    tracemalloc.start()
    try:
        with pytest.raises(PipeTableError, match="a table row holds more than"):
            read_table(path)
    finally:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert peak < 5 * 1024 * 1024


def test_an_ext_lst_flood_inside_a_cell_is_refused(tmp_path: Path) -> None:
    import tracemalloc

    # MEDIUM-1: cell extensions count toward the row cap too.
    region = "<extLst><ext uri=\"urn:x\">" + "<junk/>" * 80 + "</ext></extLst>"
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{_inline(HEADER).format(r=1)}</row>"
        f"<row r=\"2\"><c>" + region * 2000 + "</c></row></sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    tracemalloc.start()
    try:
        with pytest.raises(PipeTableError, match="a table row holds more than"):
            read_table(path)
    finally:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert peak < 5 * 1024 * 1024


def test_an_ext_lst_flood_directly_under_sheet_data_is_refused(tmp_path: Path) -> None:
    import time
    import tracemalloc

    # MEDIUM-1: one sheetData-level extLst region is capped at 1000 elements,
    # far below the 100k worksheet-level cap, so a 2001-element flood in a
    # single region refuses.
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{_inline(HEADER).format(r=1)}</row>"
        "<extLst><ext uri=\"urn:x\">" + "<ext/>" * 2000 + "</ext></extLst>"
        "</sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    tracemalloc.start()
    try:
        with pytest.raises(PipeTableError, match="more than 1000 elements"):
            read_table(path)
    finally:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert time.perf_counter() - started < 2
    assert peak < 5 * 1024 * 1024


def test_furigana_text_is_never_read(tmp_path: Path) -> None:
    import time

    # LOW: rPh/t holds furigana guides, not cell text. Both the shared-string
    # path and the inlineStr cell path read only t and r/t.
    sst = (
        f'<sst xmlns="{_SST_NS}"><si><r><rPr><sz val="11"/></rPr><t>BASE</t></r>'
        '<rPh sb="0" eb="1"><t>FURI</t></rPh></si></sst>'
    )
    sheet = _sheet([_inline(HEADER).format(r=1)] + ['<c r="A2" t="s"><v>0</v></c>'])
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst)
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 2
    assert table.rows[0]["flowpath"] == "BASE"
    inline = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{_inline(HEADER).format(r=1)}</row><row r=\"2\">"
        '<c r="A2" t="inlineStr"><is><r><t>A</t></r>'
        '<rPh sb="0" eb="1"><t>B</t></rPh></is></c>'
        + "".join(
            f'<c r="{chr(66 + position)}2" t="inlineStr"><is><t>x</t></is></c>'
            for position in range(7)
        )
        + "</row></sheetData></worksheet>"
    )
    table = read_table(_xlsx_raw(tmp_path / "inline.xlsx", inline, _sst([])))
    assert time.perf_counter() - started < 2
    assert table.rows[0]["flowpath"] == "A"


def test_a_second_sheet_data_is_refused(tmp_path: Path) -> None:
    import time

    # LOW: a sheet part holds exactly one sheetData element.
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{_inline(HEADER).format(r=1)}</row></sheetData>"
        "<sheetData></sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    with pytest.raises(PipeTableError, match="second sheetData"):
        read_table(path)
    assert time.perf_counter() - started < 2


def test_preserved_whitespace_text_still_imports(tmp_path: Path) -> None:
    import time

    # LOW pin: an xml:space="preserve" string with padding imports; the
    # text fields are stripped later by _converted, so this pins the shape
    # end to end rather than the raw spacing.
    sst = (
        f'<sst xmlns="{_SST_NS}"><si>'
        '<t xml:space="preserve">  FP_A  </t></si></sst>'
    )
    sheet = _sheet([_inline(HEADER).format(r=1)] + ['<c r="A2" t="s"><v>0</v></c>'])
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst)
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 2
    assert table.rows[0]["flowpath"] == "FP_A"


def test_an_empty_t_reads_as_missing_text(tmp_path: Path) -> None:
    import time

    # LOW pin: an empty shared-string t reads as "", which read_table skips,
    # so the column is absent from the record while the row still imports.
    sst = f'<sst xmlns="{_SST_NS}"><si><t></t></si></sst>'
    row = (
        '<c r="A2" t="inlineStr"><is><t>FP_A</t></is></c>'
        '<c r="B2" t="s"><v>0</v></c>'
        + "".join(
            f'<c r="{chr(67 + position)}2" t="inlineStr"><is><t>x</t></is></c>'
            for position in range(6)
        )
    )
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{_inline(HEADER).format(r=1)}</row>"
        f"<row r=\"2\">{row}</row></sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, sst)
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 2
    assert table.rows[0]["flowpath"] == "FP_A"
    assert "pipe" not in table.rows[0]


def test_a_cell_with_only_v_reads_its_number(tmp_path: Path) -> None:
    import time

    # LOW pin: a cell with no type and a single cached value reads as a
    # number without any inline-string wrapper.
    row = "".join(
        f'<c r="{chr(65 + position)}2" t="inlineStr"><is><t>{text}</t></is></c>'
        for position, text in enumerate(["FP_A", "P1", "IN", "J1"])
    )
    row += '<c r="E2"><v>10</v></c>'
    row += "".join(
        f'<c r="{chr(70 + position)}2" t="inlineStr"><is><t>{text}</t></is></c>'
        for position, text in enumerate(["0", "0.05", "0.00005"])
    )
    sheet = (
        f'<worksheet xmlns="{_SST_NS}"><sheetData>'
        f"<row r=\"1\">{_inline(HEADER).format(r=1)}</row>"
        f"<row r=\"2\">{row}</row></sheetData></worksheet>"
    )
    path = _xlsx_raw(tmp_path / "pipes.xlsx", sheet, _sst([]))
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 2
    assert table.rows[0]["length_m"] == 10.0


def test_encrypted_workbook_is_refused_with_its_code(tmp_path: Path) -> None:
    import time

    # The code travels on the exception (read refusals raise; they never
    # become import issues, so it stays out of READER_ISSUE_CODES). The
    # frontend fixture and ko/en text for it belong to lanes nwep/nwfe.
    path = tmp_path / "locked.xlsx"
    path.write_bytes(bytes((0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1)))
    started = time.perf_counter()
    with pytest.raises(PipeTableError) as excinfo:
        read_table(path)
    assert time.perf_counter() - started < 2
    assert excinfo.value.code == "table_encrypted"
    assert "unprotected copy" in str(excinfo.value)


def test_drm_wrapped_workbook_is_refused_with_its_code(tmp_path: Path) -> None:
    import time

    # A document-DRM wrapper header: ASCII tag + one non-ASCII byte,
    # not a zip.
    path = tmp_path / "wrapped.xlsx"
    path.write_bytes(b"XXXDRMC\xb8" + bytes(8))
    started = time.perf_counter()
    with pytest.raises(PipeTableError) as excinfo:
        read_table(path)
    assert time.perf_counter() - started < 2
    assert excinfo.value.code == "table_encrypted"
    assert "unprotected copy" in str(excinfo.value)


def test_drm_marker_in_csv_is_not_an_encrypted_workbook(tmp_path: Path) -> None:
    import time

    # The DRM-marker rule is for workbooks only; a .csv that happens to
    # start with those bytes parses as text instead.
    path = tmp_path / "notes.csv"
    path.write_bytes(b"DRM notes,second\n1,2\n")
    started = time.perf_counter()
    with pytest.raises(PipeTableError) as excinfo:
        read_table(path)
    assert time.perf_counter() - started < 2
    assert excinfo.value.code == ""


def test_plain_non_zip_keeps_the_old_refusal(tmp_path: Path) -> None:
    import time

    path = tmp_path / "notes.xlsx"
    path.write_text("just some text, not a workbook", encoding="utf-8")
    started = time.perf_counter()
    with pytest.raises(PipeTableError) as excinfo:
        read_table(path)
    assert time.perf_counter() - started < 2
    assert excinfo.value.code == ""
    assert "not a valid workbook" in str(excinfo.value)


def test_japanese_headers_map_start_end_coordinates(tmp_path: Path) -> None:
    import time

    # Synthetic headers: start/end X/Y/Z in Japanese with metre units, one
    # of them split by a line break, plus diameter/length/roughness.
    header = (
        "flowpath,pipe,from_node,to_node,"
        '"配管始点\nX座標(m)",配管始点 Y座標(m),配管始点 Z座標(m),'
        "配管終点 X座標(m),配管終点 Y座標(m),配管終点 Z座標(m),"
        "内径,長さ,粗度,"
        "node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction"
    )
    row = (
        "FP_1,P1,SRC,SNK,0.0,0.0,0.0,8.0,6.0,5.0,0.05,10.0,5e-05,,,,,,"
    )
    nodes = (
        ",,,,,,,,,,,,,SRC,source,2.0,25.0,1.0,0.0\n"
        ",,,,,,,,,,,,,SNK,sink,1.0,25.0,0.5,0.0\n"
    )
    path = tmp_path / "pipes.csv"
    path.write_text(header + "\n" + row + "\n" + nodes, encoding="utf-8")
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 2
    record = table.rows[0]
    assert record["x_start_m"] == 0.0
    assert record["y_start_m"] == 0.0
    assert record["z_start_m"] == 0.0
    assert record["x_m"] == 8.0
    assert record["y_m"] == 6.0
    assert record["z_m"] == 5.0
    assert record["inner_diameter_m"] == 0.05
    assert record["length_m"] == 10.0
    assert record["roughness_m"] == 5e-05


def test_full_width_header_forms_map(tmp_path: Path) -> None:
    import time

    # Full-width Ｘ, full-width brackets and unit read as ASCII halves.
    header = (
        "flowpath,pipe,from_node,to_node,"
        "配管始点 Ｘ座標（ｍ）,配管始点 Y座標(m),配管始点 Z座標(m),"
        "配管終点 X座標(m),配管終点 Y座標(m),配管終点 Z座標(m),"
        "内径,長さ,粗度,"
        "node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction"
    )
    row = (
        "FP_1,P1,SRC,SNK,0.0,0.0,0.0,8.0,6.0,5.0,0.05,10.0,5e-05,,,,,,"
    )
    nodes = (
        ",,,,,,,,,,,,,SRC,source,2.0,25.0,1.0,0.0\n"
        ",,,,,,,,,,,,,SNK,sink,1.0,25.0,0.5,0.0\n"
    )
    path = tmp_path / "pipes.csv"
    path.write_text(header + "\n" + row + "\n" + nodes, encoding="utf-8")
    started = time.perf_counter()
    table = read_table(path)
    assert time.perf_counter() - started < 2
    record = table.rows[0]
    assert record["x_start_m"] == 0.0
    assert record["x_m"] == 8.0
    assert record["inner_diameter_m"] == 0.05
