from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from olga_companion.genkey_static import file_sha256
from olga_companion.sweep_execution import (
    cancel_sweep,
    execute_sweep,
    preview_sweep,
    sweep_status,
)
from sweep_test_support import (
    FAKE_OLGA,
    SIMPLE,
    _resolvable_case,
    _run_dirs,
    _wait_for_sweep_final,
)

pytestmark = pytest.mark.skipif(
    not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable"
)


def test_sweep_execute_runs_all_cases_with_one_human_approval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Given one previewed sweep, When executed once with approval, Then every generated case reaches final status."""
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    preview = preview_sweep(
        str(_resolvable_case(tmp_path)),
        ["INTEGRATION.ENDTIME=3600,7200"],
        "oat",
        5,
        30,
    )

    started = execute_sweep(
        preview["sweep_id"], approved=True, plan_id=preview["plan_id"]
    )
    assert started["state"] in {"running", "completed"}
    assert all(case["run_id"] for case in started["cases"])

    final = _wait_for_sweep_final(preview["sweep_id"])
    assert final["state"] == "completed"
    assert final["ok"] is True
    assert {case["state"] for case in final["cases"]} == {"completed"}
    assert all(case["pvt_files"] for case in final["cases"])
    assert all("solver_progress" in case for case in final["cases"])
    assert "percent" not in final
    assert final["counts"]["completed"] == 2

    time.sleep(0.05)

    later = sweep_status(preview["sweep_id"])
    assert later["elapsed_ms"] == final["elapsed_ms"]
    assert [case["elapsed_ms"] for case in later["cases"]] == [
        case["elapsed_ms"] for case in final["cases"]
    ]


def test_sweep_execute_requires_explicit_approval(tmp_path: Path) -> None:
    """Given a planned sweep, When approval is absent, Then no case run is started."""
    preview = preview_sweep(
        str(_resolvable_case(tmp_path)),
        ["INTEGRATION.ENDTIME=3600,7200"],
        "oat",
        5,
        30,
    )

    with pytest.raises(ValueError, match="approval"):
        execute_sweep(preview["sweep_id"], approved=False)

    status = sweep_status(preview["sweep_id"])
    assert status["state"] == "planned"
    assert all(case["run_id"] is None for case in status["cases"])


def test_sweep_pins_base_case_runtime_selection_for_generated_children(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "OLGA-2022.1.0.exe"
    runtime.write_bytes(b"runtime")
    candidate = {
        "exe": str(runtime),
        "kind": "engine",
        "version": "2022.1.0",
        "source": "install-glob",
        "candidate_id": "runtime_selected",
        "runtime_id": "runtime_selected",
        "sha256": file_sha256(runtime),
    }
    selected = {
        "detected": True,
        **candidate,
        "kind": "engine",
        "version": "2022.1.0",
        "selection_status": "selected",
        "rationale": "qualified base case",
        "required_version": None,
        "candidates": [candidate],
        "alternatives": [],
        "evidence": [],
    }
    seen: list[dict | None] = []
    monkeypatch.setattr(
        "olga_companion.sweep_execution.runner.detect_olga",
        lambda source=None: selected,
    )
    monkeypatch.setattr(
        "olga_companion.runner.ensure_broker",
        lambda: type(
            "Artifact",
            (),
            {"to_dict": lambda self: {"protocol": "test", "sha256": "b" * 64}},
        )(),
    )

    def fake_execute(
        source,
        approved=False,
        override=False,
        timeout_s=3600,
        selection_id=None,
        pinned_detection=None,
    ):
        seen.append(pinned_detection)
        return {"run_id": f"run-{len(seen)}"}

    monkeypatch.setattr(
        "olga_companion.sweep_execution.runner.execute_run", fake_execute
    )
    preview = preview_sweep(
        str(_resolvable_case(tmp_path)),
        ["INTEGRATION.ENDTIME=3600,7200"],
        "oat",
        5,
        30,
    )

    started = execute_sweep(
        preview["sweep_id"], approved=True, plan_id=preview["plan_id"]
    )

    assert preview["detection"] == selected
    assert started["detection"] == selected
    assert len(seen) == 2
    assert all(item and item["candidate_id"] == "runtime_selected" for item in seen)
    assert all(item and item["sha256"] == candidate["sha256"] for item in seen)


def test_sweep_children_reject_same_metadata_runtime_replacement_before_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime.py"
    runtime.write_bytes(FAKE_OLGA.read_bytes())
    monkeypatch.setenv("OLGA_EXE_PATH", str(runtime))
    preview = preview_sweep(
        str(_resolvable_case(tmp_path)),
        ["INTEGRATION.ENDTIME=3600,7200"],
        "oat",
        5,
        30,
    )
    original_stat = runtime.stat()
    payload = runtime.read_bytes()
    runtime.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
    os.utime(runtime, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    popen = Mock()
    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", popen)
    before = _run_dirs()

    with pytest.raises(ValueError, match="runtime|candidate|preview"):
        execute_sweep(preview["sweep_id"], approved=True, plan_id=preview["plan_id"])

    assert _run_dirs() == before
    popen.assert_not_called()


def test_sweep_cancel_stops_all_running_cases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Given a running sweep, When cancelled, Then every live child run is cancelled."""
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setenv("FAKE_OLGA_SLEEP", "30")
    preview = preview_sweep(
        str(_resolvable_case(tmp_path)),
        ["INTEGRATION.ENDTIME=3600,7200"],
        "oat",
        5,
        30,
    )
    execute_sweep(preview["sweep_id"], approved=True, plan_id=preview["plan_id"])

    cancelled = cancel_sweep(preview["sweep_id"])
    assert cancelled["state"] == "cancelled"
    assert {case["state"] for case in cancelled["cases"]} == {"cancelled"}
    assert cancelled["ok"] is False
