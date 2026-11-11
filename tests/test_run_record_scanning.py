from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olga_companion import run_records, runner
from olga_companion.runner import recent_runs, run_status
from olga_companion.sidecar import app

FAKE_OLGA = Path(__file__).parent / "fixtures" / "fake_olga" / "fake_olga.py"
FLUID_TAB = Path(__file__).parent / "fixtures" / "fluids" / "fluid.tab"
SAMPLE_ROOT = Path(__file__).parent / "fixtures" / "cases"
SIMPLE = SAMPLE_ROOT / "simple_pipeline.genkey"

pytestmark = pytest.mark.skipif(not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable")


def _terminal_receipt(run_id: str, *, source_path: Path | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "phase": "terminal",
        "state": "completed",
        "source": {
            "name": "case.genkey",
            "sha256": "a" * 64,
            "staged_sha256": "a" * 64,
            **({"resolved_path": str(source_path.resolve())} if source_path is not None else {}),
        },
        "companions": [],
        "runtime": {
            "candidate_id": "runtime_x",
            "runtime_id": "runtime_x",
            "version": "2025.1.0",
            "kind": "opi",
            "exe": "/olga/opi.exe",
        },
        "selection_id": "selection",
        "validation": {"valid": True, "command": {}},
        "timestamps": {
            "prepared_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:01Z",
            "finished_at": "2026-01-01T00:00:02Z",
        },
        "command": ["/olga/opi.exe", "-f", "case.genkey"],
        "exit_code": 0,
        "failure": None,
        "outputs": [],
        "timed_out": False,
        "cancelled": False,
        "ok": True,
        "engine_failed": False,
        "validation_valid": True,
        "elapsed_ms": 1000,
        "log_tail": "normal stop",
    }


def test_recent_history_finds_newest_receipt_beyond_first_500_legacy_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sandbox = tmp_path / "sandbox"
    runs_root = sandbox / "runs"
    runs_root.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    for index in range(550):
        (runs_root / f"legacy-{index:04d}").mkdir()
    latest_dir = runs_root / "latest-receipt"
    latest_dir.mkdir()
    run_records.write_run_record(latest_dir, _terminal_receipt("latest-receipt"))
    real_scandir = run_records.os.scandir

    class OrderedScandir:
        def __init__(self, path: Path) -> None:
            self._iterator = real_scandir(path)

        def __enter__(self):
            entries = list(self._iterator)
            entries.sort(key=lambda entry: (entry.name == "latest-receipt", entry.name))
            return iter(entries)

        def __exit__(self, *_args: Any) -> None:
            self._iterator.close()

    monkeypatch.setattr(
        run_records.os,
        "scandir",
        lambda path: OrderedScandir(Path(path)) if Path(path) == runs_root else real_scandir(path),
    )

    history = recent_runs(limit=5)

    assert [item["run_id"] for item in history] == ["latest-receipt"]
    assert history[0]["state"] == "completed"
    assert history[0]["recovered_from_receipt"] is True
    assert history[0]["run_dir"] == str(latest_dir)


def test_recent_record_scan_caps_receipt_parsing_after_ranking_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    for index in range(225):
        run_dir = runs_root / f"run-{index:04d}"
        run_dir.mkdir()
        (run_dir / "run.json").write_text("{not-json", encoding="utf-8")
    calls = 0
    real_load = run_records.load_run_record

    def counted_load(run_dir: Path) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return real_load(run_dir)

    monkeypatch.setattr(run_records, "load_run_record", counted_load)

    records = run_records.recent_run_records(runs_root, limit=5)

    assert len(records) == 5
    assert calls <= 200
    assert all(record["state"] == "receipt_error" for record in records)


def test_recent_history_reports_corrupt_receipt_without_following_receipt_symlinks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sandbox = tmp_path / "sandbox"
    runs_root = sandbox / "runs"
    runs_root.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    bad_dir = runs_root / "bad-receipt"
    bad_dir.mkdir()
    (bad_dir / "run.json").write_text("{not-json", encoding="utf-8")
    linked_dir = runs_root / "linked-receipt"
    linked_dir.mkdir()
    outside = tmp_path / "outside-run.json"
    outside.write_text(json.dumps(_terminal_receipt("linked-receipt")), encoding="utf-8")
    (linked_dir / "run.json").symlink_to(outside)

    history = recent_runs(limit=10)

    assert len(history) == 1
    assert history[0]["run_id"] == "bad-receipt"
    assert history[0]["state"] == "receipt_error"
    assert history[0]["ok"] is False
    assert history[0]["recovered_from_receipt"] is False
    assert "corrupt" in history[0]["receipt_error"].lower()


def test_run_status_rejects_symlink_and_oversize_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sandbox = tmp_path / "sandbox"
    runs_root = sandbox / "runs"
    runs_root.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_terminal_receipt("linked-run")), encoding="utf-8")
    linked = runs_root / "linked-run"
    linked.mkdir()
    (linked / "run.json").symlink_to(outside)
    oversized = runs_root / "oversized-run"
    oversized.mkdir()
    (oversized / "run.json").write_bytes(b" " * (2 * 1024 * 1024))

    with pytest.raises(ValueError, match="symlink|regular"):
        run_status("linked-run")
    with pytest.raises(ValueError, match="large|size"):
        run_status("oversized-run")


def test_recovered_run_status_redacts_host_paths_from_operator_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sandbox = tmp_path / "sandbox"
    run_dir = sandbox / "runs" / "private-run"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    receipt = _terminal_receipt("private-run")
    receipt["log_tail"] = (
        "INPUT FILE : C:\\Users\\Woojin\\Private Folder\\case.genkey\n"
        "LOG FILE : /mnt/c/Users/Woojin/Private Folder/case.out"
    )
    run_records.write_run_record(run_dir, receipt)

    status = run_status("private-run")

    assert "C:\\" not in status["log_tail"]
    assert "/mnt/c/" not in status["log_tail"]
    assert "INPUT FILE : case.genkey" in status["log_tail"]
    assert "LOG FILE : case.out" in status["log_tail"]


def test_recent_history_source_filter_matches_exact_resolved_source_and_excludes_old_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sandbox = tmp_path / "sandbox"
    runs_root = sandbox / "runs"
    runs_root.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    first_source = tmp_path / "cases" / "first.genkey"
    second_source = tmp_path / "cases" / "second.genkey"
    first_source.parent.mkdir()
    first_source.write_text("CASE\n")
    second_source.write_text("CASE\n")
    for run_id, source in (("first-run", first_source), ("second-run", second_source)):
        run_dir = runs_root / run_id
        run_dir.mkdir()
        run_records.write_run_record(run_dir, _terminal_receipt(run_id, source_path=source))
        time.sleep(0.01)
    old_dir = runs_root / "old-without-path"
    old_dir.mkdir()
    run_records.write_run_record(old_dir, _terminal_receipt("old-without-path"))

    filtered = recent_runs(limit=10, source=str(first_source.parent / "." / first_source.name))
    response = TestClient(app).get("/api/run/history", params={"limit": 10, "source": str(first_source)})

    assert [item["run_id"] for item in filtered] == ["first-run"]
    assert filtered[0]["recovered_from_receipt"] is True
    assert response.status_code == 200
    assert [item["run_id"] for item in response.json()["runs"]] == ["first-run"]
