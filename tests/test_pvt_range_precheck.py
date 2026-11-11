"""PVT range precheck: a case must not run when its pressures or temperatures
leave the linked .tab grid (found in the installed app, 2026-10-31).

RED first: every test below fails before the precheck exists.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from olga_companion import workspace
from olga_companion.agent import approvals, plan_execution, plan_progress, tools


TAB_LABEL = "NEUTRAL-RANGE"
TAB_NAME = "range.tab"

_TAB_COLUMNS = (
    "PT", "TM", "ROG", "ROHL", "DROGDP", "DROHLDP", "DROGDT", "DROHLDT",
    "RS", "VISG", "VISHL", "CPG", "CPHL", "HG", "HHL", "TCG", "TCHL",
    "SIGGHL", "SEG", "SEHL",
)


def make_tab(pressures_pa: list[float], temps_c: list[float], label: str = TAB_LABEL) -> str:
    """A neutral STANDARD keyword table; grids only, placeholder properties."""
    points: list[str] = []
    filler = [4.0, 650.0, 2e-6, 3e-7, -0.02, -0.4, 0.2, 1.6e-5, 2.1e-4,
              1400.0, 2300.0, -12000.0, -80000.0, 0.03, 0.15, 0.008, 400.0, -200.0]
    for pressure in pressures_pa:
        for temp in temps_c:
            values = [pressure, temp, *filler]
            points.append(
                "PVTTABLE POINT = ( " + ", ".join(repr(v) for v in values) + " )"
            )
    return "\n".join([
        f'PVTTABLE LABEL = "{label}",PHASE = TWO,',
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


def make_case(
    outlet_pressure: str = "30 bara",
    outlet_temp: str = "15 C",
    inlet_pressure: str = "50 bara",
    inlet_temp: str = "20 C",
    pvtfile: str | None = "./range.tab",
) -> str:
    """A neutral two-node pipeline case."""
    files = f'FILES PVTFILE="{pvtfile}"\n' if pvtfile is not None else ""
    return "\n".join([
        "OPTIONS STEADYSTATE=ON, COMPOSITIONAL=OFF, FLOWMODEL=OLGAHD",
        'CASE AUTHOR=T, PROJECT=T, TITLE="Range check"',
        files.rstrip("\n"),
        "INTEGRATION ENDTIME=1 h",
        "NETWORKCOMPONENT TYPE=FLOWPATH, TAG=MAIN",
        ' PARAMETERS LABEL="Main"',
        f' BRANCH FLUID="{TAB_LABEL}"',
        ' GEOMETRY LABEL="G-MAIN", XSTART=0 m, YSTART=0 m, ZSTART=0 m',
        " PIPE LABEL=Pipe_1, ROUGHNESS=0.00005 m, NSEGMENT=2,",
        "        LSEGMENT=(50, 50) m, XEND=100 m, YEND=0 m, ZEND=0 m, DIAMETER=0.2 m",
        "ENDNETWORKCOMPONENT",
        "NETWORKCOMPONENT TYPE=NODE, TAG=INLET",
        f' PARAMETERS LABEL="Inlet", TYPE=PRESSURE, X=0 m, Y=0 m, Z=0 m, PRESSURE={inlet_pressure}, TEMPERATURE={inlet_temp}, TIME=0 s, GASFRACTION=0.2 -, FLUID="{TAB_LABEL}"',
        "ENDNETWORKCOMPONENT",
        "NETWORKCOMPONENT TYPE=NODE, TAG=OUTLET",
        f' PARAMETERS LABEL="Outlet", TYPE=PRESSURE, X=100 m, Y=0 m, Z=0 m, PRESSURE={outlet_pressure}, TEMPERATURE={outlet_temp}, TIME=0 s, FLUID="{TAB_LABEL}"',
        "ENDNETWORKCOMPONENT",
        "CONNECTION TERMINALS = (INLET FLOWTERM_1, MAIN INLET)",
        "CONNECTION TERMINALS = (OUTLET FLOWTERM_1, MAIN OUTLET)",
        "ENDCASE",
        "",
    ])


def _write_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_text: str) -> Path:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / TAB_NAME).write_text(
        make_tab([1_000_000.0, 10_000_000.0], [10.0, 30.0]), encoding="utf-8"
    )
    case = tmp_path / "case.genkey"
    case.write_text(case_text, encoding="utf-8")
    return case


def _mint_run(case: Path, selection_id: str = "sel-1") -> dict[str, Any]:
    payload = tools.approval_payload(
        "run_execute",
        {"source": str(case), "timeout_s": 60, "selection_id": selection_id},
    )
    minted = approvals.mint(
        "run_execute", payload, context_generation=workspace.context_generation()
    )
    return {**payload, "approval_token": minted["token"]}


def _valid_spec(pvt_reference: str = TAB_NAME) -> dict[str, Any]:
    return {
        "version": "2",
        "nodes": [
            {"label": "IN_A", "kind": "source", "pressure_pa": 5_000_000.0,
             "temperature_c": 20.0, "gas_fraction": 0.2, "total_water_fraction": 0.4},
            {"label": "OUT_A", "kind": "sink", "pressure_pa": 3_000_000.0,
             "temperature_c": 18.0, "gas_fraction": 0.15, "total_water_fraction": 0.35},
        ],
        "flowpaths": [
            {"label": "MAIN", "from": "IN_A", "to": "OUT_A", "pipes": [
                {"label": "PIPE_A", "centerline_m": [[0, 0, 0], [100, 0, 0]],
                 "diameter_m": 0.2, "roughness_m": 5e-5, "sections": 4},
            ]},
        ],
        "pvt_reference": pvt_reference,
        "fluid_label": TAB_LABEL,
        "thermal": {"model": "adiabatic"},
        "integration": {"end_time_s": 3600},
        "outputs": ["PT", "TM"],
    }


HANGUL = re.compile(r"[\uac00-\ud7a3]")


# ------------------------------------------------ outlet below the minimum


def test_outlet_below_table_minimum_refuses_run_with_named_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The installed-app failure: outlet 1.013 bara, table from 10 bar."""
    case = _write_workspace(
        tmp_path, monkeypatch, make_case(outlet_pressure="1.013 bara")
    )

    def _must_not_launch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("the run must not launch below the table range")

    monkeypatch.setattr(tools.runner, "execute_run", _must_not_launch)
    with pytest.raises(tools.ToolRefusedError, match="OUTLET"):
        tools.dispatch("run_execute", _mint_run(case))


def test_inlet_below_table_minimum_refuses_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The installed-app failure: inlet 0.61 bara, table from 1 bar."""
    (tmp_path / TAB_NAME).write_text(
        make_tab([100_000.0, 10_000_000.0], [10.0, 30.0]), encoding="utf-8"
    )
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text(
        make_case(inlet_pressure="0.61 bara", outlet_pressure="30 bara"),
        encoding="utf-8",
    )

    def _must_not_launch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("the run must not launch below the table range")

    monkeypatch.setattr(tools.runner, "execute_run", _must_not_launch)
    with pytest.raises(tools.ToolRefusedError, match="INLET"):
        tools.dispatch("run_execute", _mint_run(case))


def test_refusal_names_node_value_and_table_range_in_ko_and_en(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason names the node, the value and the table range, in ko and en."""
    case = _write_workspace(
        tmp_path, monkeypatch, make_case(outlet_pressure="1.013 bara")
    )
    monkeypatch.setattr(
        tools.runner, "execute_run",
        lambda *_a: (_ for _ in ()).throw(AssertionError("must not launch")),
    )
    with pytest.raises(tools.ToolRefusedError) as caught:
        tools.dispatch("run_execute", _mint_run(case))
    reason = str(caught.value)
    assert "OUTLET" in reason
    assert "1.013" in reason
    assert "10" in reason  # the table minimum in bar
    assert HANGUL.search(reason) is not None
    assert "PVT" in reason or "table" in reason


# ------------------------------------------------------------------ warning


def test_near_edge_value_warns_but_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """11 bar sits within 10 percent of the 10-100 bar edge: warn, do not block."""
    (tmp_path / TAB_NAME).write_text(
        make_tab([1_000_000.0, 10_000_000.0], [10.0, 30.0]), encoding="utf-8"
    )
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    spec = _valid_spec()
    spec["nodes"][1]["pressure_pa"] = 1_100_000.0  # OUT_A sink, 11 bar
    result = tools.dispatch("case_spec_validate", {"spec": spec})
    assert result["valid"] is True
    warnings = result["warnings"]
    assert any("pvt_range_near_edge" in str(w.get("code")) for w in warnings)
    assert any("widen" in str(w.get("message")).lower() for w in warnings)

    case = tmp_path / "case.genkey"
    case.write_text(make_case(outlet_pressure="11 bara"), encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        tools.runner, "execute_run",
        lambda source, **_k: calls.append(source) or {"run_id": "r1", "state": "running"},
    )
    out = tools.dispatch("run_execute", _mint_run(case))
    assert calls != []
    assert out.get("pvt_range_warnings")


def _warnings_for(
    quantity: str, value_si: float, display: str, *, tab_range: Any
) -> list[str]:
    from olga_companion import pvt_range

    entry = pvt_range.RangeEntry(
        origin="OUTLET", kind="node", quantity=quantity,
        value_si=value_si, display=display, field="f",
    )
    refusals, warnings = pvt_range.check_entries([entry], tab_range)
    assert refusals == []
    return [message for _entry, message in warnings]


def _air_water_range() -> Any:
    from olga_companion import pvt_range

    return pvt_range.TabRange(50_000.0, 2_000_000.0, 0.0, 100.0, "air_water.tab")


def test_atmospheric_pressure_is_not_near_the_edge_of_a_half_bar_table() -> None:
    """Owner decision D1: 1.01325 bar is twice the 0.5 bar minimum, so no near-edge warning."""
    assert _warnings_for("pressure", 101_325.0, "1.01325 bar", tab_range=_air_water_range()) == []


@pytest.mark.parametrize(("value_pa", "display"), [(60_000.0, "0.6 bar"), (55_000.0, "0.55 bar"), (50_000.0, "0.5 bar")])
def test_pressure_close_to_the_low_edge_warns_with_its_margin(value_pa: float, display: str) -> None:
    """Low-edge margin = min(10% of the 19.5 bar span, half of 0.5 bar) = 0.25 bar."""
    messages = _warnings_for("pressure", value_pa, display, tab_range=_air_water_range())
    assert len(messages) == 1
    message = messages[0]
    english, korean = message.split("표 경계 근처")
    assert f"{display} is within 0.25 bar of the table minimum 0.5 bar" in english
    assert "of the table's" not in english
    assert "최소값 0.5 bar에서 0.25 bar 이내에 있습니다" in korean
    assert HANGUL.search(korean) is not None


@pytest.mark.parametrize(("value_pa", "display"), [(1_900_000.0, "19 bar"), (2_000_000.0, "20 bar")])
def test_pressure_close_to_the_high_edge_warns_with_the_span_margin(value_pa: float, display: str) -> None:
    messages = _warnings_for("pressure", value_pa, display, tab_range=_air_water_range())
    assert len(messages) == 1
    english, korean = messages[0].split("표 경계 근처")
    assert f"{display} is within 1.95 bar of the table maximum 20 bar" in english
    assert "최대값 20 bar에서 1.95 bar 이내에 있습니다" in korean


def test_pressure_just_below_the_minimum_refuses() -> None:
    from olga_companion import pvt_range

    entry = pvt_range.RangeEntry(
        origin="OUTLET", kind="node", quantity="pressure", value_si=49_999.0, display="0.49999 bar", field="f",
    )
    refusals, warnings = pvt_range.check_entries([entry], _air_water_range())
    assert len(refusals) == 1 and warnings == []


def test_pressure_beyond_the_margin_does_not_warn() -> None:
    assert _warnings_for("pressure", 250_000.0, "2.5 bar", tab_range=_air_water_range()) == []
    assert _warnings_for("pressure", 76_000.0, "0.76 bar", tab_range=_air_water_range()) == []
    # The margin is strict: exactly 0.25 bar above the 0.5 bar minimum is outside the band.
    assert _warnings_for("pressure", 75_000.0, "0.75 bar", tab_range=_air_water_range()) == []
    assert len(_warnings_for("pressure", 74_999.0, "0.74999 bar", tab_range=_air_water_range())) == 1


def test_the_pressure_step_grid_check_uses_the_same_margin() -> None:
    """The large-step warning trusts the table only for pressures the near-edge rule calls inside."""
    from olga_companion import pvt_range

    table = _air_water_range()
    assert pvt_range._inside_pressure_grid(75_000.0, table) is True
    assert pvt_range._inside_pressure_grid(74_999.0, table) is False
    assert pvt_range._inside_pressure_grid(1_805_000.0, table) is True
    assert pvt_range._inside_pressure_grid(1_805_001.0, table) is False


def test_the_low_edge_margin_keeps_the_span_rule_when_it_is_smaller() -> None:
    """10-100 bar: min(9 bar, 5 bar) = 5 bar, so 11 bar (1 bar from the edge) still warns."""
    from olga_companion import pvt_range

    wide = pvt_range.TabRange(1_000_000.0, 10_000_000.0, 0.0, 100.0, "wide.tab")
    messages = _warnings_for("pressure", 1_100_000.0, "11 bar", tab_range=wide)
    assert len(messages) == 1
    assert "within 5 bar of the table minimum 10 bar" in messages[0]
    assert _warnings_for("pressure", 1_600_000.0, "16 bar", tab_range=wide) == []


def test_temperature_near_edge_warning_keeps_the_span_margin() -> None:
    messages = _warnings_for("temperature", 5.0, "5 C", tab_range=_air_water_range())
    assert len(messages) == 1
    english, korean = messages[0].split("표 경계 근처")
    assert "5 C is within 10 C of the table minimum 0 C" in english
    assert "최소값 0 C에서 10 C 이내에 있습니다" in korean
    assert _warnings_for("temperature", 15.0, "15 C", tab_range=_air_water_range()) == []


def test_in_range_case_runs_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mid-grid values behave as today: the runner is called, no new warnings."""
    case = _write_workspace(tmp_path, monkeypatch, make_case())
    calls: list[str] = []
    monkeypatch.setattr(
        tools.runner, "execute_run",
        lambda source, **_k: calls.append(source) or {"run_id": "r1", "state": "running"},
    )
    out = tools.dispatch("run_execute", _mint_run(case))
    assert calls == [str(case)]
    assert not out.get("pvt_range_warnings")

    result = tools.dispatch("case_spec_validate", {"spec": _valid_spec()})
    assert result["valid"] is True
    assert result["warnings"] == []


# ------------------------------------------------------- plan step at turn


def test_plan_step_refuses_at_its_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bound run step stops failed/refused at its turn, never uncertain."""
    case = _write_workspace(
        tmp_path, monkeypatch, make_case(outlet_pressure="1.013 bara")
    )
    monkeypatch.setattr(
        tools.runner, "execute_run",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not launch")),
    )
    pending = SimpleNamespace(context_generation=workspace.context_generation())
    step = {
        "kind": "run_execute",
        "args": {"source": str(case), "timeout_s": 60, "selection_id": "sel-1"},
    }
    state, _output, message, code = plan_execution._run_step(
        "pending-1", pending, 1, step, {}, lambda _text: None
    )
    assert state == plan_progress.FAILED
    assert code == "refused"
    assert "OUTLET" in message


# --------------------------------------------- validate and compile blocks


def test_case_spec_validate_blocks_outside_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sink below the table minimum fails validation with a ko/en reason."""
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / TAB_NAME).write_text(
        make_tab([1_000_000.0, 10_000_000.0], [10.0, 30.0]), encoding="utf-8"
    )
    spec = _valid_spec()
    spec["nodes"][1]["pressure_pa"] = 101_300.0  # OUT_A sink, ~1.013 bara
    result = tools.dispatch("case_spec_validate", {"spec": spec})
    assert result["valid"] is False
    assert any("pvt_range_outside" in str(e.get("code")) for e in result["errors"])
    first = next(
        e for e in result["errors"] if "pvt_range_outside" in str(e.get("code"))
    )
    assert "OUT_A" in str(first["message"])
    assert HANGUL.search(str(first["message"])) is not None


def test_case_spec_compile_blocks_outside_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compile carries the same block: an out-of-range case is not compilable."""
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / TAB_NAME).write_text(
        make_tab([1_000_000.0, 10_000_000.0], [10.0, 30.0]), encoding="utf-8"
    )
    spec = _valid_spec()
    spec["nodes"][0]["pressure_pa"] = 61_000.0  # IN_A source, ~0.61 bara
    result = tools.dispatch("case_spec_compile", {"spec": spec})
    assert result["valid"] is False
    assert any("pvt_range_outside" in str(e.get("code")) for e in result["errors"])


# ------------------------------------------------- behave-as-today paths


def test_missing_table_behaves_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable table never blocks: launch and validation stay as today."""
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text(make_case(outlet_pressure="1.013 bara"), encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        tools.runner, "execute_run",
        lambda source, **_k: calls.append(source) or {"run_id": "r1", "state": "running"},
    )
    out = tools.dispatch("run_execute", _mint_run(case))
    assert calls == [str(case)]
    assert not out.get("pvt_range_warnings")

    result = tools.dispatch("case_spec_validate", {"spec": _valid_spec()})
    assert result["valid"] is True
    assert result["warnings"] == []


def test_case_without_pvtfile_behaves_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A case with no PVTFILE reference launches as today."""
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text(
        make_case(outlet_pressure="1.013 bara", pvtfile=None), encoding="utf-8"
    )
    calls: list[str] = []
    monkeypatch.setattr(
        tools.runner, "execute_run",
        lambda source, **_k: calls.append(source) or {"run_id": "r1", "state": "running"},
    )
    tools.dispatch("run_execute", _mint_run(case))
    assert calls == [str(case)]


def test_source_temperature_outside_table_warns_or_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Source temperatures are compared against the table temperature range."""
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / TAB_NAME).write_text(
        make_tab([1_000_000.0, 10_000_000.0], [10.0, 30.0]), encoding="utf-8"
    )
    spec = _valid_spec()
    spec["nodes"][0]["temperature_c"] = 200.0  # IN_A source, far above 30 C
    result = tools.dispatch("case_spec_validate", {"spec": spec})
    assert result["valid"] is False
    assert any("pvt_range_outside" in str(e.get("code")) for e in result["errors"])
