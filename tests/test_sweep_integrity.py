from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from olga_companion.sweep_execution import execute_sweep, preview_sweep
from sweep_test_support import FAKE_OLGA, SIMPLE, _resolvable_case, _run_dirs

pytestmark = pytest.mark.skipif(
    not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable"
)


@pytest.mark.parametrize("drift", ["source", "companion"])
def test_sweep_execution_rejects_any_child_drift_before_starting_children(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, drift: str
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    preview = preview_sweep(
        str(_resolvable_case(tmp_path)),
        ["INTEGRATION.ENDTIME=3600,7200"],
        "oat",
        5,
        30,
    )
    first_case = Path(preview["cases"][0]["path"])
    if drift == "source":
        first_case.write_text(
            first_case.read_text() + "\n! changed after approval preview\n"
        )
    else:
        (first_case.parent / "fluid.tab").write_bytes(b"unapproved child companion")
    child_calls: list[str] = []
    monkeypatch.setattr(
        "olga_companion.sweep_execution.runner.execute_run",
        lambda source, **kwargs: child_calls.append(source) or {"run_id": "unexpected"},
    )
    before = _run_dirs()

    with pytest.raises(ValueError, match="plan|changed|preview"):
        execute_sweep(preview["sweep_id"], approved=True, plan_id=preview["plan_id"])

    assert child_calls == []
    assert _run_dirs() == before


@pytest.mark.parametrize("companion", ["pvt", "restart"])
def test_sweep_execution_rejects_changed_base_companion_before_starting_children(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, companion: str
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    base = _resolvable_case(tmp_path)
    target = tmp_path / "fluid.tab"
    if companion == "restart":
        target = tmp_path / "state.rsw"
        target.write_bytes(b"approved restart")
        base.write_text(f'RESTART READFILE=ON, FILE="./state.rsw"\n{base.read_text()}')
    preview = preview_sweep(str(base), ["INTEGRATION.ENDTIME=3600,7200"], "oat", 5, 30)
    target.write_bytes(target.read_bytes() + b"\nunapproved change")
    child_calls: list[str] = []
    monkeypatch.setattr(
        "olga_companion.sweep_execution.runner.execute_run",
        lambda source, **kwargs: child_calls.append(source) or {"run_id": "unexpected"},
    )
    before = _run_dirs()

    with pytest.raises(ValueError, match="plan|changed|preview"):
        execute_sweep(preview["sweep_id"], approved=True, plan_id=preview["plan_id"])

    assert child_calls == []
    assert _run_dirs() == before


def test_sweep_preflights_every_materialized_child_before_starting_any_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    preview = preview_sweep(
        str(_resolvable_case(tmp_path)),
        ["INTEGRATION.ENDTIME=3600,7200"],
        "oat",
        5,
        30,
    )
    second_case = Path(preview["cases"][1]["path"])
    original_materialize = __import__(
        "olga_companion.sweep_execution", fromlist=["_materialize_pvt_companions"]
    )._materialize_pvt_companions
    materialize_calls = 0

    def drift_during_materialization(base: Path, case: Path) -> list[str]:
        nonlocal materialize_calls
        materialize_calls += 1
        if materialize_calls == 1:
            (second_case.parent / "fluid.tab").write_bytes(
                b"swapped before all children were preflighted"
            )
        return original_materialize(base, case)

    child_calls: list[str] = []
    monkeypatch.setattr(
        "olga_companion.sweep_execution._materialize_pvt_companions",
        drift_during_materialization,
    )
    monkeypatch.setattr(
        "olga_companion.sweep_execution.runner.execute_run",
        lambda source, **kwargs: child_calls.append(source) or {"run_id": "unexpected"},
    )
    before = _run_dirs()

    with pytest.raises(ValueError, match="plan|changed|preview"):
        execute_sweep(preview["sweep_id"], approved=True, plan_id=preview["plan_id"])

    assert child_calls == []
    assert _run_dirs() == before


def test_sweep_later_child_drift_after_preflight_cannot_launch_changed_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olga_companion import runner

    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    preview = preview_sweep(
        str(_resolvable_case(tmp_path)),
        ["INTEGRATION.ENDTIME=3600,7200"],
        "oat",
        5,
        30,
    )
    second_case = Path(preview["cases"][1]["path"])
    real_execute = runner.execute_run
    handoffs: list[str | None] = []

    def mutate_before_later_handoff(source: str, **kwargs):
        handoffs.append(kwargs.get("selection_id"))
        if len(handoffs) == 1:
            second_case.write_text(
                second_case.read_text() + "\n! changed after sweep preflight\n"
            )
        return real_execute(source, **kwargs)

    popen = Mock()
    popen.return_value.poll.return_value = 0
    popen.return_value.wait.return_value = 0
    monkeypatch.setattr(
        "olga_companion.sweep_execution.runner.execute_run", mutate_before_later_handoff
    )
    monkeypatch.setattr(
        "olga_companion.runner._validate_case",
        lambda path: {"valid": True, "command": {}},
    )
    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", popen)
    before = _run_dirs()

    try:
        result = execute_sweep(
            preview["sweep_id"], approved=True, plan_id=preview["plan_id"]
        )
        after = _run_dirs()

        assert all(handoffs), (
            "every child handoff must carry its post-preflight selection ID"
        )
        assert popen.call_count == 1, "the changed later child must not launch"
        assert result["cases"][0]["run_id"] is not None
        assert result["cases"][1]["run_id"] is None
        assert (
            "selection" in result["cases"][1]["error"].lower()
            or "preview" in result["cases"][1]["error"].lower()
        )
        assert len(after - before) == 1, (
            "only the unchanged first child may retain a run directory"
        )
    finally:
        for created in _run_dirs() - before:
            shutil.rmtree(created, ignore_errors=True)
