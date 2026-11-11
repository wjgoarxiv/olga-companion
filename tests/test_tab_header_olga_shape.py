"""OLGA keyword header shape (lane lnheader, task 10): RED-first pins.

The installed OLGA 2022.1 rejects tables whose header does not match its own
keyword samples (``Wrong header`` + exit 18). These tests pin the sample shape:
quoted strings, PVTTABLE LABEL on line 1, the full ordered key list, and no
NOPRES/NOTEMP. They fail until ``tab_writer`` and the validator/parser learn it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from olga_companion import fluids
from olga_companion.pvt_engine import generate_table

OLGA_DATA = Path("/mnt/c/Program Files/Schlumberger/OLGA 2022.1.0/Data")
FIXTURES = Path(__file__).parent / "fixtures" / "fluids"


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def toolkit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    scripts = Path(fluids.fluids_toolkit_status()["toolkit_dir"]) / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return tuple(importlib.import_module(name) for name in ("tab_parser", "tab_validator"))


def _neutral(out_dir: Path, name: str = "neutral.tab"):
    return generate_table(
        out_dir / name,
        ["CO2", "N2"], [0.9, 0.1], "PR",
        [5e5, 20e5], [-30.0, 40.0], "NEUTRAL-CO2-N2",
    )


def test_writer_line_one_is_quoted_pvttable_label(out_dir: Path) -> None:
    _neutral(out_dir)
    lines = (out_dir / "neutral.tab").read_text(encoding="utf-8").splitlines()
    assert lines[0] == 'PVTTABLE LABEL = "NEUTRAL-CO2-N2",PHASE = TWO,\\'


def test_writer_comments_come_after_line_one(out_dir: Path) -> None:
    _neutral(out_dir)
    text = (out_dir / "neutral.tab").read_text(encoding="utf-8")
    before = text.split("PVTTABLE LABEL")[0]
    assert before == "", repr(before)
    head, _, _ = text.partition("COMPONENTS")
    assert "independent table, not multiflash-identical" in head.lower()


def test_writer_has_no_nopres_notemp_and_has_olga_keys(out_dir: Path) -> None:
    _neutral(out_dir)
    text = (out_dir / "neutral.tab").read_text(encoding="utf-8")
    assert "NOPRES" not in text and "NOTEMP" not in text
    header, _, _ = text.partition("PVTTABLE POINT")
    for key in (
        'EOS = "', "COMPONENTS = (", "MOLES = (", "MOLWEIGHT = (",
        "DENSITY = (", "STDPRESSURE =", "STDTEMPERATURE =",
        "GOR =", "GLR =", "STDGASDENSITY =", "STDOILDENSITY =",
        "MESHTYPE = STANDARD", "PRESSURE = (", "TEMPERATURE = (",
        "BUBBLEPRESSURES = (", "BUBBLETEMPERATURES = (", "COLUMNS = (",
    ):
        assert key in header, key
    assert text.count("PVTTABLE POINT") == 4


def test_writer_table_passes_the_validator(out_dir: Path, toolkit) -> None:
    _, validator_module = toolkit
    _neutral(out_dir)
    report = validator_module.TabValidator(str(out_dir / "neutral.tab")).validate()
    assert report["errors"] == [], report["errors"]


def test_validator_rejects_a_comment_before_pvttable_label(toolkit, tmp_path: Path) -> None:
    _, validator_module = toolkit
    path = tmp_path / "leading-comment.tab"
    path.write_text(
        "! provenance note\n"
        'PVTTABLE LABEL = "NEUTRAL",PHASE = TWO,\\\n'
        'COMPONENTS = ( "CO2", "N2" ), MOLES = ( .8, .2 ),\\\n'
        "MESHTYPE = STANDARD,\\\n"
        "PRESSURE = ( 200000, 800000 ) PA,\\\n"
        "TEMPERATURE = ( 10, 30 ) C,\\\n"
        "COLUMNS = ( PT, TM, ROG, ROHL, DROGDP, DROHLDP, DROGDT, DROHLDT, RS,"
        " VISG, VISHL, CPG, CPHL, HG, HHL, TCG, TCHL, SIGGHL, SEG, SEHL )\n"
        "PVTTABLE POINT = ( 200000, 10, 4.1, 650, 2.1e-06, 3.1e-07, -0.021, -0.41,"
        " 0.21, 1.6e-05, 0.00021, 1400, 2300, -12000, -80000, 0.031, 0.151,"
        " 0.0081, 400, -200 )\n"
        "PVTTABLE POINT = ( 200000, 30, 4.2, 660, 2.2e-06, 3.2e-07, -0.022, -0.42,"
        " 0.22, 1.7e-05, 0.00022, 1410, 2310, -11000, -79000, 0.032, 0.152,"
        " 0.0082, 410, -190 )\n"
        "PVTTABLE POINT = ( 800000, 10, 4.3, 670, 2.3e-06, 3.3e-07, -0.023, -0.43,"
        " 0.23, 1.8e-05, 0.00023, 1420, 2320, -10000, -78000, 0.033, 0.153,"
        " 0.0083, 420, -180 )\n"
        "PVTTABLE POINT = ( 800000, 30, 4.4, 680, 2.4e-06, 3.4e-07, -0.024, -0.44,"
        " 0.24, 1.9e-05, 0.00024, 1430, 2330, -9000, -77000, 0.034, 0.154,"
        " 0.0084, 430, -170 )\n",
        encoding="utf-8",
    )
    report = validator_module.TabValidator(str(path)).validate()
    matched = [item for item in report["errors"] if item["rule_id"] == "V030"]
    assert matched, report["errors"]
    assert "rejected" in matched[0]["message"].lower()


def test_validator_warns_but_does_not_fail_on_unquoted_strings(toolkit, tmp_path: Path) -> None:
    _, validator_module = toolkit
    text = (FIXTURES / "keyword_two.tab").read_text(encoding="utf-8")
    unquoted = (
        text.replace('LABEL = "NEUTRAL-TWO"', "LABEL = NEUTRAL-TWO")
        .replace('"CO2", "N2"', "CO2, N2")
    )
    assert unquoted != text
    probe = tmp_path / "keyword_two.probe.tab"
    probe.write_text(unquoted, encoding="utf-8")
    report = validator_module.TabValidator(str(probe)).validate()
    assert not report["errors"], report["errors"]
    assert report["warnings"], "unquoted LABEL/COMPONENTS must warn"


def test_validator_rejects_nopres_notemp_in_a_keyword_header(toolkit, tmp_path: Path) -> None:
    _, validator_module = toolkit
    text = (FIXTURES / "keyword_two.tab").read_text(encoding="utf-8")
    assert "NOPRES" not in text and "NOTEMP" not in text
    bad = text.replace("MESHTYPE = STANDARD, \\", "MESHTYPE = STANDARD, \\\nNOPRES = ( 2 ), NOTEMP = ( 2 ), \\", 1)
    assert bad != text
    path = tmp_path / "with-nopres.tab"
    path.write_text(bad, encoding="utf-8")
    report = validator_module.TabValidator(str(path)).validate()
    matched = [
        item for item in report["errors"]
        if item["rule_id"] == "V032" and ("NOPRES" in item["message"] or "NOTEMP" in item["message"])
    ]
    assert matched, report


def test_an_unknown_header_key_warns_unless_olga_rejects_it(toolkit, tmp_path: Path) -> None:
    """NOPRES and NOTEMP stay errors. Any other unknown key is a warning."""
    _, validator_module = toolkit
    text = (FIXTURES / "keyword_two.tab").read_text(encoding="utf-8")
    bad = text.replace("MESHTYPE = STANDARD, \\", "MESHTYPE = STANDARD, \\\nCUSTOM = 1, \\", 1)
    assert bad != text
    path = tmp_path / "custom-key.tab"
    path.write_text(bad, encoding="utf-8")
    report = validator_module.TabValidator(str(path)).validate()
    custom_errors = [item for item in report["errors"] if item.get("location") == "CUSTOM" or "CUSTOM" in item["message"]]
    custom_warnings = [item for item in report["warnings"] if item["rule_id"] == "V032" and "CUSTOM" in item["message"]]
    assert custom_errors == []
    assert custom_warnings


def test_all_shipped_keyword_tables_pass_with_no_new_errors(toolkit) -> None:
    _, validator_module = toolkit
    if not OLGA_DATA.is_dir():
        pytest.skip("OLGA keyword samples are absent")
    keyword_tabs = sorted(OLGA_DATA.rglob("*.tab"))
    keyword_tabs = [
        path for path in keyword_tabs
        if "PVTTABLE" in path.read_bytes()[:3000].decode("utf-8", errors="replace").upper()
    ]
    if len(keyword_tabs) < 40:
        pytest.skip("OLGA keyword samples are absent")
    failed = {}
    for path in keyword_tabs:
        report = validator_module.TabValidator(str(path)).validate()
        fresh = [
            item for item in report["errors"]
            if item["rule_id"] in {"V030", "V031", "V032"} or "PVTTABLE LABEL" in item["message"]
        ]
        if fresh:
            failed[path.name] = fresh
    assert not failed, failed
