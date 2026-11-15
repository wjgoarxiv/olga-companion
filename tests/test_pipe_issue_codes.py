"""Issue codes registry: every import issue carries a stable code and params.

The frontend draft card renders `pipeDraft.reason.<code>` with `params` and
keeps the English `reason` for the model, so the backend registry and
`frontend/tests/fixtures/pipe-issue-codes.json` must stay in sync.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from olga_companion import pipe_table_import
from olga_companion.pipe_table import read_table
from olga_companion.pipe_table_import import ImportOptions, build_case_spec

TABLES = Path(__file__).parent / "fixtures" / "pipe_tables"
SMALL = (TABLES / "small_branch.csv").read_text(encoding="utf-8")
OPTIONS = ImportOptions(
    pvt_reference="fluid.tab", fluid_label="TEST_FLUID", thermal={"model": "adiabatic"},
    end_time_s=600.0, max_section_m=1.0,
)
FIXTURE = Path(__file__).parent.parent / "frontend" / "tests" / "fixtures" / "pipe-issue-codes.json"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "pipes.csv"
    path.write_text(text, encoding="utf-8")
    return path


def _coord_table(*rows: str) -> str:
    header = (
        "flowpath,pipe,from_node,to_node,length_m,elevation_m,"
        "x_start_m,y_start_m,z_start_m,x_m,y_m,z_m,"
        "inner_diameter_m,roughness_m,node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction"
    )
    return header + "\n" + "".join(rows)


def _node_row(node: str, kind: str, pressure: str = "5.0") -> str:
    return f",,,,,,,,,,,,,,{node},{kind},{pressure},25.0,1.0,0.0\n"


def _coord_pipe(flowpath: str, pipe: str, frm: str, to: str, start: str, end: str) -> str:
    return f"{flowpath},{pipe},{frm},{to},,,{start},{end},0.05,5e-05,,,,,,\n"


def _bad_tables(tmp_path: Path) -> list[str]:
    header = SMALL.splitlines()[0]
    trunk = _coord_table(
        _node_row("SRC", "source"),
        _node_row("SNK", "sink", "1.0"),
        _coord_pipe("FP_1", "P1", "SRC", "SNK", ",,", "8.0,6.0,0.0"),
    )
    return [
        # missing diameter + zero length + mixed styles + bad node kind
        SMALL.replace(",20.0,0.0,0.05,", ",20.0,0.0,,", 1),
        SMALL.replace("FP_A,FP_A_P1,J_1,OUT_A,10.0,", "FP_A,FP_A_P1,J_1,OUT_A,0.0,", 1),
        SMALL + "FP_C,FP_C_P1,J_1,OUT_D,3.0,0.0,0.05,5e-05,,,,,,,,,,\n",
        SMALL.replace(",,,,,,,,,,,,OUT_B,sink,", ",,,,,,,,,,,,OUT_B,bogus,"),
        # no pipe rows, disconnected, missing boundary, valve faults
        "\n".join(line for line in SMALL.splitlines() if line.startswith(("flowpath", ",,"))) + "\n",
        SMALL + "FP_X,FP_X_P1,ISO_A,ISO_B,1.0,0.0,0.05,5e-05,,,,,,,,,,\n",
        "\n".join(line for line in SMALL.splitlines() if not line.startswith(",,,,,,,,,,,,OUT_B")) + "\n",
        SMALL.replace("V_FP_A,0.5,", "V_FP_A,,", 1),
        SMALL.replace("V_FP_A,0.5,", "V_FP_A,2.0,", 1),
        SMALL.replace('"0:1, 299:1, 300:0"', '"e:1"', 1),
        SMALL.replace("FP_IN,FP_IN_P1,SRC,J_1,20.0,0.0,", "FP_IN,FP_IN_P1,SRC,J_1,20.0,5000.0,", 1),
        SMALL.replace("FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,0.04,", "FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,40.0,", 1),
        SMALL.replace("FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,0.04,5e-05,", "FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,0.04,0.5,", 1),
        SMALL.replace("SRC,source,2.4,25.0,1.0,0.0", "SRC,source,2.4,25.0,3.0,0.0"),
        SMALL.replace("SRC,source,2.4,25.0,1.0,0.0", "SRC,source,2.4,5000.0,1.0,0.0"),
        SMALL.replace("SRC,source,2.4,25.0,1.0,0.0", "SRC,source,2.4,,1.0,0.0"),
        SMALL.replace("FP_A,FP_A_P1,J_1,OUT_A,10.0,", "FP_A,FP_A_P1,J_1,OUT_A,1xx,", 1),
        SMALL + "FP_A,FP_A_P9,J_1,OUT_X,1.0,0.0,0.05,5e-05,,,,,,,,,,\n",
        SMALL + "FP_Z,FP_Z_P1,,,1.0,0.0,0.05,5e-05,,,,,,,,,,\n",
        SMALL + ",P9,IN,J9,1.0,0.0,0.05,5e-05,,,,,,,,,,\n",
        SMALL.replace("FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,0.04,", "FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,inf,", 1),
        SMALL.replace("FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,0.04,5e-05,", "FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,0.04,-5e-05,", 1),
        SMALL.replace('"0:1, 299:1, 300:0"', '""', 1),
        SMALL + "FP_C,FP_C_P1,J_1,OUT_B,3.0,0.0,0.05,5e-05,,,,,,,,,,\n",
        # A 2-in/2-out junction names every involved row.
        SMALL
        + "FP_C,FP_C_P1,SRC2,J_1,3.0,0.0,0.05,5e-05,,,,,,,,,,\n"
        + "FP_D,FP_D_P1,J_1,OUT_D,3.0,0.0,0.05,5e-05,,,,,,,,,,\n"
        + ",,,,,,,,,,,,SRC2,source,5.0,25.0,1.0,0.0\n"
        + ",,,,,,,,,,,,OUT_D,sink,1.0,25.0,0.5,0.0\n",
        # A closed inlet without a mass flow is refused before its values.
        SMALL
        + "FP_W,FP_W_P1,WELL,J_1,5.0,0.0,0.05,5e-05,,,,,,,,,,\n"
        + ",,,,,,,,,,,,WELL,closed,,,,\n",
        SMALL.replace(",,,,,,,,,,,,OUT_B,sink,2.0,25.0,0.5,0.0", ",,,,,,,,,,,,OUT_B,closed,,,,")
        + "\n",
        SMALL + ",,,,,,,,,,,,OUT_B,sink,1.0,25.0,0.5,0.0\n",
        # coordinate faults: zero-length pipe, clashing starts, mixed table
        trunk.replace("8.0,6.0,0.0,0.05", "0.0,0.0,0.0,0.05"),
        _coord_table(
            _node_row("SRC", "source"),
            _node_row("SRC2", "source", "4.0"),
            _node_row("SNK", "sink", "1.0"),
            _coord_pipe("FP_A", "P1", "SRC", "J_1", "0.0,0.0,0.0", "100.0,0.0,0.0"),
            _coord_pipe("FP_B", "P1", "SRC2", "J_1", "0.0,40.0,0.0", "100.05,0.0,0.0"),
            _coord_pipe("FP_C", "P1", "J_1", "SNK", ",,", "150.0,0.0,0.0"),
        ),
        # A second inlet without a stated start is refused once the origin
        # is taken.
        _coord_table(
            _node_row("SRC", "source"),
            _node_row("SRC2", "source", "4.0"),
            _node_row("SNK", "sink", "1.0"),
            _coord_pipe("FP_A", "P1", "SRC", "J_1", ",,", "100.0,0.0,0.0"),
            _coord_pipe("FP_B", "P1", "SRC2", "J_1", ",,", "100.0,0.0,0.0"),
            _coord_pipe("FP_C", "P1", "J_1", "SNK", ",,", "150.0,0.0,0.0"),
        ),
        # A coordinate length past 10,000 km is refused.
        _coord_table(
            _node_row("SRC", "source"),
            _node_row("SNK", "sink", "1.0"),
            _coord_pipe("FP_1", "P1", "SRC", "SNK", ",,", "9000000.0,9000000.0,0.0"),
        ),
        # Non-finite ends and starts are refused naming their field.
        _coord_table(
            _node_row("SRC", "source"),
            _node_row("SNK", "sink", "1.0"),
            _coord_pipe("FP_1", "P1", "SRC", "SNK", ",,", "inf,0.0,0.0"),
        ),
        _coord_table(
            _node_row("SRC", "source"),
            _node_row("SNK", "sink", "1.0"),
            _coord_pipe("FP_1", "P1", "SRC", "SNK", "1000000000.0,0.0,0.0", "8.0,6.0,0.0"),
        ),
        _coord_table(
            _node_row("SRC", "source"),
            _node_row("SNK", "sink", "1.0"),
            _coord_pipe("FP_1", "P1", "SRC", "SNK", "8.0,,0.0", "8.0,6.0,0.0"),
        ),
        _coord_table(
            _node_row("SRC", "source"),
            _node_row("SNK", "sink", "1.0"),
            _coord_pipe("FP_A", "P1", "SRC", "J_1", ",,", "100.0,0.0,0.0"),
            _coord_pipe("FP_B", "P1", "J_1", "SNK", "200.0,0.0,0.0", "150.0,0.0,0.0"),
        ),
        _coord_table(
            _node_row("SRC", "source"),
            _node_row("SNK", "sink", "1.0"),
            _coord_pipe("FP_1", "P1", "SRC", "SNK", ",,", "8.0,6.0,0.0"),
            _coord_pipe("FP_1", "P2", "SRC", "SNK", "0.0,0.0,0.0", "8.0,6.0,5.0"),
        ),
        trunk + "FP_2,P2,SRC,SNK,5.0,0.0,,,,,,,0.05,5e-05,,,,,,\n",
        _coord_table(
            _node_row("SRC", "source"),
            _node_row("SNK", "sink", "1.0"),
            _coord_pipe("FP_1", "P1", "SRC", "SNK", ",,", "8.0,,"),
        ),
        _coord_table(
            _node_row("SRC", "source"),
            _node_row("SNK", "sink", "1.0"),
            "FP_1,P1,SRC,SNK,6000.0,0.0,,,,,,,0.05,5e-05,,,,,,\n",
            "FP_1,P2,SRC,SNK,6000.0,0.0,,,,,,,0.05,5e-05,,,,,,\n",
        ),
        # A single pipe past the per-pipe section limit fails CaseSpec
        # validation, exercising the spec.<code> pass-through.
        _coord_table(
            _node_row("SRC", "source"),
            _node_row("SNK", "sink", "1.0"),
            "FP_1,P1,SRC,SNK,6000.0,0.0,,,,,,,0.05,5e-05,,,,,,\n",
        ),
        # reader faults: unknown length unit, missing pressure unit, bad mass-flow unit
        SMALL.replace("length_m", "length (ft)", 1),
        SMALL.replace("pressure_bar", "pressure", 1),
        SMALL.replace("temperature_c", "temperature (f)", 1),
        "\n".join([
            "flowpath,pipe,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m,"
            "node,node_kind,Mass Flow (lb),temperature_c,gas_fraction,water_fraction",
            ",,,,,,,,WELL,closed,5.5,40.0,1.0,0.0",
            ",,,,,,,,SNK,sink,1.0,25.0,0.5,0.0",
            "FP_1,P1,WELL,SNK,10.0,2.0,0.05,5e-05,,,,,,",
        ]) + "\n",
        "\n".join([
            header,
            "FP_1,P1,A,B,10.0,0.0,0.05,5e-05,,,,,,,,,,",
            "FP_2,P2,B,A,10.0,0.0,0.05,5e-05,,,,,,,,,,",
        ]),
        # start void fractions: out of range, and two stated values on a joined flowpath
        "\n".join([
            "flowpath,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m,"
            "initial_void_fraction,node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction",
            ",,,,,,,,SRC,source,2.4,25,1,0",
            ",,,,,,,,OUT,sink,2.0,25,1,0",
            "UP,SRC,J_1,10,0,0.05,5e-05,1.5,,,,,,",
            "DOWN,J_1,OUT,10,0,0.05,5e-05,1,,,,,,",
        ]) + "\n",
        "\n".join([
            "flowpath,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m,"
            "initial_void_fraction,node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction",
            ",,,,,,,,SRC,source,2.4,25,1,0",
            ",,,,,,,,OUT,sink,2.0,25,1,0",
            "UP,SRC,J_1,10,0,0.05,5e-05,0,,,,,,",
            "DOWN,J_1,OUT,10,0,0.05,5e-05,1,,,,,,",
        ]) + "\n",
    ]


def _bad_options() -> list[ImportOptions]:
    from dataclasses import replace

    return [
        replace(OPTIONS, max_section_m=float("nan")),
        replace(OPTIONS, max_ratio=0.5),
    ]


def test_the_code_registry_is_a_module_level_tuple() -> None:
    assert isinstance(pipe_table_import.ISSUE_CODES, tuple)
    assert len(pipe_table_import.ISSUE_CODES) >= 45
    assert all(isinstance(code, str) and code for code in pipe_table_import.ISSUE_CODES)
    assert len(set(pipe_table_import.ISSUE_CODES)) == len(pipe_table_import.ISSUE_CODES)


def test_every_negative_control_issue_has_a_registry_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import olga_companion.pipe_table_import as importer_module

    registry = set(pipe_table_import.ISSUE_CODES)
    seen: set[str] = set()

    spec_seen: set[str] = set()

    def _check(result, label: str) -> None:
        assert result.issues, f"{label} raised no issues"
        for issue in result.issues:
            assert issue.code, f"issue without code: {issue!r}"
            if issue.code.startswith("spec."):
                assert len(issue.code) > len("spec."), f"empty spec code: {issue!r}"
                spec_seen.add(issue.code)
            else:
                assert issue.code in registry, f"code {issue.code!r} not in registry"
            assert isinstance(issue.params, dict)
            seen.add(issue.code)

    for index, text in enumerate(_bad_tables(tmp_path)):
        _check(build_case_spec(read_table(_write(tmp_path, text)), OPTIONS), f"bad table {index}")
    for index, options in enumerate(_bad_options()):
        _check(build_case_spec(read_table(_write(tmp_path, SMALL)), options), f"bad options {index}")
    table = read_table(_formula_xlsx(tmp_path / "formula.xlsx"))
    _check(build_case_spec(table, OPTIONS), "formula without cached value")
    node_cap = importer_module.MAX_NODES
    monkeypatch.setattr(importer_module, "MAX_NODES", 2)
    _check(build_case_spec(read_table(_write(tmp_path, SMALL)), OPTIONS), "small table over caps")
    from dataclasses import replace as _replace

    monkeypatch.setattr(importer_module, "MAX_NODES", node_cap)
    monkeypatch.setattr(importer_module, "MAX_SECTIONS", 60)
    _check(
        build_case_spec(
            read_table(_write(tmp_path, SMALL)), _replace(OPTIONS, max_ratio=1.0001)),
        "tight mesh over sections",
    )
    assert seen - spec_seen == registry, sorted(registry - seen)
    assert spec_seen, "no spec.<code> pass-through issue was exercised"


def _formula_xlsx(path: Path) -> Path:
    """One header row and one data row whose length cell is an uncached formula."""
    import zipfile

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    header = "".join(
        f'<c r="{chr(65 + position)}1" t="inlineStr"><is><t>{name}</t></is></c>'
        for position, name in enumerate(
            ["flowpath", "pipe", "from_node", "to_node", "length_m",
             "elevation_m", "inner_diameter_m", "roughness_m"])
    )
    data = "".join(
        f'<c r="{chr(65 + position)}2" t="inlineStr"><is><t>{text}</t></is></c>'
        for position, text in enumerate(["FP_A", "P1", "IN", "J1"])
    ) + '<c r="E2"><f>LEN(A2)</f></c>'
    sheet = (
        f'<worksheet xmlns="{ns}"><sheetData>'
        f"<row r=\"1\">{header}</row><row r=\"2\">{data}</row>"
        "</sheetData></worksheet>"
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
    return path


def test_reader_issues_carry_codes_through_the_import(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_text(
        "flowpath,pipe,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m\n"
        "FP_A,P1,IN,J1,1xx,0,0.05,0.00005\n",
        encoding="utf-8",
    )
    table = read_table(path)
    assert table.issues and all(issue.code for issue in table.issues)
    result = build_case_spec(table, OPTIONS)
    assert result.issues and all(issue.code for issue in result.issues)
    assert all(issue.code in set(pipe_table_import.ISSUE_CODES) for issue in result.issues)


def test_tool_issues_emit_code_and_params_next_to_an_unchanged_reason(tmp_path: Path) -> None:
    from olga_companion.agent import pipe_table_tools as tools_module

    text = SMALL.replace(",20.0,0.0,0.05,", ",20.0,0.0,,", 1)
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None
    payload = tools_module._issues(result)
    assert payload and len(payload) <= tools_module.MAX_ISSUES
    for item, issue in zip(payload, result.issues):
        assert item["reason"] == issue.reason[: tools_module._ISSUE_TEXT]
        assert item["code"] == issue.code
        assert item["params"] == issue.params


def test_twenty_coded_issues_stay_within_the_result_cap(tmp_path: Path) -> None:
    from olga_companion.agent import pipe_table_tools as tools_module

    text = SMALL.replace(",20.0,0.0,0.05,", ",20.0,0.0,,", 1)
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    many = result.issues * ((20 // max(1, len(result.issues))) + 1)
    many = many[:20]
    assert len(many) == 20
    payload = tools_module._issues(
        type(result)(spec=None, issues=tuple(many), summary={}, label_map={}),
    )
    import json as _json

    assert len(_json.dumps({"issues": payload}, ensure_ascii=False)) < 16 * 1024


def test_twenty_huge_unit_issues_stay_within_the_result_cap(tmp_path: Path) -> None:
    from olga_companion.agent import pipe_table_tools as tools_module

    header = "flowpath,pipe,from_node,to_node,length (UNIT),elevation_m,inner_diameter_m,roughness_m\n"
    header = header.replace("UNIT", "u" * 30_000)
    path = tmp_path / "pipes.csv"
    path.write_text(
        header + "FP_A,P1,IN,J1,10,0,0.05,0.00005\n" * 20, encoding="utf-8",
    )
    result = build_case_spec(read_table(path), OPTIONS)
    assert result.spec is None and len(result.issues) == 40
    assert [issue.code for issue in result.issues if issue.code == "reader_unknown_length_unit"]
    assert all(
        len(value) <= 48
        for issue in result.issues
        for value in issue.params.values()
        if isinstance(value, str)
    )
    payload = tools_module._issues(result)
    import json as _json

    assert len(_json.dumps({"issues": payload}, ensure_ascii=False)) < 16 * 1024


def test_the_frontend_fixture_matches_the_registry() -> None:
    registry = list(pipe_table_import.ISSUE_CODES)
    assert FIXTURE.is_file(), f"missing frontend fixture {FIXTURE}"
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == registry
