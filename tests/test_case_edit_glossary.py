"""0.1.22 row 7: each edit-table row names the OLGA keyword it changes, and the glossary text shown for
those keywords explains them without suggesting a value."""

from __future__ import annotations

import re
from pathlib import Path

from test_case_edit_routes import _install, _rows, ws  # noqa: F401
from test_controller_edit_table import _loop_case

from olga_companion.case_lint import _TABLE_PATHS
from olga_companion.glossary import entries

_VALUE_WITH_UNIT = re.compile(r"\d[\d.,]*\s*(?:bar|bara|barg|Pa|kPa|MPa|psi|s|ms|min|h|m|mm|cm|in|°C|C|K|kg/s|kg|%|W|J)\b")


def test_every_row_names_its_keyword(ws: Path) -> None:  # noqa: F811
    rows = {row["id"]: row for row in _rows(_loop_case(ws))["rows"]}
    assert rows["integration.end_time_s"]["keyword"] == "INTEGRATION.ENDTIME"
    assert rows["integration.profile_interval_s"]["keyword"] == "PROFILE.DTPLOT"
    assert rows["controllers.PC.setpoint"]["keyword"] == "PARAMETERS.SETPOINT"
    assert rows["controllers.PC.gain"]["keyword"] == "PARAMETERS.AMPLIFICATION"
    assert all(row["keyword"] for row in rows.values()), [row["id"] for row in rows.values() if not row.get("keyword")]


def test_an_owner_case_row_names_its_keyword_too(ws: Path) -> None:  # noqa: F811
    case = ws / "owner.genkey"
    case.write_text("INTEGRATION ENDTIME=600 s, DTSTART=0.1 s\n", encoding="utf-8")
    rows = _rows(case)["rows"]
    assert [row["keyword"] for row in rows] == ["INTEGRATION.ENDTIME"]


def test_the_pid_and_source_keys_explain_themselves_from_the_olga_key_list() -> None:
    by_term = {entry["term"]: entry for entry in entries()}
    for term, source in {
        "SETPOINT": "PIDCONTROLLERkeyinfo.txt",
        "AMPLIFICATION": "PIDCONTROLLERkeyinfo.txt",
        "INTEGRALCONST": "PIDCONTROLLERkeyinfo.txt",
        "DERIVATIVECONST": "PIDCONTROLLERkeyinfo.txt",
        "MASSFLOW": "FLOWPATHkeyinfo.txt",
    }.items():
        entry = by_term.get(term)
        assert entry, term
        assert entry["source"]["file"] == f"OLGA 2022.1 {source}", term
        assert entry.get("meaning_en") and entry.get("meaning_ko"), term
    # The setpoint takes the unit of what it controls; the meaning says so in both languages.
    assert "unit" not in by_term["SETPOINT"]


def test_no_glossary_text_for_an_edit_table_key_suggests_a_value() -> None:
    keys = {path.split(".")[1] for path in _TABLE_PATHS.values()}
    shown = [entry for entry in entries() if entry["term"] in keys]
    assert shown, "the edit table keys have glossary entries"
    for entry in shown:
        for text in (entry["meaning"], entry.get("meaning_en", ""), entry.get("meaning_ko", "")):
            assert not _VALUE_WITH_UNIT.search(text), (entry["term"], text)
