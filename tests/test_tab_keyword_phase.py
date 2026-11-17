"""Keyword STANDARD tables: PHASE=TWO and PHASE=THREE, columns, grid, filled nodes."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from olga_companion import fluids

FIXTURES = Path(__file__).parent / "fixtures" / "fluids"
KEYWORD_TWO = FIXTURES / "keyword_two.tab"
KEYWORD_THREE = FIXTURES / "keyword_three.tab"
STANDARD_THREE = FIXTURES / "standard_three.tab"

TWO_COLUMNS = [
    "PT", "TM", "ROG", "ROHL", "DROGDP", "DROHLDP", "DROGDT", "DROHLDT", "RS",
    "VISG", "VISHL", "CPG", "CPHL", "HG", "HHL", "TCG", "TCHL", "SIGGHL", "SEG", "SEHL",
]


@pytest.fixture
def toolkit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    scripts = Path(fluids.fluids_toolkit_status()["toolkit_dir"]) / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return tuple(importlib.import_module(name) for name in (
        "tab_parser", "tab_validator", "tab_summarizer",
    ))


def _fmt(value: float) -> str:
    if float(value).is_integer() and abs(value) >= 1:
        return str(int(value))
    return format(value, ".16g")


def _neutral_series(names: list[str], count: int) -> dict[str, list[float]]:
    series = {}
    for name in names:
        if name in {"RS", "RSW"}:
            series[name] = [0.2 + 0.01 * index for index in range(count)]
        elif name.startswith("SIG"):
            series[name] = [0.01 + 0.001 * index for index in range(count)]
        elif name.startswith("H") or name.startswith("SE"):
            series[name] = [-1000.0 - 10.0 * index for index in range(count)]
        elif name.endswith("DT"):
            series[name] = [-0.02 - 0.001 * index for index in range(count)]
        else:
            series[name] = [2.0 + 0.1 * index for index in range(count)]
    return series


def _keyword_table(
    path: Path,
    *,
    phase: str = "TWO",
    columns: list[str] | None = None,
    pressures: list[float] | None = None,
    temperatures: list[float] | None = None,
    series: dict[str, list[float]] | None = None,
    water: str | None = None,
    pressure_unit: str = "PA",
    temperature_unit: str = "C",
    nopres: str | None = None,
    notemp: str | None = None,
    extra_header: str = "",
) -> Path:
    columns = list(columns or TWO_COLUMNS)
    pressures = list(pressures or [200000, 800000])
    temperatures = list(temperatures or [10, 30])
    props = [name for name in columns if name not in {"PT", "TM"}]
    count = len(pressures) * len(temperatures)
    if series is None:
        series = _neutral_series(props, count)
    mesh = "MESHTYPE = STANDARD"
    if water is not None:
        mesh += f", TOTWATERFRACTION = ( {water} )"
    counts = ""
    if nopres is not None or notemp is not None:
        parts = []
        if nopres is not None:
            parts.append(f"NOPRES = ( {nopres} )")
        if notemp is not None:
            parts.append(f"NOTEMP = ( {notemp} )")
        counts = ", ".join(parts) + ", \\\n"
    lines = [
        f'PVTTABLE LABEL = "NEUTRAL-{phase}",PHASE = {phase}, \\',
        "! Synthetic keyword table. Numbers are placeholders, not measured fluid properties.",
        "! Independent table shape reference; not Multiflash output.",
        'EOS = "PR Peneloux", \\',
        'COMPONENTS = ( "CO2", "N2" ), MOLES = ( .8, .2 ), \\',
        "MOLWEIGHT = ( 44.009, 28.014 ) g/mol, \\",
        "DENSITY = ( 0, 0 ) g/cm3, \\",
        "STDPRESSURE = 1 ATM, \\",
        "STDTEMPERATURE = 288.15 K, \\",
        "GOR = -999 Sm3/Sm3, \\",
        "GLR = -999 Sm3/Sm3, \\",
        "STDGASDENSITY = 1.66 kg/m3, \\",
        "STDOILDENSITY = 0 kg/m3, \\",
        *([extra_header] if extra_header else []),
        mesh + ", \\",
        counts + f"PRESSURE = ( {', '.join(_fmt(p) for p in pressures)} ) {pressure_unit}, \\",
        f"TEMPERATURE = ( {', '.join(_fmt(t) for t in temperatures)} ) {temperature_unit}, \\",
        f"BUBBLEPRESSURES = ( {', '.join(['1E10'] * len(temperatures))} ) PA, \\",
        f"BUBBLETEMPERATURES = ( {', '.join(_fmt(t) for t in temperatures)} ) C, \\",
        "COLUMNS = ( " + ", ".join(columns) + " )",
    ]
    index = 0
    for pressure in pressures:
        for temperature in temperatures:
            values = [_fmt(pressure), _fmt(temperature)]
            values.extend(_fmt(series[name][index]) for name in props)
            lines.append("PVTTABLE POINT = ( " + ", ".join(values) + " )")
            index += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _errors(report: dict) -> list[dict]:
    return report["errors"]


def _text(findings: list[dict]) -> str:
    return "\n".join(
        f"{item['rule_id']} {item['message']} {item.get('location', '')}"
        for item in findings
    )


def test_two_phase_standard_keyword_table_is_accepted(toolkit) -> None:
    parser_module, validator_module, summary_module = toolkit
    parsed = parser_module.TabParser(KEYWORD_TWO)
    report = validator_module.TabValidator(KEYWORD_TWO).validate()
    assert parsed.phase == "TWO"
    assert parsed.formulation == "PT"
    assert parsed.columns == TWO_COLUMNS
    assert parsed.pressure_grid == [200000, 800000]
    assert parsed.temperature_grid == [10, 30]
    assert len(parsed.point_rows) == 4
    assert report["errors"] == []
    assert report["warnings"] == []
    summary = summary_module.TabSummarizer(KEYWORD_TWO).summarize()
    assert "Phase:        TWO" in summary


def test_three_phase_standard_keyword_table_is_accepted(toolkit) -> None:
    parser_module, validator_module, _ = toolkit
    parsed = parser_module.TabParser(KEYWORD_THREE)
    report = validator_module.TabValidator(KEYWORD_THREE).validate()
    assert parsed.phase == "THREE"
    assert "ROWT" in parsed.columns
    assert "RSW" in parsed.columns
    assert "SIGHLWT" in parsed.columns
    assert report["errors"] == []
    assert report["warnings"] == []


def test_existing_three_phase_fixture_keeps_a_clean_report(toolkit) -> None:
    _, validator_module, _ = toolkit
    report = validator_module.TabValidator(STANDARD_THREE).validate()
    assert report["errors"] == []
    assert report["warnings"] == []


def test_phase_two_label_on_a_water_table_stays_rejected(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    report = validator_module.TabValidator(STANDARD_THREE).validate()
    assert report["errors"] == []
    text = STANDARD_THREE.read_text(encoding="utf-8").replace("PHASE = THREE", "PHASE = TWO", 1)
    path = tmp_path / "phase-swap-check.tab"
    path.write_text(text, encoding="utf-8")
    swapped = validator_module.TabValidator(path).validate()
    assert swapped["errors"]


def test_missing_density_column_names_the_column(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    columns = [name for name in TWO_COLUMNS if name != "ROG"]
    path = _keyword_table(tmp_path / "missing-rog.tab", columns=columns)
    report = validator_module.TabValidator(path).validate()
    assert any(
        item["rule_id"] == "V006" and "ROG" in item["message"]
        for item in _errors(report)
    )


def test_unknown_column_is_rejected_with_its_name(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    columns = TWO_COLUMNS + ["NOT_A_COLUMN"]
    path = _keyword_table(tmp_path / "unknown-column.tab", columns=columns)
    report = validator_module.TabValidator(path).validate()
    assert any(
        item["rule_id"] == "V012" and "NOT_A_COLUMN" in item["message"]
        for item in _errors(report)
    )


def test_wrong_pressure_unit_names_the_required_unit(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    path = _keyword_table(tmp_path / "bar-pressure.tab", pressure_unit="BAR")
    report = validator_module.TabValidator(path).validate()
    detail = " ".join(item["message"].split(":", 1)[-1] for item in _errors(report)).upper()
    assert "PRESSURE" in detail and "PA" in detail


def test_wrong_temperature_unit_names_the_required_unit(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    path = _keyword_table(tmp_path / "fahrenheit.tab", temperature_unit="F")
    report = validator_module.TabValidator(path).validate()
    text = _text(_errors(report)).upper()
    assert "TEMPERATURE" in text
    assert " C" in f" {text} " or text.endswith(" C") or "EXPLICIT C" in text


def test_nopres_must_match_the_pressure_grid(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    path = _keyword_table(tmp_path / "bad-nopres.tab", nopres="2")
    report = validator_module.TabValidator(path).validate()
    matched = [
        item for item in _errors(report)
        if item["rule_id"] == "V032" and "NOPRES" in item["message"]
    ]
    assert matched
    assert matched[0]["location"] == "NOPRES"
    assert not [
        item for item in _errors(report)
        if item["rule_id"] == "V014" and "NOPRES" in item["message"]
    ]


def test_notemp_must_match_the_temperature_grid(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    path = _keyword_table(tmp_path / "bad-notemp.tab", notemp="2")
    report = validator_module.TabValidator(path).validate()
    matched = [
        item for item in _errors(report)
        if item["rule_id"] == "V032" and "NOTEMP" in item["message"]
    ]
    assert matched
    assert matched[0]["location"] == "NOTEMP"
    assert not [
        item for item in _errors(report)
        if item["rule_id"] == "V014" and "NOTEMP" in item["message"]
    ]


def test_grid_count_mismatch_is_still_a_v014_error(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    path = _keyword_table(tmp_path / "bad-notemp-count.tab", notemp="5")
    report = validator_module.TabValidator(path).validate()
    matched = [
        item for item in _errors(report)
        if item["rule_id"] == "V014" and "NOTEMP" in item["message"]
    ]
    assert matched
    assert "5" in matched[0]["message"] and "2" in matched[0]["message"]
    assert matched[0]["location"]


def test_water_column_is_rejected_when_phase_is_two(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    columns = TWO_COLUMNS + ["ROWT"]
    path = _keyword_table(tmp_path / "water-on-two.tab", columns=columns)
    report = validator_module.TabValidator(path).validate()
    assert any(
        item["rule_id"] == "V012" and "ROWT" in item["message"] and "TWO" in item["message"]
        for item in _errors(report)
    )


def test_nonzero_water_fraction_is_rejected_when_phase_is_two(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    path = _keyword_table(tmp_path / "water-fraction.tab", water=".4")
    report = validator_module.TabValidator(path).validate()
    text = _text(_errors(report))
    assert "TOTWATERFRACTION" in text


def test_zero_water_fraction_is_accepted_on_phase_two(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    path = _keyword_table(tmp_path / "dry-fraction.tab", water="0")
    report = validator_module.TabValidator(path).validate()
    assert report["errors"] == []
    assert report["warnings"] == []


def test_gas_water_fraction_column_is_allowed_on_phase_two(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    columns = TWO_COLUMNS[:9] + ["RSW"] + TWO_COLUMNS[9:]
    path = _keyword_table(tmp_path / "rsw-two.tab", columns=columns)
    report = validator_module.TabValidator(path).validate()
    assert report["errors"] == []
    assert report["warnings"] == []


def test_zero_node_is_a_warning_with_its_location(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    series = _neutral_series([name for name in TWO_COLUMNS if name not in {"PT", "TM"}], 4)
    series["ROG"] = [0, 4.2, 4.3, 4.4]
    path = _keyword_table(tmp_path / "zero-rog.tab", series=series)
    report = validator_module.TabValidator(path).validate()
    assert any(
        item["rule_id"] == "V020" and "ROG" in item["message"] and "density" in item["message"]
        for item in report["errors"]
    )
    matched = [item for item in report["warnings"] if item["rule_id"] == "V017"]
    assert len(matched) == 1
    blob = _text(matched)
    assert "ROG" in blob
    assert "200000" in blob and "10" in blob
    assert matched[0]["location"]


def test_stepped_node_is_a_warning_with_its_location(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    temperatures = [10, 20, 30]
    props = [name for name in TWO_COLUMNS if name not in {"PT", "TM"}]
    series = _neutral_series(props, 6)
    series["ROG"] = [5, 5, 40, 6, 7, 8]
    path = _keyword_table(
        tmp_path / "stepped-rog.tab",
        temperatures=temperatures,
        series=series,
    )
    report = validator_module.TabValidator(path).validate()
    assert report["errors"] == []
    matched = [item for item in report["warnings"] if item["rule_id"] == "V018"]
    assert len(matched) == 1
    blob = _text(matched)
    assert "ROG" in blob
    assert "200000" in blob and "30" in blob
    assert "5" in blob and "40" in blob
    assert matched[0]["location"]


def test_default_filled_column_is_a_warning_with_its_location(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    series = _neutral_series([name for name in TWO_COLUMNS if name not in {"PT", "TM"}], 4)
    series["ROG"] = [1, 1, 1, 1]
    path = _keyword_table(tmp_path / "default-rog.tab", series=series)
    report = validator_module.TabValidator(path).validate()
    assert report["errors"] == []
    matched = [item for item in report["warnings"] if item["rule_id"] == "V019"]
    assert len(matched) == 1
    blob = _text(matched)
    assert "ROG" in blob
    assert "200000" in blob
    assert matched[0]["location"]


@pytest.mark.parametrize(
    ("column", "values", "snippet"),
    [
        ("ROG", [-1524.9, 4.2, 4.3, 4.4], "density"),
        ("ROHL", [-1, 660, 670, 680], "density"),
        ("VISG", [-1e-5, 1.7e-5, 1.8e-5, 1.9e-5], "viscosity"),
        ("CPG", [0, 1410, 1420, 1430], "heat capacity"),
        ("TCG", [0, 0.032, 0.033, 0.034], "thermal conductivity"),
        ("SIGGHL", [-0.02, 0.0082, 0.0083, 0.0084], "surface tension"),
        ("RS", [1.1, 0.22, 0.23, 0.24], "mass fraction"),
        ("HG", [7.5e167, -11000, -10000, -9000], "1e30"),
    ],
)
def test_impossible_property_values_are_errors(
    toolkit, tmp_path: Path, column: str, values: list[float], snippet: str,
) -> None:
    _, validator_module, _ = toolkit
    props = [name for name in TWO_COLUMNS if name not in {"PT", "TM"}]
    series = _neutral_series(props, 4)
    series[column] = values
    path = _keyword_table(tmp_path / f"bad-{column}.tab", series=series)
    report = validator_module.TabValidator(path).validate()
    matched = [
        item for item in report["errors"]
        if item["rule_id"] == "V020" and column in item["message"] and snippet in item["message"]
    ]
    assert matched
    assert matched[0]["location"]
    assert "200000" in matched[0]["location"]


def test_mass_fraction_inside_tolerance_is_accepted(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    props = [name for name in TWO_COLUMNS if name not in {"PT", "TM"}]
    series = _neutral_series(props, 4)
    series["RS"] = [1 + 1e-12, -1e-12, 0.23, 1.0]
    path = _keyword_table(tmp_path / "rs-tolerance.tab", series=series)
    report = validator_module.TabValidator(path).validate()
    assert report["errors"] == []


def test_mass_fraction_just_outside_tolerance_is_an_error(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    props = [name for name in TWO_COLUMNS if name not in {"PT", "TM"}]
    series = _neutral_series(props, 4)
    series["RS"] = [1 + 2e-9, 0.22, 0.23, 0.24]
    path = _keyword_table(tmp_path / "rs-over.tab", series=series)
    report = validator_module.TabValidator(path).validate()
    assert any(
        item["rule_id"] == "V020" and "RS" in item["message"]
        for item in report["errors"]
    )


def test_zero_viscosity_is_an_error_and_a_zero_warning(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    props = [name for name in TWO_COLUMNS if name not in {"PT", "TM"}]
    series = _neutral_series(props, 4)
    series["VISG"] = [0, 1.7e-5, 1.8e-5, 1.9e-5]
    path = _keyword_table(tmp_path / "zero-visg.tab", series=series)
    report = validator_module.TabValidator(path).validate()
    assert any(item["rule_id"] == "V020" and "VISG" in item["message"] for item in report["errors"])
    assert any(item["rule_id"] == "V017" and "VISG" in item["location"] for item in report["warnings"])


def test_zero_surface_tension_stays_a_warning(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    props = [name for name in TWO_COLUMNS if name not in {"PT", "TM"}]
    series = _neutral_series(props, 4)
    series["SIGGHL"] = [0, 0.0082, 0.0083, 0.0084]
    path = _keyword_table(tmp_path / "zero-sig.tab", series=series)
    report = validator_module.TabValidator(path).validate()
    assert report["errors"] == []
    assert any(item["rule_id"] == "V017" and "SIGGHL" in item["location"] for item in report["warnings"])


def test_zero_critical_pressure_and_temperature_are_errors(toolkit, tmp_path: Path) -> None:
    _, validator_module, _ = toolkit
    path = _keyword_table(
        tmp_path / "zero-critical.tab",
        extra_header="CRITICALPRESSURE = 0.0 ATM, \\\nCRITICALTEMPERATURE = 0.0 K, \\",
    )
    report = validator_module.TabValidator(path).validate()
    text = _text(report["errors"])
    assert "V021" in text
    assert "CRITICALPRESSURE" in text
    assert "CRITICALTEMPERATURE" in text


def test_legacy_ph_table_is_not_judged_by_keyword_column_rules(toolkit) -> None:
    _, validator_module, _ = toolkit
    report = validator_module.TabValidator(FIXTURES / "fluid.tab").validate()
    assert report["errors"] == []
    assert all(item["rule_id"] not in {"V012", "V014", "V017", "V018", "V019"} for item in report["warnings"])
