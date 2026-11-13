from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock


from olga_companion import runner
from olga_companion.run_outputs import collect_outputs


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "progress"


def _live_state(
    run_dir: Path,
    *,
    poll_result: int | None,
    receipt: dict[str, Any] | None = None,
) -> runner._RunState:
    popen = SimpleNamespace(poll=lambda: poll_result)
    if poll_result is not None:
        popen.wait = lambda timeout=None: poll_result
    return runner._RunState(
        popen=popen,
        run_dir=run_dir,
        log_path=run_dir / "run.log",
        command=["fake", "owner.genkey"],
        detection={},
        selection_id="selection",
        validation_valid=True,
        timeout_s=30,
        started_monotonic=time.monotonic() - 2,
        timer=Mock(),
        receipt=receipt or {"phase": "running", "timestamps": {"finished_at": None}},
        staged_case_name="owner.genkey",
    )


def _receipt(
    run_id: str,
    *,
    phase: str = "running",
    state: str = "running",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "phase": phase,
        "state": state,
        "source": {"name": "owner.genkey", "sha256": "a", "staged_sha256": "a"},
        "runtime": {
            "candidate_id": "c",
            "runtime_id": "r",
            "version": "v",
            "kind": "script",
            "exe": "fake",
        },
        "companions": [],
        "selection_id": "selection",
        "validation": {},
        "validation_valid": True,
        "timestamps": {
            "prepared_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:01Z",
            "finished_at": "2026-01-01T00:00:02Z" if phase == "terminal" else None,
        },
        "command": ["fake", "owner.genkey"],
        "exit_code": 0 if phase == "terminal" else None,
        "failure": None,
        "outputs": [],
        "staged_case_name": "owner.genkey",
    }
def test_staged_restart_input_is_not_an_output_but_fresh_generated_rsw_is(tmp_path: Path) -> None:
    input_restart = tmp_path / "input.rsw"
    generated_restart = tmp_path / "generated.rsw"
    input_restart.write_bytes(b"staged restart input")
    generated_restart.write_bytes(b"new solver restart output")
    companions = [
        {
            "kind": "restart",
            "reference": "./input.rsw",
            "resolved_path": str(tmp_path / "owner-input.rsw"),
            "sha256": "approved",
        }
    ]

    outputs = collect_outputs(tmp_path, companions=companions, started_wall_ns=time.time_ns() - 1_000_000)

    assert {item["name"] for item in outputs} == {"generated.rsw"}


def test_concurrent_terminal_polls_leave_one_valid_terminal_receipt(tmp_path: Path) -> None:
    run_dir = tmp_path / "concurrent"
    run_dir.mkdir()
    (run_dir / "owner.out").write_bytes((FIXTURE_DIR / "demo_adaptive.out").read_bytes())
    receipt = _receipt("concurrent")
    state = _live_state(run_dir, poll_result=0, receipt=receipt)
    writes: list[dict] = []
    writes_lock = threading.Lock()
    original_write = runner.write_run_record

    def recording_write(path: Path, record: dict) -> None:
        with writes_lock:
            writes.append(json.loads(json.dumps(record)))
        original_write(path, record)

    runner.write_run_record = recording_write
    try:
        threads = [threading.Thread(target=runner._live_run_status, args=("concurrent", state)) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            assert not thread.is_alive()
    finally:
        runner.write_run_record = original_write

    assert len(writes) == 1
    parsed = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert parsed["phase"] == "terminal"
    assert parsed["solver_progress"]["phase"] == "terminal"
