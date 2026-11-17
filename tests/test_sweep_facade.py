from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from olga_companion import sweep_execution, sweep_selection
from sweep_test_support import FAKE_OLGA, SIMPLE, _resolvable_case, _synthetic_sweep

pytestmark = pytest.mark.skipif(
    not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable"
)


class RecordingLock:
    def __init__(self) -> None:
        self.entries = 0

    def __enter__(self) -> RecordingLock:
        self.entries += 1
        return self

    def __exit__(self, *args: Any) -> None:
        return None


@pytest.fixture(autouse=True)
def _fake_olga(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))


def _preview(tmp_path: Path) -> dict[str, Any]:
    return sweep_execution.preview_sweep(
        str(_resolvable_case(tmp_path)),
        ["INTEGRATION.ENDTIME=3600"],
        "oat",
        5,
        30,
    )


def test_preview_resolves_rebound_plan_id_through_facade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def facade_plan_id(*args: Any) -> str:
        calls.append("called")
        return "facade-plan"

    monkeypatch.setattr(sweep_execution, "_plan_id", facade_plan_id)

    preview = _preview(tmp_path)

    assert calls == ["called"]
    assert preview["plan_id"] == "facade-plan"


def test_execute_resolves_rebound_plan_id_through_facade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = _synthetic_sweep(tmp_path, run_id=None, started=False)
    monkeypatch.setattr(sweep_execution, "_SWEEPS", {state.sweep_id: state})
    received_factories: list[Any] = []

    def facade_plan_id(*args: Any) -> str:
        return "facade-plan"

    def capture_launch(*args: Any) -> None:
        received_factories.append(args[3] if len(args) > 3 else None)

    monkeypatch.setattr(sweep_execution, "_plan_id", facade_plan_id)
    monkeypatch.setattr(sweep_execution._launch, "launch_sweep", capture_launch)

    sweep_execution.execute_sweep(state.sweep_id, approved=True, plan_id=state.plan_id)

    assert received_factories == [facade_plan_id]


def test_preview_resolves_rebound_case_factory_through_facade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = sweep_execution._case_from_entry
    seen: list[int] = []

    def facade_case(entry: dict[str, Any], base: Path):
        seen.append(int(entry["index"]))
        return original(entry, base)

    monkeypatch.setattr(sweep_execution, "_case_from_entry", facade_case)

    preview = _preview(tmp_path)

    assert seen == [0]
    assert preview["case_count"] == 1


def test_status_resolves_rebound_case_status_through_facade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = _synthetic_sweep(tmp_path, run_id=None, started=False)
    original = sweep_execution._case_status
    seen: list[int] = []

    def facade_case_status(case, cancelled: bool):
        seen.append(case.index)
        return original(case, cancelled)

    monkeypatch.setattr(sweep_execution, "_case_status", facade_case_status)

    result = sweep_execution._status_for_state(state)

    assert seen == [0]
    assert result["state"] == "planned"


def test_status_resolves_rebound_aggregate_through_facade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = _synthetic_sweep(tmp_path, run_id=None, started=False)
    original = sweep_execution._aggregate_state
    calls: list[tuple[bool, bool]] = []

    def facade_aggregate(cases, started: bool, cancelled: bool) -> str:
        calls.append((started, cancelled))
        return original(cases, started, cancelled)

    monkeypatch.setattr(sweep_execution, "_aggregate_state", facade_aggregate)

    result = sweep_execution._status_for_state(state)

    assert calls == [(False, False)]
    assert result["state"] == "planned"


def test_preview_and_lookup_use_rebound_facade_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    isolated_registry: dict[str, sweep_execution.SweepState] = {}
    monkeypatch.setattr(sweep_execution, "_SWEEPS", isolated_registry)

    preview = _preview(tmp_path)
    sweep_id = preview["sweep_id"]
    try:
        assert sweep_id in isolated_registry
        assert sweep_execution.sweep_status(sweep_id)["sweep_id"] == sweep_id
    finally:
        isolated_registry.pop(sweep_id, None)
        sweep_selection.SWEEPS.pop(sweep_id, None)


def test_preview_and_lookup_use_rebound_facade_registry_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lock = RecordingLock()
    monkeypatch.setattr(sweep_execution, "_REGISTRY_LOCK", lock)

    preview = _preview(tmp_path)
    sweep_id = preview["sweep_id"]
    try:
        sweep_execution.sweep_status(sweep_id)
        assert lock.entries == 2
    finally:
        sweep_selection.SWEEPS.pop(sweep_id, None)
