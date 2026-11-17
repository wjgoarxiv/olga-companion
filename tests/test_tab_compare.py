"""Lane lncompare (todo 9b): read-only comparison of two OLGA .tab tables.

RED-first acceptance tests: identical tables give zero differences, a known
perturbation is found at the right node, grid mismatch falls back to common
nodes, filled/default columns are flagged from validator V017/V019 data, the
comparison never writes, and the report carries ko/en summaries.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from olga_companion import tab_compare
from olga_companion.pvt_engine import generate_table

COLUMNS = [
    "PT", "TM", "ROG", "ROHL", "DROGDP", "DROHLDP", "DROGDT", "DROHLDT", "RS",
    "VISG", "VISHL", "CPG", "CPHL", "HG", "HHL", "TCG", "TCHL", "SIGGHL", "SEG", "SEHL",
]
PROPS = [name for name in COLUMNS if name not in {"PT", "TM"}]


def _engine_table(path: Path, **overrides) -> Path:
    args = dict(
        path=path,
        components=["CO2", "N2"],
        moles=[0.9, 0.1],
        eos="PR",
        pressures_pa=[5e5, 20e5],
        temperatures_c=[0.0, 40.0],
        label="NEUTRAL-COMPARE",
    )
    args.update(overrides)
    generate_table(**args)
    return path


def _perturb_point(text: str, pressure: float, temperature: float, column: str, delta: float) -> str:
    index = COLUMNS.index(column)
    out = []
    for line in text.splitlines(keepends=True):
        match = re.match(r"PVTTABLE POINT = \( ([^)]+) \)", line)
        if match:
            values = [float(token) for token in match.group(1).split(",")]
            if values[0] == pressure and values[1] == temperature:
                values[index] += delta
                line = "PVTTABLE POINT = ( " + ", ".join(format(v, ".10g") for v in values) + " )\n"
        out.append(line)
    return "".join(out)


def test_identical_tables_give_zero_differences(tmp_path: Path) -> None:
    reference = _engine_table(tmp_path / "ref-a.tab")
    candidate = _engine_table(tmp_path / "ref-b.tab")
    report = tab_compare.compare_tables(reference, candidate)
    assert report["compared_nodes"] == 4
    assert report["grid"]["method"] == "exact"
    for name in PROPS:
        column = report["columns"][name]
        if column["relative_nodes"] == 0:
            # A column that is zero everywhere in the reference (here SIGGHL, one gas phase)
            # has no relative difference; it is reported by absolute difference alone.
            assert column["mean_rel_diff"] is None and column["max_rel_diff"] is None
            assert column["zero_reference_max_abs_diff"] == 0.0
        else:
            assert column["mean_rel_diff"] == 0.0
            assert column["max_rel_diff"] == 0.0
    assert report["regions"]["gas_only"]["nodes"] == 4
    assert sum(region["nodes"] for region in report["regions"].values()) == 4


def test_known_perturbation_is_found_at_the_right_node(tmp_path: Path) -> None:
    reference = _engine_table(tmp_path / "ref.tab")
    text = reference.read_text(encoding="utf-8")
    before_rows = tab_compare.read_grid(reference)
    target_p = before_rows["pressures"][1]
    target_t = before_rows["temperatures"][0]
    column = "ROG"
    col_index = COLUMNS.index(column)
    old_value = None
    for row in before_rows["rows"]:
        if row[0] == target_p and row[1] == target_t:
            old_value = row[col_index]
    assert old_value is not None and old_value != 0.0
    candidate = tmp_path / "perturbed.tab"
    candidate.write_text(
        _perturb_point(text, target_p, target_t, column, old_value * 0.05),
        encoding="utf-8",
    )
    report = tab_compare.compare_tables(reference, candidate)
    rog = report["columns"]["ROG"]
    assert rog["max_rel_diff"] == pytest.approx(0.05, rel=0.02)
    assert rog["max_location"]["pressure_pa"] == target_p
    assert rog["max_location"]["temperature_c"] == target_t
    for name in PROPS:
        if name != "ROG":
            # SIGGHL is zero everywhere in this reference: it has no relative difference at all.
            assert (report["columns"][name]["max_rel_diff"] or 0.0) == 0.0


def test_grid_mismatch_compares_common_nodes(tmp_path: Path) -> None:
    reference = _engine_table(tmp_path / "ref.tab")
    candidate = _engine_table(
        tmp_path / "cand.tab",
        temperatures_c=[40.0, 80.0],
        label="NEUTRAL-CAND",
    )
    report = tab_compare.compare_tables(reference, candidate)
    assert report["grid"]["method"] == "common_nodes"
    assert report["compared_nodes"] == 2
    assert report["grid"]["reference_nodes"] == 4
    assert report["grid"]["candidate_nodes"] == 4


def test_disjoint_grids_are_refused(tmp_path: Path) -> None:
    reference = _engine_table(tmp_path / "ref.tab")
    candidate = _engine_table(
        tmp_path / "far.tab",
        pressures_pa=[8e6, 9e6],
        label="NEUTRAL-FAR",
    )
    with pytest.raises(tab_compare.GridMismatchError, match="no common"):
        tab_compare.compare_tables(reference, candidate)


def _keyword_table(path: Path, *, series_value, label: str = "NEUTRAL-FILL") -> Path:
    lines = [
        "! Synthetic keyword table. Numbers are placeholders, not measured fluid properties.",
        f"PVTTABLE LABEL = {label}, PHASE = TWO, \\",
        "COMPONENTS = ( CO2, N2 ), MOLES = ( .8, .2 ), \\",
        "MESHTYPE = STANDARD, \\",
        "PRESSURE = ( 200000, 800000 ) PA, \\",
        "TEMPERATURE = ( 10, 30 ) C, \\",
        "COLUMNS = ( " + ", ".join(COLUMNS) + " )",
    ]
    index = 0
    for pressure in (200000, 800000):
        for temperature in (10, 30):
            values = [float(pressure), float(temperature)]
            values.extend(series_value(name, index) for name in PROPS)
            lines.append("PVTTABLE POINT = ( " + ", ".join(format(v, ".10g") for v in values) + " )")
            index += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _healthy(name: str, index: int) -> float:
    if name in {"RS", "RSW"}:
        return 0.2 + 0.01 * index
    if name.startswith("SIG"):
        return 0.01 + 0.001 * index
    if name.startswith("H") or name.startswith("SE"):
        return -1000.0 - 10.0 * index
    if name.endswith("DT"):
        return -0.02 - 0.001 * index
    return 2.0 + 0.1 * index


def test_filled_node_flag_names_the_column(tmp_path: Path) -> None:
    reference = _keyword_table(
        tmp_path / "filled.tab",
        series_value=lambda name, index: 0.0 if name == "SIGGHL" else _healthy(name, index),
    )
    candidate = _keyword_table(tmp_path / "healthy.tab", series_value=_healthy, label="NEUTRAL-OK")
    report = tab_compare.compare_tables(reference, candidate)
    assert "SIGGHL" in report["filled"]["reference"]
    assert "SIGGHL" not in report["filled"]["candidate"]
    sig = report["columns"]["SIGGHL"]
    assert sig["zero_reference_nodes"] == 4 and sig["max_rel_diff"] is None
    assert sig["zero_reference_max_abs_diff"] > 0.0


def test_compare_is_read_only(tmp_path: Path) -> None:
    reference = _engine_table(tmp_path / "ref.tab")
    candidate = _engine_table(tmp_path / "cand.tab", label="NEUTRAL-CAND")
    before = {
        path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in (reference, candidate)
    }
    tab_compare.compare_tables(reference, candidate)
    for path, snapshot in before.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == snapshot[0]
        assert path.stat().st_mtime_ns == snapshot[1]


def test_report_carries_ko_and_en_summaries(tmp_path: Path) -> None:
    reference = _engine_table(tmp_path / "ref.tab")
    candidate = _engine_table(tmp_path / "cand.tab", label="NEUTRAL-CAND")
    report = tab_compare.compare_tables(reference, candidate)
    assert report["summary_en"].strip()
    assert report["summary_ko"].strip()
    assert re.search(r"[\uac00-\ud7a3]", report["summary_ko"])


def _workspace_tables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    from olga_companion.agent import tools

    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    _engine_table(tmp_path / "owner.tab", label="NEUTRAL-OWNER")
    _engine_table(tmp_path / "engine.tab", label="NEUTRAL-ENGINE")
    return tools.dispatch(
        "fluids_compare_tab",
        {"reference_rel": "owner.tab", "candidate_rel": "engine.tab"},
    )


def test_compare_tool_needs_no_approval_card() -> None:
    from olga_companion.agent import tools

    spec = tools.TOOLS["fluids_compare_tab"]
    assert spec.side_effect is False
    assert "approval_token" not in spec.parameters["properties"]
    assert "approval_token" not in spec.parameters.get("required", [])


def test_compare_tool_returns_columns_and_bilingual_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    out = _workspace_tables(monkeypatch, tmp_path)
    assert out["compared_nodes"] == 4
    assert out["columns"]["ROG"]["max_rel_diff"] == 0.0
    assert out["summary_en"].strip()
    assert re.search(r"[\uac00-\ud7a3]", out["summary_ko"])
    assert out["writes_nothing"] is True


def test_compare_tool_is_read_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    _engine_table(tmp_path / "owner.tab", label="NEUTRAL-OWNER")
    _engine_table(tmp_path / "engine.tab", label="NEUTRAL-ENGINE")
    before = sorted(path.name for path in tmp_path.iterdir())
    digests = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.iterdir() if path.is_file()
    }
    from olga_companion.agent import tools

    tools.dispatch("fluids_compare_tab", {"reference_rel": "owner.tab", "candidate_rel": "engine.tab"})
    assert sorted(path.name for path in tmp_path.iterdir()) == before
    for name, digest in digests.items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest


# --------------------------------------------------------------------- lntabfix

import shutil
import sys

from olga_companion import config


def _grid_table(
    path: Path,
    pressures: list[float],
    temperatures: list[float],
    value,
    *,
    label: str = "NEUTRAL-GRID",
    components: tuple[list[str], list[float]] = (["CO2", "N2"], [0.8, 0.2]),
) -> Path:
    names, moles = components
    lines = [
        "! Synthetic keyword table. Numbers are placeholders, not measured fluid properties.",
        f"PVTTABLE LABEL = {label}, PHASE = TWO, \\",
        f"COMPONENTS = ( {', '.join(names)} ), MOLES = ( {', '.join(str(m) for m in moles)} ), \\",
        "MESHTYPE = STANDARD, \\",
        "PRESSURE = ( " + ", ".join(format(p, ".12g") for p in pressures) + " ) PA, \\",
        "TEMPERATURE = ( " + ", ".join(format(t, ".12g") for t in temperatures) + " ) C, \\",
        "COLUMNS = ( " + ", ".join(COLUMNS) + " )",
    ]
    for pi, pressure in enumerate(pressures):
        for ti, temperature in enumerate(temperatures):
            values = [pressure, temperature]
            values.extend(value(name, pi, ti) for name in PROPS)
            lines.append("PVTTABLE POINT = ( " + ", ".join(format(v, ".12g") for v in values) + " )")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _base(name: str, pi: int, ti: int) -> float:
    return _healthy(name, pi * 7 + ti)


@pytest.fixture
def private_toolkit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway copy of the toolkit scripts and a clean import state, restored afterwards."""
    root = tmp_path / "toolkit"
    shutil.copytree(
        config.toolkit_dir() / "scripts", root / "scripts",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    monkeypatch.setenv("OLGA_TOOLKIT_DIR", str(root))
    monkeypatch.setattr(tab_compare, "_parser_module", None)
    monkeypatch.setattr(tab_compare, "_validator_module", None)
    saved = {name: sys.modules.pop(name, None) for name in ("tab_parser", "tab_validator")}
    yield root
    for name, module in saved.items():
        sys.modules.pop(name, None)
        if module is not None:
            sys.modules[name] = module


def test_comparing_leaves_sys_path_and_the_bytecode_flag_as_they_were(
    private_toolkit: Path, tmp_path: Path
) -> None:
    reference = _engine_table(tmp_path / "ref.tab")
    candidate = _engine_table(tmp_path / "cand.tab", label="NEUTRAL-CAND")
    path_before, flag_before = list(sys.path), sys.dont_write_bytecode

    tab_compare.compare_tables(reference, candidate)
    tab_compare.compare_tables(reference, candidate)

    assert sys.path == path_before
    assert sys.dont_write_bytecode == flag_before


def test_comparing_writes_no_bytecode_into_the_toolkit_folder(private_toolkit: Path, tmp_path: Path) -> None:
    reference = _engine_table(tmp_path / "ref.tab")
    candidate = _engine_table(tmp_path / "cand.tab", label="NEUTRAL-CAND")

    tab_compare.compare_tables(reference, candidate)

    assert not [path for path in private_toolkit.rglob("__pycache__")]
    assert not [path for path in private_toolkit.rglob("*.pyc")]


def test_an_oversized_table_is_refused_before_it_is_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _engine_table(tmp_path / "ref.tab")
    candidate = _engine_table(tmp_path / "cand.tab", label="NEUTRAL-CAND")
    monkeypatch.setattr(tab_compare, "MAX_TAB_BYTES", 64)
    with pytest.raises(tab_compare.GridMismatchError, match="too large"):
        tab_compare.compare_tables(reference, candidate)


def test_the_size_cap_reuses_the_toolkit_input_limit() -> None:
    from olga_companion import genkey_static

    assert tab_compare.MAX_TAB_BYTES == genkey_static.MAX_GENKEY_INPUT_BYTES


def test_a_table_the_parser_cannot_read_is_a_clear_refusal_naming_the_file(tmp_path: Path) -> None:
    reference = _engine_table(tmp_path / "ref.tab")
    broken = tmp_path / "broken.tab"
    broken.write_text(
        "PVTTABLE LABEL = X, PHASE = TWO, \\\nCOMPONENTS = ( CO2 ), MOLES = ( abc ), \\\n"
        "PRESSURE = ( 1, x ) PA, \\\nTEMPERATURE = ( 1 ) C, \\\nCOLUMNS = ( PT, TM )\n",
        encoding="utf-8",
    )
    with pytest.raises(tab_compare.GridMismatchError, match="broken.tab") as caught:
        tab_compare.compare_tables(reference, broken)
    assert str(tmp_path) not in str(caught.value)
    with pytest.raises(tab_compare.GridMismatchError, match="broken.tab"):
        tab_compare.compare_tables(broken, reference)


def test_the_compare_tool_turns_a_parser_failure_into_a_tool_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olga_companion.agent import tools

    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    _engine_table(tmp_path / "owner.tab", label="NEUTRAL-OWNER")
    (tmp_path / "broken.tab").write_text(
        "PVTTABLE LABEL = X, PHASE = TWO, \\\nCOMPONENTS = ( CO2 ), MOLES = ( abc ), \\\n"
        "PRESSURE = ( 1, x ) PA, \\\nTEMPERATURE = ( 1 ) C, \\\nCOLUMNS = ( PT, TM )\n",
        encoding="utf-8",
    )
    with pytest.raises(tools.ToolError, match="broken.tab"):
        tools.dispatch("fluids_compare_tab", {"reference_rel": "owner.tab", "candidate_rel": "broken.tab"})


def _zero_at_first_node(name: str, pi: int, ti: int) -> float:
    return 0.0 if (name == "HG" and pi == 0 and ti == 0) else _base(name, pi, ti)


def test_zero_reference_nodes_stay_out_of_the_relative_mean_and_max(tmp_path: Path) -> None:
    pressures, temperatures = [2e5, 8e5], [10.0, 30.0]
    reference = _grid_table(tmp_path / "ref.tab", pressures, temperatures, _zero_at_first_node)
    candidate = _grid_table(
        tmp_path / "cand.tab", pressures, temperatures,
        lambda name, pi, ti: _base(name, pi, ti) * (1.02 if name == "HG" else 1.0)
        if not (name == "HG" and pi == 0 and ti == 0) else 5.0,
        label="NEUTRAL-CAND",
    )

    hg = tab_compare.compare_tables(reference, candidate)["columns"]["HG"]

    assert hg["nodes"] == 4 and hg["relative_nodes"] == 3
    assert hg["zero_reference_nodes"] == 1
    assert hg["zero_reference_max_abs_diff"] == pytest.approx(5.0)
    assert hg["max_rel_diff"] == pytest.approx(0.02, rel=1e-6)
    assert hg["mean_rel_diff"] == pytest.approx(0.02, rel=1e-6)
    assert (hg["max_location"]["pressure_pa"], hg["max_location"]["temperature_c"]) != (2e5, 10.0)


def test_a_column_that_is_zero_in_the_reference_has_no_relative_statistic(tmp_path: Path) -> None:
    reference = _keyword_table(
        tmp_path / "zero.tab",
        series_value=lambda name, index: 0.0 if name == "SIGGHL" else _healthy(name, index),
    )
    candidate = _keyword_table(tmp_path / "ok.tab", series_value=_healthy, label="NEUTRAL-OK")

    report = tab_compare.compare_tables(reference, candidate)

    sig = report["columns"]["SIGGHL"]
    assert sig["relative_nodes"] == 0 and sig["zero_reference_nodes"] == 4
    assert sig["mean_rel_diff"] is None and sig["max_rel_diff"] is None and sig["max_location"] is None
    assert sig["zero_reference_max_abs_diff"] > 0.0
    assert report["columns"]["ROG"]["max_rel_diff"] == 0.0


def test_the_summary_never_calls_an_absolute_number_relative(tmp_path: Path) -> None:
    reference = _keyword_table(
        tmp_path / "zero.tab",
        series_value=lambda name, index: 0.0 if name == "SIGGHL" else _healthy(name, index),
    )
    candidate = _keyword_table(tmp_path / "ok.tab", series_value=_healthy, label="NEUTRAL-OK")

    report = tab_compare.compare_tables(reference, candidate)

    absolute = f"{report['columns']['SIGGHL']['zero_reference_max_abs_diff']:.3g}"
    for text, word in ((report["summary_en"], "absolute"), (report["summary_ko"], "절대")):
        sentences = [part for part in re.split(r"(?<=[.])\s+", text) if absolute in part]
        assert sentences, (absolute, text)
        assert all(word in part for part in sentences)
        assert all("relative" not in part and "상대" not in part for part in sentences)
    largest = next(part for part in re.split(r"(?<=[.])\s+", report["summary_en"]) if "Largest" in part)
    assert "SIGGHL" not in largest


def test_region_means_leave_out_zero_reference_cells(tmp_path: Path) -> None:
    pressures, temperatures = [2e5, 8e5], [10.0, 30.0]
    reference = _grid_table(tmp_path / "ref.tab", pressures, temperatures, _zero_at_first_node)
    candidate = _grid_table(
        tmp_path / "cand.tab", pressures, temperatures,
        lambda name, pi, ti: 5.0 if (name == "HG" and pi == 0 and ti == 0) else _base(name, pi, ti),
        label="NEUTRAL-CAND",
    )
    regions = tab_compare.compare_tables(reference, candidate)["regions"]
    assert all(region["mean_rel_diff"] == 0.0 for region in regions.values())


def test_the_heat_map_keeps_the_largest_difference_of_each_bin(tmp_path: Path) -> None:
    pressures = [1e5 * (index + 1) for index in range(12)]
    temperatures = [float(index) for index in range(12)]
    reference = _grid_table(tmp_path / "ref.tab", pressures, temperatures, _base)
    candidate = _grid_table(
        tmp_path / "cand.tab", pressures, temperatures,
        lambda name, pi, ti: _base(name, pi, ti) * (1.5 if (name == "HHL" and (pi, ti) == (1, 1)) else 1.0),
        label="NEUTRAL-CAND",
    )

    report = tab_compare.compare_tables(reference, candidate)

    cells = [cell for row in report["heat"]["columns"]["HHL"] for cell in row if cell is not None]
    assert report["columns"]["HHL"]["max_rel_diff"] == pytest.approx(0.5, rel=1e-6)
    assert max(cells) == pytest.approx(0.5, rel=1e-3), "the global peak must be drawn"
    assert len(report["heat"]["pressures_pa"]) == len(report["heat"]["columns"]["HHL"]) <= tab_compare.HEAT_BINS


def test_a_cell_with_nothing_compared_is_null_not_zero(tmp_path: Path) -> None:
    pressures, temperatures = [2e5, 8e5], [10.0, 30.0]
    reference = _grid_table(tmp_path / "ref.tab", pressures, temperatures, _zero_at_first_node)
    candidate = _grid_table(
        tmp_path / "cand.tab", pressures, temperatures,
        lambda name, pi, ti: _base(name, pi, ti) * (1.1 if name == "HG" else 1.0),
        label="NEUTRAL-CAND",
    )

    heat = tab_compare.compare_tables(reference, candidate)["heat"]["columns"]["HG"]

    assert heat[0][0] is None
    assert heat[0][1] == pytest.approx(0.1, rel=1e-3) and heat[1][1] == pytest.approx(0.1, rel=1e-3)


def test_grid_values_that_differ_by_rounding_still_pair_up(tmp_path: Path) -> None:
    pressures, temperatures = [2e5, 8e5], [10.0, 30.0]
    reference = _grid_table(tmp_path / "ref.tab", pressures, temperatures, _base)
    candidate = _grid_table(
        tmp_path / "cand.tab", [p * (1 + 3e-12) for p in pressures], [t + 1e-11 for t in temperatures],
        _base, label="NEUTRAL-CAND",
    )

    report = tab_compare.compare_tables(reference, candidate)

    assert report["compared_nodes"] == 4
    assert report["grid"]["method"] == "exact"
    assert report["columns"]["ROG"]["max_rel_diff"] == pytest.approx(0.0, abs=1e-9)


def test_grid_values_that_really_differ_do_not_pair_up(tmp_path: Path) -> None:
    pressures, temperatures = [2e5, 8e5], [10.0, 30.0]
    reference = _grid_table(tmp_path / "ref.tab", pressures, temperatures, _base)
    candidate = _grid_table(
        tmp_path / "cand.tab", [p * 1.001 for p in pressures], temperatures, _base, label="NEUTRAL-CAND"
    )
    with pytest.raises(tab_compare.GridMismatchError, match="no common"):
        tab_compare.compare_tables(reference, candidate)


def test_different_compositions_are_warned_about_in_the_report_and_both_summaries(tmp_path: Path) -> None:
    pressures, temperatures = [2e5, 8e5], [10.0, 30.0]
    reference = _grid_table(tmp_path / "ref.tab", pressures, temperatures, _base)
    other = _grid_table(
        tmp_path / "other.tab", pressures, temperatures, _base, label="NEUTRAL-OTHER",
        components=(["CO2", "CH4"], [0.8, 0.2]),
    )
    shifted = _grid_table(
        tmp_path / "shifted.tab", pressures, temperatures, _base, label="NEUTRAL-SHIFT",
        components=(["CO2", "N2"], [0.7, 0.3]),
    )

    names = tab_compare.compare_tables(reference, other)
    moles = tab_compare.compare_tables(reference, shifted)

    assert [item["code"] for item in names["warnings"]] == ["components_differ"]
    assert [item["code"] for item in moles["warnings"]] == ["moles_differ"]
    for report in (names, moles):
        assert "composition" in report["summary_en"].casefold()
        assert "조성" in report["summary_ko"]
        assert report["warnings"][0]["message_en"].strip() and report["warnings"][0]["message_ko"].strip()


def test_the_same_composition_gives_no_warning(tmp_path: Path) -> None:
    pressures, temperatures = [2e5, 8e5], [10.0, 30.0]
    reference = _grid_table(tmp_path / "ref.tab", pressures, temperatures, _base)
    candidate = _grid_table(
        tmp_path / "cand.tab", pressures, temperatures, _base, label="NEUTRAL-CAND",
        components=(["N2", "CO2"], [0.2, 0.8]),
    )
    report = tab_compare.compare_tables(reference, candidate)
    assert report["warnings"] == []
    assert "composition" not in report["summary_en"].casefold()


# ------------------------------------------------- Multiflash comparison findings (2026-10-31)

PRESSURES, TEMPERATURES = [2e5, 8e5], [10.0, 30.0]
# Node order: (p0,t0) (p0,t1) (p1,t0) (p1,t1)
RS_REFERENCE = [1.0, 0.5, 0.0, 1.0]  # gas-only, two-phase, liquid-only, gas-only
GAS_COLUMNS = ["ROG", "DROGDP", "DROGDT", "VISG", "CPG", "HG", "TCG", "SEG"]
LIQUID_COLUMNS = ["ROHL", "DROHLDP", "DROHLDT", "VISHL", "CPHL", "HHL", "TCHL", "SEHL"]


def _phase_table(path: Path, rs: list[float], scale=None, *, label: str, components=None) -> Path:
    """A 2x2 table whose RS per node is given; ``scale(name, node)`` multiplies a property."""

    def value(name: str, pi: int, ti: int) -> float:
        node = pi * 2 + ti
        if name == "RS":
            return rs[node]
        factor = scale(name, node) if scale else 1.0
        return _base(name, pi, ti) * factor

    kwargs = {"components": components} if components else {}
    return _grid_table(path, PRESSURES, TEMPERATURES, value, label=label, **kwargs)


def _filled_value_scale(name: str, node: int) -> float:
    """Present-phase differences are small; absent-phase (filled) values differ wildly."""
    if name == "ROG":  # gas absent at node 2 (liquid-only)
        return {0: 1.01, 1: 1.02, 2: 7.11, 3: 1.0}[node]
    if name == "ROHL":  # liquid absent at nodes 0 and 3 (gas-only)
        return {0: 9.0, 1: 1.05, 2: 1.03, 3: 9.0}[node]
    if name == "SIGGHL":  # defined only on the two-phase node 1
        return {0: 5.0, 1: 1.07, 2: 5.0, 3: 5.0}[node]
    return 1.0


def test_component_aliases_do_not_warn_but_a_real_composition_difference_does(tmp_path: Path) -> None:
    reference = _phase_table(
        tmp_path / "ref.tab", RS_REFERENCE, label="NEUTRAL-ALIAS-A",
        components=(["CO2", "PROPANE"], [0.9, 0.1]),
    )
    aliased = _phase_table(
        tmp_path / "alias.tab", RS_REFERENCE, label="NEUTRAL-ALIAS-B",
        components=(['"C3H8"', '"CARBON DIOXIDE"'], [0.1, 0.9]),
    )
    report = tab_compare.compare_tables(reference, aliased)
    assert report["warnings"] == []

    other = _phase_table(
        tmp_path / "other.tab", RS_REFERENCE, label="NEUTRAL-ALIAS-C",
        components=(["CO2", "PROPANE"], [0.8, 0.2]),
    )
    assert [w["code"] for w in tab_compare.compare_tables(reference, other)["warnings"]] == ["moles_differ"]

    different = _phase_table(
        tmp_path / "diff.tab", RS_REFERENCE, label="NEUTRAL-ALIAS-D",
        components=(["CO2", "METHANE"], [0.9, 0.1]),
    )
    assert [w["code"] for w in tab_compare.compare_tables(reference, different)["warnings"]] == [
        "components_differ"
    ]


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ('"C3H8"', "PROPANE"), ("C3", "PROPANE"), ("c1", "METHANE"), ("CH4", "METHANE"),
        ("C2", "ETHANE"), ("IC4", "IC4"), ("I-BUTANE", "IC4"), ("ISOBUTANE", "IC4"),
        ("NC4", "NC4"), ("N-BUTANE", "NC4"), ("BUTANE", "NC4"),
        ("N2", "NITROGEN"), ("CO2", "CARBON DIOXIDE"), ('"carbon dioxide"', "CARBON DIOXIDE"),
        ("H2S", "HYDROGEN SULPHIDE"), ("HYDROGEN SULFIDE", "HYDROGEN SULPHIDE"),
        ("H2O", "WATER"), ("water", "WATER"),
    ],
)
def test_component_names_are_unquoted_and_aliased_before_comparing(alias: str, canonical: str) -> None:
    assert tab_compare.canonical_component(alias) == tab_compare.canonical_component(canonical)


def test_unrelated_components_stay_different() -> None:
    assert tab_compare.canonical_component("PROPANE") != tab_compare.canonical_component("ETHANE")
    assert tab_compare.canonical_component("IC4") != tab_compare.canonical_component("NC4")


def test_mole_fractions_within_the_tolerance_do_not_warn(tmp_path: Path) -> None:
    reference = _phase_table(
        tmp_path / "ref.tab", RS_REFERENCE, label="NEUTRAL-TOL-A",
        components=(["CO2", "PROPANE"], [0.9, 0.1]),
    )
    rounded = _phase_table(
        tmp_path / "round.tab", RS_REFERENCE, label="NEUTRAL-TOL-B",
        components=(["CO2", "PROPANE"], [0.90000000001, 0.09999999999]),
    )
    assert tab_compare.compare_tables(reference, rounded)["warnings"] == []


def test_headline_stats_use_only_the_nodes_where_the_phase_is_present(tmp_path: Path) -> None:
    reference = _phase_table(tmp_path / "ref.tab", RS_REFERENCE, label="NEUTRAL-PH-A")
    candidate = _phase_table(tmp_path / "cand.tab", RS_REFERENCE, _filled_value_scale, label="NEUTRAL-PH-B")
    report = tab_compare.compare_tables(reference, candidate)

    # The all-node figure still carries the absent-phase filled values.
    assert report["columns"]["ROG"]["max_rel_diff"] == pytest.approx(6.11, rel=1e-6)
    assert report["columns"]["ROHL"]["max_rel_diff"] == pytest.approx(8.0, rel=1e-6)

    present = report["present_phase"]
    assert present["basis"] == "RS"
    rog, rohl, sig = present["columns"]["ROG"], present["columns"]["ROHL"], present["columns"]["SIGGHL"]
    assert rog["scope"] == "gas" and rog["nodes"] == 3
    assert rog["max_rel_diff"] == pytest.approx(0.02, rel=1e-6)
    assert rog["mean_rel_diff"] == pytest.approx(0.03 / 3, rel=1e-6)
    assert rohl["scope"] == "liquid" and rohl["nodes"] == 2
    assert rohl["max_rel_diff"] == pytest.approx(0.05, rel=1e-6)
    assert rohl["mean_rel_diff"] == pytest.approx(0.04, rel=1e-6)
    assert sig["scope"] == "two_phase" and sig["nodes"] == 1
    assert sig["max_rel_diff"] == pytest.approx(0.07, rel=1e-6)
    assert sig["max_location"] == {"pressure_pa": 2e5, "temperature_c": 30.0}

    for name in GAS_COLUMNS:
        assert present["columns"][name]["scope"] == "gas"
    for name in LIQUID_COLUMNS:
        assert present["columns"][name]["scope"] == "liquid"
    assert present["columns"]["RS"]["scope"] == "all" and present["columns"]["RS"]["nodes"] == 4

    headline = present["headline"]
    assert headline["column"] == "SIGGHL"
    assert headline["max_rel_diff"] == pytest.approx(0.07, rel=1e-6)


def test_summary_leads_with_the_present_phase_figure_and_labels_the_all_node_line(tmp_path: Path) -> None:
    reference = _phase_table(tmp_path / "ref.tab", RS_REFERENCE, label="NEUTRAL-SUM-A")
    candidate = _phase_table(tmp_path / "cand.tab", RS_REFERENCE, _filled_value_scale, label="NEUTRAL-SUM-B")
    report = tab_compare.compare_tables(reference, candidate)

    en, ko = report["summary_en"], report["summary_ko"]
    assert "SIGGHL 0.07" in en and "SIGGHL 0.07" in ko
    assert "including filled values" in en
    assert "채움값 포함" in ko
    assert en.index("SIGGHL 0.07") < en.index("including filled values")
    assert ko.index("SIGGHL 0.07") < ko.index("채움값 포함")
    after = en[en.index("including filled values"):]
    assert "ROHL 8" in after  # the all-node peak survives, as the secondary line
    assert "ROHL 8" not in en[: en.index("including filled values")]


def test_a_node_where_the_phase_labels_disagree_is_listed(tmp_path: Path) -> None:
    reference = _phase_table(tmp_path / "ref.tab", RS_REFERENCE, label="NEUTRAL-DIS-A")
    # node 0 gas vs liquid; node 1 same; node 2 same; node 3 gas vs two-phase.
    candidate = _phase_table(tmp_path / "cand.tab", [0.0, 0.5, 0.0, 0.4], label="NEUTRAL-DIS-B")
    report = tab_compare.compare_tables(reference, candidate)

    disagreement = report["phase_disagreement"]
    assert disagreement["basis"] == "RS"
    assert disagreement["count"] == 2
    assert disagreement["nodes"] == [
        {"pressure_pa": 2e5, "temperature_c": 10.0, "reference": "gas_only", "candidate": "liquid_only"},
        {"pressure_pa": 8e5, "temperature_c": 30.0, "reference": "gas_only", "candidate": "two_phase"},
    ]
    assert "2 node(s)" in report["summary_en"] and "phase label" in report["summary_en"]
    assert "2개 노드" in report["summary_ko"] and "상 구분" in report["summary_ko"]
    assert "P=200000 Pa, T=10 C" in report["summary_en"]


def test_agreeing_phase_labels_report_none(tmp_path: Path) -> None:
    reference = _phase_table(tmp_path / "ref.tab", RS_REFERENCE, label="NEUTRAL-AGR-A")
    candidate = _phase_table(tmp_path / "cand.tab", RS_REFERENCE, label="NEUTRAL-AGR-B")
    report = tab_compare.compare_tables(reference, candidate)
    assert report["phase_disagreement"]["count"] == 0
    assert report["phase_disagreement"]["nodes"] == []
    assert "phase label" not in report["summary_en"]


def test_the_phase_disagreement_list_is_capped_but_the_count_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tab_compare, "MAX_LISTED_DISAGREEMENTS", 1)
    reference = _phase_table(tmp_path / "ref.tab", RS_REFERENCE, label="NEUTRAL-CAP-A")
    candidate = _phase_table(tmp_path / "cand.tab", [0.0, 0.5, 0.0, 0.4], label="NEUTRAL-CAP-B")
    disagreement = tab_compare.compare_tables(reference, candidate)["phase_disagreement"]
    assert disagreement["count"] == 2
    assert len(disagreement["nodes"]) == 1
    assert disagreement["truncated"] is True
