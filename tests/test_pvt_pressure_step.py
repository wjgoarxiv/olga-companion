"""L8 RED: a large boundary/start pressure step warns before the run approval.

The 5 bar source / 2 bar sink template aborts on PRESSURE ABOVE TABLE
VALUES even with a stated 2 bar start, and nothing warns at run approval
today. The 2.4/2.0/2.2 bar variant runs clean and must stay silent.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from olga_companion import pvt_range, workspace
from olga_companion.agent import approvals, approval_display, tools

TAB_LABEL = "NEUTRAL-RANGE"
TAB_NAME = "range.tab"

_TAB_COLUMNS = (
    "PT", "TM", "ROG", "ROHL", "DROGDP", "DROHLDP", "DROGDT", "DROHLDT",
    "RS", "VISG", "VISHL", "CPG", "CPHL", "HG", "HHL", "TCG", "TCHL",
    "SIGGHL", "SEG", "SEHL",
)


def make_tab(pressures_pa: list[float], temps_c: list[float]) -> str:
    filler = [4.0, 650.0, 2e-6, 3e-7, -0.02, -0.4, 0.2, 1.6e-5, 2.1e-4,
              1400.0, 2300.0, -12000.0, -80000.0, 0.03, 0.15, 0.008, 400.0, -200.0]
    points = [
        "PVTTABLE POINT = ( " + ", ".join(repr(v) for v in [p, t, *filler]) + " )"
        for p in pressures_pa for t in temps_c
    ]
    return "\n".join([
        f'PVTTABLE LABEL = "{TAB_LABEL}",PHASE = TWO,',
        "! Neutral range fixture. Numbers are placeholders, not measured properties.",
        'EOS = "PR Peneloux",',
        'COMPONENTS = ( "CO2", "N2" ), MOLES = ( .8, .2 ),',
        "MOLWEIGHT = ( 44.009, 28.014 ) g/mol,",
        "DENSITY = ( 0, 0 ) g/cm3,",
        "STDPRESSURE = 1 ATM,",
        "STDTEMPERATURE = 288.15 K,",
        "GOR = -999 Sm3/Sm3,",
        "GLR = -999 Sm3/Sm3,",
        "STDGASDENSITY = 1.66 kg/m3,",
        "STDOILDENSITY = 0 kg/m3,",
        "MESHTYPE = STANDARD,",
        f"PRESSURE = ( {', '.join(repr(p) for p in pressures_pa)} ) PA,",
        f"TEMPERATURE = ( {', '.join(repr(t) for t in temps_c)} ) C,",
        "BUBBLEPRESSURES = ( 1E10, 1E10 ) PA,",
        f"BUBBLETEMPERATURES = ( {', '.join(repr(t) for t in temps_c)} ) C,",
        f"COLUMNS = ( {', '.join(_TAB_COLUMNS)} )",
        *points,
        "",
    ])


def make_case(inlet_pressure: str, outlet_pressure: str, start_pressure_pa: float) -> str:
    return "\n".join([
        "OPTIONS STEADYSTATE=ON, COMPOSITIONAL=OFF, FLOWMODEL=OLGAHD",
        'CASE AUTHOR=T, PROJECT=T, TITLE="Pressure step check"',
        f'FILES PVTFILE="./{TAB_NAME}"',
        "INTEGRATION ENDTIME=1 h",
        "NETWORKCOMPONENT TYPE=FLOWPATH, TAG=MAIN",
        ' PARAMETERS LABEL="Main"',
        f' BRANCH FLUID="{TAB_LABEL}"',
        f" INITIALCONDITIONS PRESSURE={start_pressure_pa:g} Pa, TEMPERATURE=25 C, VOIDFRACTION=1",
        ' GEOMETRY LABEL="G-MAIN", XSTART=0 m, YSTART=0 m, ZSTART=0 m',
        " PIPE LABEL=Pipe_1, ROUGHNESS=0.00005 m, NSEGMENT=2,",
        "        LSEGMENT=(50, 50) m, XEND=100 m, YEND=0 m, ZEND=0 m, DIAMETER=0.2 m",
        "ENDNETWORKCOMPONENT",
        "NETWORKCOMPONENT TYPE=NODE, TAG=INLET",
        f' PARAMETERS LABEL="Inlet", TYPE=PRESSURE, X=0 m, Y=0 m, Z=0 m, PRESSURE={inlet_pressure}, TEMPERATURE=25 C, TIME=0 s, FLUID="{TAB_LABEL}"',
        "ENDNETWORKCOMPONENT",
        "NETWORKCOMPONENT TYPE=NODE, TAG=OUTLET",
        f' PARAMETERS LABEL="Outlet", TYPE=PRESSURE, X=100 m, Y=0 m, Z=0 m, PRESSURE={outlet_pressure}, TEMPERATURE=25 C, TIME=0 s, FLUID="{TAB_LABEL}"',
        "ENDNETWORKCOMPONENT",
        "CONNECTION TERMINALS = (INLET FLOWTERM_1, MAIN INLET)",
        "CONNECTION TERMINALS = (OUTLET FLOWTERM_1, MAIN OUTLET)",
        "ENDCASE",
        "",
    ])


def _write_workspace(
    tmp_path: Path, monkeypatch: Any, case_text: str,
    pressures_pa: list[float] | None = None, temps_c: list[float] | None = None,
) -> Path:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / TAB_NAME).write_text(
        make_tab(pressures_pa or [100_000.0, 10_000_000.0], temps_c or [0.0, 50.0]),
        encoding="utf-8",
    )
    case = tmp_path / "case.genkey"
    case.write_text(case_text, encoding="utf-8")
    return case


def _display(case: Path, selection_id: str = "selection_exact", locale: str = "ko") -> dict[str, Any]:
    def preview(value: str, timeout: int) -> dict[str, Any]:
        return {
            "source": value,
            "selection_id": selection_id,
            "runtime_id": "olga-2022.1",
            "detection": {"exe": r"C:\OLGA\OLGA-2022.1.0.exe"},
            "timeout_s": timeout,
            "context_generation": 0,
        }

    class Paths:
        def input_file(self, value: str, suffixes: set[str]) -> Path:
            assert suffixes == {".genkey"}
            return Path(value)

    return approval_display.build(
        "run_execute",
        {"source": str(case), "selection_id": selection_id, "timeout_s": 45},
        Paths(),  # type: ignore[arg-type]
        preview,
        locale,
    )


HANGUL = re.compile(r"[\uac00-\ud7a3]")


def test_large_boundary_start_step_warns_before_approval(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    case = _write_workspace(
        tmp_path, monkeypatch,
        make_case("5 bara", "2 bara", start_pressure_pa=200_000.0),
    )
    warnings = pvt_range.pressure_step_warnings(case)
    assert len(warnings) == 1
    assert "5 bar" in warnings[0] and "2 bar" in warnings[0]
    assert HANGUL.search(warnings[0])
    assert "temperature range" in warnings[0]
    assert "온도 범위" in warnings[0]


def test_small_step_stays_silent(tmp_path: Path, monkeypatch: Any) -> None:
    case = _write_workspace(
        tmp_path, monkeypatch,
        make_case("2.4 bara", "2 bara", start_pressure_pa=220_000.0),
    )
    assert pvt_range.pressure_step_warnings(case) == []


def test_run_approval_display_carries_the_warning(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    case = _write_workspace(
        tmp_path, monkeypatch,
        make_case("5 bara", "2 bara", start_pressure_pa=200_000.0),
    )
    display = _display(case)
    assert len(display["warnings"]) == 1
    assert "5 bar" in display["warnings"][0]


def test_run_approval_display_omits_warnings_when_quiet(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    case = _write_workspace(
        tmp_path, monkeypatch,
        make_case("2.4 bara", "2 bara", start_pressure_pa=220_000.0),
    )
    assert "warnings" not in _display(case)


def test_unreadable_case_warns_nothing(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    missing = tmp_path / "absent.genkey"
    assert pvt_range.pressure_step_warnings(missing) == []


def test_inside_wide_grid_large_step_stays_silent(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    case = _write_workspace(
        tmp_path, monkeypatch,
        make_case("75 bara", "15 bara", start_pressure_pa=1_500_000.0),
        pressures_pa=[100_000.0, 10_000_000.0],
        temps_c=[0.0, 100.0],
    )
    assert pvt_range.pressure_step_warnings(case) == []


def test_threshold_boundary_matches_the_import_rule(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    exact = _write_workspace(
        tmp_path, monkeypatch,
        make_case("3 bara", "2 bara", start_pressure_pa=200_000.0),
    )
    assert pvt_range.pressure_step_warnings(exact) == []
    above = _write_workspace(
        tmp_path, monkeypatch,
        make_case("3.1 bara", "2 bara", start_pressure_pa=200_000.0),
    )
    assert len(pvt_range.pressure_step_warnings(above)) == 1


def test_missing_table_warns_on_ratio(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case_text = make_case("5 bara", "2 bara", start_pressure_pa=200_000.0)
    case = tmp_path / "case.genkey"
    case.write_text(
        case_text.replace('FILES PVTFILE="./range.tab"', 'FILES PVTFILE="./absent.tab"'),
        encoding="utf-8",
    )
    warnings = pvt_range.pressure_step_warnings(case)
    assert len(warnings) == 1
    assert "5 bar" in warnings[0] and "2 bar" in warnings[0]


def test_outside_extreme_warns(tmp_path: Path, monkeypatch: Any) -> None:
    case = _write_workspace(
        tmp_path, monkeypatch,
        make_case("150 bara", "15 bara", start_pressure_pa=1_500_000.0),
    )
    assert len(pvt_range.pressure_step_warnings(case)) == 1


def test_toolbox_failure_warns_nothing(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise TypeError("toolbox exploded")

    monkeypatch.setattr(pvt_range.genkey_static, "run_tool", boom)
    assert pvt_range.pressure_step_warnings(tmp_path / "case.genkey") == []


def test_run_approval_warning_reads_in_the_ui_language(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    case = _write_workspace(
        tmp_path, monkeypatch,
        make_case("5 bara", "2 bara", start_pressure_pa=200_000.0),
    )
    korean = _display(case, locale="ko")["warnings"][0]
    english = _display(case, locale="en")["warnings"][0]
    assert HANGUL.search(korean) and "Large pressure step" not in korean
    assert "5 bar" in korean and "온도 범위" in korean
    assert not HANGUL.search(english) and "Large pressure step" in english
