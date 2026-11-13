"""F2 code-quality pins. Each test names one review finding and fails until that finding is fixed."""

from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path

import pytest

from olga_companion import fluid_table, pvt_range, tab_compare
from olga_companion.agent import tools
from olga_companion.pvt_engine.errors import OverwriteError
from olga_companion.pvt_engine.tab_writer import check_request, generate_table

_HELPER_PATH = Path(__file__).with_name("test_pvt_range_precheck.py")
_helper_spec = importlib.util.spec_from_file_location("pvt_range_precheck_helpers", _HELPER_PATH)
assert _helper_spec is not None and _helper_spec.loader is not None
_helpers = importlib.util.module_from_spec(_helper_spec)
_helper_spec.loader.exec_module(_helpers)
TAB_NAME = _helpers.TAB_NAME
make_case = _helpers.make_case
make_tab = _helpers.make_tab

ATMOSPHERE_PA = 101_325.0
PSI_PA = 6_894.757293168


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (2, "Pa", 2.0),
        (2, "kPa", 2_000.0),
        (2, "MPa", 2_000_000.0),
        (2, "bar", 200_000.0),
        (2, "bara", 200_000.0),
        (2, "barg", 200_000.0 + ATMOSPHERE_PA),
        (2, "atm", 2 * ATMOSPHERE_PA),
        (2, "atma", 2 * ATMOSPHERE_PA),
        (2, "atmg", 3 * ATMOSPHERE_PA),
        (2, "psi", 2 * PSI_PA),
        (2, "psia", 2 * PSI_PA),
        (2, "psig", 2 * PSI_PA + ATMOSPHERE_PA),
        (2, "mmHg", 2 * 133.322387415),
        (2, "inwg", 2 * 249.08891 + ATMOSPHERE_PA),
        (2, "at", 2 * 98_066.5),
        (2, "atg", 2 * 98_066.5 + ATMOSPHERE_PA),
        (2, "BARG", 200_000.0 + ATMOSPHERE_PA),
    ],
)
def test_pressure_to_pa_converts_every_known_unit(value: float, unit: str, expected: float) -> None:
    converted = pvt_range.pressure_to_pa(value, unit)
    assert converted is not None
    assert converted == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (20, "C", 20.0),
        (20, "degC", 20.0),
        (293.15, "K", 20.0),
        (68, "F", 20.0),
        (68, "degF", 20.0),
        (527.67, "R", 20.0),
        (527.67, "degR", 20.0),
    ],
)
def test_temperature_to_c_converts_every_known_unit(value: float, unit: str, expected: float) -> None:
    converted = pvt_range.temperature_to_c(value, unit)
    assert converted is not None
    assert converted == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize(
    ("converter", "value", "unit"),
    [
        (pvt_range.pressure_to_pa, 10, None),
        (pvt_range.pressure_to_pa, 10, ""),
        (pvt_range.pressure_to_pa, 10, "torr"),
        (pvt_range.temperature_to_c, 20, None),
        (pvt_range.temperature_to_c, 20, ""),
        (pvt_range.temperature_to_c, 20, "Rankine"),
    ],
)
def test_missing_or_unknown_units_are_skipped(converter, value: float, unit: object) -> None:
    assert converter(value, unit) is None


def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_text: str, pressures: list[float], temps: list[float]) -> Path:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / TAB_NAME).write_text(make_tab(pressures, temps), encoding="utf-8")
    case = tmp_path / "case.genkey"
    case.write_text(case_text, encoding="utf-8")
    return case


def test_bara_on_the_pascal_edge_is_not_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """1.013 bara is 101300 Pa aside from binary rounding, so a 101300 Pa edge is inside."""
    case = _workspace(
        tmp_path,
        monkeypatch,
        make_case(outlet_pressure="1.013 bara", inlet_pressure="20 bara"),
        [101_300.0, 5_000_000.0],
        [10.0, 30.0],
    )
    refusals, _warnings = pvt_range.check_genkey_source(case)
    assert refusals == []


def test_node_pressure_ramp_below_the_table_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A time list on a node is checked point by point, the same way a source list is."""
    case_text = make_case(inlet_pressure="(50, 1) bara", inlet_temp="(20, 20) C")
    case = _workspace(
        tmp_path, monkeypatch, case_text, [1_000_000.0, 10_000_000.0], [10.0, 30.0]
    )
    refusals, _warnings = pvt_range.check_genkey_source(case)
    assert any("INLET" in message and "1" in message for message in refusals)


def test_lowercase_node_keys_are_still_compared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case_text = make_case().replace(
        'PRESSURE=30 bara, TEMPERATURE=15 C',
        "pressure=1 bara, temperature=15 C",
    ).replace("TYPE=PRESSURE", "type=pressure")
    case = _workspace(
        tmp_path, monkeypatch, case_text, [1_000_000.0, 10_000_000.0], [10.0, 30.0]
    )
    refusals, _warnings = pvt_range.check_genkey_source(case)
    assert any("OUTLET" in message for message in refusals)


def test_genkey_barg_psig_and_source_temperature_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gauge units and a source temperature list reach the table check from the case file."""
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / TAB_NAME).write_text(
        make_tab([200_000.0, 10_000_000.0], [10.0, 30.0]), encoding="utf-8"
    )
    barg = tmp_path / "barg.genkey"
    barg.write_text(
        make_case(outlet_pressure="0.5 barg", inlet_pressure="20 barg"), encoding="utf-8"
    )
    barg_refusals, _warnings = pvt_range.check_genkey_source(barg)
    assert any("0.5" in message and "barg" in message for message in barg_refusals)

    psig = tmp_path / "psig.genkey"
    psig.write_text(
        make_case(outlet_pressure="0 psig", inlet_pressure="200 psig"), encoding="utf-8"
    )
    psig_refusals, _warnings = pvt_range.check_genkey_source(psig)
    assert any("psig" in message for message in psig_refusals)

    source = tmp_path / "source.genkey"
    source_text = make_case().replace(
        "ENDNETWORKCOMPONENT",
        ' SOURCE LABEL="FEED", TEMPERATURE=(15, -40) C\nENDNETWORKCOMPONENT',
        1,
    )
    source.write_text(source_text, encoding="utf-8")
    source_refusals, _warnings = pvt_range.check_genkey_source(source)
    assert any("FEED" in message and "-40" in message for message in source_refusals)


def test_run_preview_refuses_before_it_builds_a_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _workspace(
        tmp_path, monkeypatch, make_case(outlet_pressure="1.013 bara"),
        [1_000_000.0, 10_000_000.0], [10.0, 30.0],
    )

    def must_not_preview(*_args, **_kwargs):
        raise AssertionError("preview must not build a command that approval would accept")

    monkeypatch.setattr(tools.runner, "preview_run", must_not_preview)
    with pytest.raises(tools.ToolRefusedError, match="OUTLET"):
        tools.dispatch("run_preview", {"source": str(case), "timeout_s": 60})


def test_run_preview_carries_a_near_edge_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _workspace(
        tmp_path, monkeypatch, make_case(outlet_pressure="11 bara"),
        [1_000_000.0, 10_000_000.0], [10.0, 30.0],
    )
    monkeypatch.setattr(
        tools.runner, "preview_run",
        lambda source, timeout_s: {"selection_id": "sel", "source": source, "timeout_s": timeout_s},
    )
    preview = tools.dispatch("run_preview", {"source": str(case), "timeout_s": 60})
    assert preview.get("pvt_range_warnings")
    assert any("11" in message for message in preview["pvt_range_warnings"])


def test_label_with_a_trailing_newline_is_rejected() -> None:
    with pytest.raises(ValueError, match="Label"):
        check_request(["CO2"], [1.0], "PR", [1e5, 2e5], [10.0, 20.0], "OK\n")


def test_toolkit_path_swap_does_not_overlap() -> None:
    overlap = {"current": 0, "max": 0}
    guard = threading.Lock()
    barrier = threading.Barrier(6)

    def worker() -> None:
        barrier.wait()
        with tab_compare._toolkit_imports():
            with guard:
                overlap["current"] += 1
                overlap["max"] = max(overlap["max"], overlap["current"])
            time.sleep(0.03)
            with guard:
                overlap["current"] -= 1

    threads = [threading.Thread(target=worker) for _index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert overlap["max"] == 1


def test_user_facing_table_errors_name_the_file_not_the_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing.tab"
    with pytest.raises(tab_compare.GridMismatchError, match="missing.tab") as missing_caught:
        tab_compare._check_file(missing)
    assert str(tmp_path) not in str(missing_caught.value)

    existing = tmp_path / "kept.tab"
    existing.write_text("owner\n", encoding="utf-8")
    with pytest.raises(OverwriteError, match="kept.tab") as overwrite_caught:
        generate_table(existing, ["CO2"], [1.0], "PR", [1e5, 2e5], [10.0, 20.0], "KEPT")
    assert str(tmp_path) not in str(overwrite_caught.value)


def test_draft_and_launch_errors_name_the_file_not_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = tmp_path / "draft.mfl"
    draft.write_text("remove all;\n", encoding="utf-8")
    with pytest.raises(fluid_table.FluidTableError, match="draft.mfl") as exists:
        fluid_table.write_draft_mfl(str(draft), "remove all;\n")
    assert str(tmp_path) not in str(exists.value)

    missing = tmp_path / "gone.mfl"
    with pytest.raises(fluid_table.FluidTableError, match="gone.mfl") as not_found:
        fluid_table.expected_tab_for_mfl(str(missing))
    assert str(tmp_path) not in str(not_found.value)

    exe = tmp_path / "MFBJ01.exe"
    exe.write_bytes(b"fake")

    def refuse(args, **_kwargs):
        raise OSError(f"cannot start {args[0]}")

    monkeypatch.setattr(fluid_table.subprocess, "Popen", refuse)
    with pytest.raises(fluid_table.FluidTableError, match="MFBJ01.exe") as started:
        fluid_table.launch_multiflash(str(exe))
    assert str(tmp_path) not in str(started.value)


def test_pickup_names_only_the_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "absent.tab"
    report = fluid_table.pickup_tab(str(missing), "NEUTRAL")
    message = str(report["errors"])
    assert "absent.tab" in message
    assert str(tmp_path) not in message


def test_launch_passes_a_wsl_mfl_through_multiflash_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "MFBJ01.exe"
    exe.write_bytes(b"fake")
    wsl_mfl = "/mnt/c/neutral/draft.mfl"
    real_is_file = Path.is_file

    def is_file(self: Path) -> bool:
        if self.as_posix() == wsl_mfl:
            return True
        return real_is_file(self)

    calls: list[list[str]] = []

    class FakeProcess:
        pid = 7

    def fake_popen(args, **_kwargs):
        calls.append(list(args))
        return FakeProcess()

    monkeypatch.setattr(Path, "is_file", is_file)
    monkeypatch.setattr(fluid_table.subprocess, "Popen", fake_popen)
    fluid_table.launch_multiflash(str(exe), wsl_mfl)
    assert calls[0][1] == "C:\\neutral\\draft.mfl"


def test_static_pvt_sentence_accepts_keyword_two_and_three() -> None:
    text = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    section = text.split("### Static PVT format support", 1)[1].split("###", 1)[0]
    assert "PHASE=TWO" in section and "PHASE=THREE" in section
    assert "PHASE=THREE` column" not in section
