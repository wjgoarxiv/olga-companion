from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olga_companion import runner
from olga_companion.genkey_static import file_sha256
from olga_companion.runner import execute_run, recent_runs, run_status
from olga_companion.sidecar import app

FAKE_OLGA = Path(__file__).parent / "fixtures" / "fake_olga" / "fake_olga.py"
FLUID_TAB = Path(__file__).parent / "fixtures" / "fluids" / "fluid.tab"
SAMPLE_ROOT = Path(__file__).parent / "fixtures" / "cases"
SIMPLE = SAMPLE_ROOT / "simple_pipeline.genkey"

pytestmark = pytest.mark.skipif(not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable")


def _case(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    case = tmp_path / "case.genkey"
    case.write_text(SIMPLE.read_text().replace('"./dummy_fluid.tab"', '"./fluid.tab"'))
    shutil.copy2(FLUID_TAB, tmp_path / "fluid.tab")
    return case


def _wait_for_receipt(run_dir: Path, phase: str, timeout_s: float = 15) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.05)
            continue
        if record.get("phase") == phase:
            return record
        time.sleep(0.05)
    raise AssertionError(f"run receipt did not reach {phase}")


def test_terminal_receipt_recovers_status_after_registry_loss(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setenv("FAKE_OLGA_RESULTS", "1")
    source = _case(tmp_path)

    started = execute_run(str(source), approved=True)
    run_dir = Path(started["run_dir"])
    record = _wait_for_receipt(run_dir, "terminal")

    assert record["schema_version"] == 1
    assert record["run_id"] == started["run_id"]
    assert record["state"] == "completed"
    assert record["source"]["name"] == source.name
    assert record["source"]["resolved_path"] == str(source.resolve())
    assert record["source"]["sha256"] == file_sha256(source)
    assert record["companions"]
    assert record["runtime"]["candidate_id"] == started["candidate_id"]
    assert record["runtime"]["exe"] == str(FAKE_OLGA)
    assert record["selection_id"] == started["selection_id"]
    assert record["validation"]["valid"] is True
    assert all(record["timestamps"][name] for name in ("prepared_at", "started_at", "finished_at"))
    assert record["command"] == started["command"]
    assert record["exit_code"] == 0
    assert record["failure"] is None
    assert {item["name"] for item in record["outputs"]} == {"case.out", "case.tpl", "case.ppl"}
    with runner._REGISTRY_LOCK:
        runner._RUNS.pop(started["run_id"], None)

    recovered = run_status(started["run_id"])

    assert recovered["state"] == "completed"
    assert recovered["exit_code"] == 0
    assert recovered["recovered_from_receipt"] is True
    assert recovered["outputs"] == record["outputs"]


def test_orphaned_running_receipt_returns_recovery_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_root = tmp_path / "sandbox" / "runs"
    monkeypatch.setattr(runner, "sandbox_root", lambda: tmp_path / "sandbox")
    run_dir = runs_root / "orphan-run"
    run_dir.mkdir(parents=True)
    receipt = {
        "schema_version": 1,
        "run_id": "orphan-run",
        "phase": "running",
        "state": "running",
        "source": {"name": "case.genkey", "sha256": "a" * 64, "staged_sha256": "a" * 64},
        "companions": [],
        "runtime": {"candidate_id": "runtime_x", "runtime_id": "runtime_x", "version": None, "kind": "script", "exe": "/stub"},
        "selection_id": "selection",
        "validation": {"valid": True, "command": {}},
        "timestamps": {"prepared_at": "2026-01-01T00:00:00Z", "started_at": "2026-01-01T00:00:01Z", "finished_at": None},
        "command": ["/stub", "case.genkey"],
        "exit_code": None,
        "failure": None,
        "outputs": [],
        "timed_out": False,
        "cancelled": False,
        "ok": False,
    }
    (run_dir / "run.json").write_text(json.dumps(receipt), encoding="utf-8")

    status = run_status("orphan-run")

    assert status["state"] == "recovery_unknown"
    assert status["ok"] is False
    assert status["recovered_from_receipt"] is True


@pytest.mark.parametrize(
    "payload, message",
    [
        ("{not-json", "corrupt"),
        (json.dumps({"schema_version": 999, "run_id": "bad", "phase": "terminal", "state": "failed"}), "schema"),
    ],
)
def test_corrupt_or_unknown_receipt_schema_fails_honestly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: str, message: str
) -> None:
    monkeypatch.setattr(runner, "sandbox_root", lambda: tmp_path / "sandbox")
    run_dir = tmp_path / "sandbox" / "runs" / "bad"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        run_status("bad")


def test_malformed_schema_v1_receipt_fails_as_corrupt_not_key_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "sandbox_root", lambda: tmp_path / "sandbox")
    run_dir = tmp_path / "sandbox" / "runs" / "bad-v1"
    run_dir.mkdir(parents=True)
    malformed = {
        "schema_version": 1,
        "run_id": "bad-v1",
        "phase": "terminal",
        "state": "completed",
        "source": {},
        "companions": [],
        "runtime": {},
        "selection_id": "selection",
        "validation": {},
        "timestamps": {},
        "command": [],
        "exit_code": 0,
        "failure": None,
        "outputs": [],
    }
    (run_dir / "run.json").write_text(json.dumps(malformed), encoding="utf-8")

    with pytest.raises(ValueError, match="corrupt"):
        run_status("bad-v1")


def test_recent_run_history_is_bounded_and_exposed_by_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    first = execute_run(str(_case(tmp_path / "first")), approved=True)
    second = execute_run(str(_case(tmp_path / "second")), approved=True)
    first_record = _wait_for_receipt(Path(first["run_dir"]), "terminal")
    second_record = _wait_for_receipt(Path(second["run_dir"]), "terminal")
    assert second_record["timestamps"]["prepared_at"] > first_record["timestamps"]["prepared_at"]
    first_receipt = Path(first["run_dir"]) / "run.json"
    second_receipt = Path(second["run_dir"]) / "run.json"
    second_mtime = second_receipt.stat().st_mtime_ns
    os.utime(first_receipt, ns=(second_mtime + 1_000_000, second_mtime + 1_000_000))

    history = recent_runs(limit=1)
    response = TestClient(app).get("/api/run/history", params={"limit": 1})

    assert len(history) == 1
    assert history[0]["run_id"] == second["run_id"]
    assert history[0]["state"] == "completed"
    assert history[0]["recovered_from_receipt"] is True
    assert "phase" not in history[0]
    assert response.status_code == 200
    assert response.json()["runs"] == history
