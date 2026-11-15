from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olga_companion import config, results, workspace
from olga_companion.genkey_static import file_sha256
from olga_companion.run_records import write_run_record
from olga_companion.sidecar import app

FIXTURE = Path(__file__).parent / "fixtures" / "results" / "fixture.tpl"

pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="result fixture unavailable")


@pytest.fixture
def result_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace_root = tmp_path / "workspace"
    runs_root = tmp_path / "sandbox" / "runs"
    workspace_root.mkdir()
    runs_root.mkdir(parents=True)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    monkeypatch.setattr(config, "sandbox_root", lambda: tmp_path / "sandbox")
    return workspace_root, runs_root


def test_result_inventory_includes_workspace_and_run_origins(result_roots: tuple[Path, Path]) -> None:
    workspace_root, runs_root = result_roots
    shutil.copy2(FIXTURE, workspace_root / "historical.tpl")
    run_dir = runs_root / "run-123"
    run_dir.mkdir()
    shutil.copy2(FIXTURE, run_dir / "fresh.tpl")

    inventory = workspace.list_results()
    by_name = {item["name"]: item for item in inventory}

    assert by_name["historical.tpl"]["id"] == "workspace:historical.tpl"
    assert by_name["historical.tpl"]["result_id"] == "workspace:historical.tpl"
    assert by_name["historical.tpl"]["origin"] == "workspace"
    assert by_name["fresh.tpl"]["id"] == "run:run-123/fresh.tpl"
    assert by_name["fresh.tpl"]["result_id"] == "run:run-123/fresh.tpl"
    assert by_name["fresh.tpl"]["origin"] == "run"
    assert by_name["fresh.tpl"]["run_state"] == "unknown"
    assert by_name["fresh.tpl"]["run_ok"] is None
    assert by_name["fresh.tpl"]["runtime_kind"] is None
    assert by_name["fresh.tpl"]["output_sha256"] is None
    assert by_name["fresh.tpl"]["provenance"]["kind"] == "legacy_run_directory"


def test_run_inventory_uses_bounded_two_level_scan(
    result_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, runs_root = result_roots
    run_dir = runs_root / "run-123"
    run_dir.mkdir()
    shutil.copy2(FIXTURE, run_dir / "fresh.tpl")
    nested = run_dir / "debug" / "deep"
    nested.mkdir(parents=True)
    shutil.copy2(FIXTURE, nested / "not-a-run-output.tpl")
    monkeypatch.setattr(workspace, "_list_files", lambda _suffixes: [])

    original_rglob = Path.rglob

    def reject_recursive_run_scan(path: Path, pattern: str):
        if path == runs_root:
            raise AssertionError("run inventory must not recursively traverse every sandbox")
        return original_rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", reject_recursive_run_scan)
    inventory = workspace.list_results()

    assert [item["name"] for item in inventory] == ["fresh.tpl"]


def test_workspace_result_inventory_uses_bounded_two_level_scan(
    result_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root, _ = result_roots
    shallow = workspace_root / "historical" / "fresh.tpl"
    shallow.parent.mkdir()
    shutil.copy2(FIXTURE, shallow)
    deep = workspace_root / "historical" / "debug" / "not-a-result.tpl"
    deep.parent.mkdir()
    shutil.copy2(FIXTURE, deep)

    def reject_recursive_scan(_path: Path, _pattern: str):
        raise AssertionError("result inventory must not recursively traverse the workspace")

    monkeypatch.setattr(Path, "rglob", reject_recursive_scan)
    inventory = workspace.list_results()

    assert [item["rel"] for item in inventory] == ["historical/fresh.tpl"]


def test_workspace_inventory_includes_conventional_simulation_results_depth_two(
    result_roots: tuple[Path, Path]
) -> None:
    workspace_root, _ = result_roots
    result = workspace_root / "simulation" / "results" / "fresh.tpl"
    result.parent.mkdir(parents=True)
    shutil.copy2(FIXTURE, result)

    inventory = workspace.list_results()

    assert [item["rel"] for item in inventory] == ["simulation/results/fresh.tpl"]


def _receipt(
    run_id: str,
    *,
    state: str = "completed",
    ok: bool = True,
    source_path: str = "/cases/case.genkey",
    output_name: str | None = None,
    output_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "phase": "terminal",
        "state": state,
        "source": {
            "name": "case.genkey",
            "sha256": "a" * 64,
            "staged_sha256": "a" * 64,
            "resolved_path": source_path,
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
        "outputs": []
        if output_name is None
        else [{"name": output_name, "sha256": output_sha256, "result_id": f"run:{run_id}/{output_name}"}],
        "ok": ok,
    }


def test_run_result_inventory_joins_receipt_state_and_provenance(
    result_roots: tuple[Path, Path]
) -> None:
    _, runs_root = result_roots
    run_dir = runs_root / "run-123"
    run_dir.mkdir()
    output = run_dir / "fresh.tpl"
    shutil.copy2(FIXTURE, output)
    digest = file_sha256(output)
    write_run_record(run_dir, _receipt("run-123", output_name="fresh.tpl", output_sha256=digest))

    item = workspace.list_results()[0]

    assert item["run_id"] == "run-123"
    assert item["run_state"] == "completed"
    assert item["provenance"]["kind"] == "run_receipt"
    assert item["provenance"]["source_name"] == "case.genkey"
    assert item["provenance"]["runtime_candidate_id"] == "runtime_x"
    assert item["run_ok"] is True
    assert item["runtime_kind"] == "opi"
    assert item["output_sha256"] == digest
    assert item["source_path"] == "/cases/case.genkey"
    assert item["candidate_id"] == "runtime_x"
    assert item["runtime_version"] == "2025.1.0"


def test_failed_run_result_inventory_keeps_partial_output_provenance(
    result_roots: tuple[Path, Path]
) -> None:
    _, runs_root = result_roots
    run_dir = runs_root / "run-partial"
    run_dir.mkdir()
    output = run_dir / "partial.tpl"
    shutil.copy2(FIXTURE, output)
    digest = file_sha256(output)
    write_run_record(
        run_dir,
        _receipt("run-partial", state="failed", ok=False, output_name="partial.tpl", output_sha256=digest),
    )

    item = workspace.list_results()[0]

    assert item["run_state"] == "failed"
    assert item["run_ok"] is False
    assert item["output_sha256"] == digest


def test_run_result_inventory_labels_corrupt_receipt_honestly(
    result_roots: tuple[Path, Path]
) -> None:
    _, runs_root = result_roots
    run_dir = runs_root / "run-bad"
    run_dir.mkdir()
    shutil.copy2(FIXTURE, run_dir / "fresh.tpl")
    (run_dir / "run.json").write_text("{not-json", encoding="utf-8")

    item = workspace.list_results()[0]

    assert item["run_state"] == "unknown"
    assert item["provenance"]["kind"] == "invalid_run_receipt"
    assert "corrupt" in item["provenance"]["receipt_error"].lower()


@pytest.mark.parametrize("kind", ["symlink", "oversize"])
def test_result_inventory_labels_unsafe_receipts_invalid(
    result_roots: tuple[Path, Path], tmp_path: Path, kind: str
) -> None:
    _, runs_root = result_roots
    run_dir = runs_root / f"run-{kind}"
    run_dir.mkdir()
    shutil.copy2(FIXTURE, run_dir / "fresh.tpl")
    if kind == "symlink":
        outside = tmp_path / "outside-receipt.json"
        outside.write_text(json.dumps(_receipt(f"run-{kind}")), encoding="utf-8")
        (run_dir / "run.json").symlink_to(outside)
    else:
        (run_dir / "run.json").write_bytes(b" " * (2 * 1024 * 1024))

    item = workspace.list_results()[0]

    assert item["run_state"] == "unknown"
    assert item["provenance"]["kind"] == "invalid_run_receipt"
    expected = "symlink" if kind == "symlink" else "large"
    assert expected in item["provenance"]["receipt_error"].lower()


def test_result_inventory_skips_empty_artifacts_and_orders_newest_first(
    result_roots: tuple[Path, Path]
) -> None:
    workspace_root, runs_root = result_roots
    old = workspace_root / "old.tpl"
    shutil.copy2(FIXTURE, old)
    empty = workspace_root / "empty.tpl"
    empty.touch()
    fake = workspace_root / "fake.tpl"
    fake.write_bytes(b"fake-tpl")
    run_dir = runs_root / "run-new"
    run_dir.mkdir()
    fresh = run_dir / "fresh.tpl"
    shutil.copy2(FIXTURE, fresh)
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    os.utime(fresh, ns=(2_000_000_000, 2_000_000_000))

    inventory = workspace.list_results()

    assert [item["name"] for item in inventory] == ["fresh.tpl", "old.tpl"]
    assert all(item["size"] > 0 for item in inventory)
    assert all(item["name"] != "fake.tpl" for item in inventory)


def test_run_result_identifier_loads_series(result_roots: tuple[Path, Path]) -> None:
    _, runs_root = result_roots
    run_dir = runs_root / "run-123"
    run_dir.mkdir()
    shutil.copy2(FIXTURE, run_dir / "fresh.tpl")
    variable = results.load_result(str(run_dir / "fresh.tpl"))["variables"][0]["variable"]

    response = TestClient(app).post(
        "/api/results/series",
        json={"rel": "run:run-123/fresh.tpl", "variable": variable},
    )

    assert response.status_code == 200, response.text
    assert response.json()["variable"] == variable


def test_result_load_rejects_file_outside_allowed_roots(
    result_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    outside = tmp_path / "outside.tpl"
    shutil.copy2(FIXTURE, outside)

    with pytest.raises(ValueError, match="workspace or run sandbox"):
        results.load_result(str(outside))


def test_zero_byte_result_is_rejected_before_the_parser_runs(
    result_roots: tuple[Path, Path],
) -> None:
    # Given the empty .ppl a failed run leaves behind. pyfas raises a bare
    # UnboundLocalError on empty input, which reads like a packaging failure.
    workspace_root, _ = result_roots
    (workspace_root / "aborted.ppl").write_bytes(b"")

    # When it is resolved, then the caller is told the file is empty.
    with pytest.raises(workspace.WorkspaceError, match="empty"):
        workspace.resolve_result("workspace:aborted.ppl")


def test_series_route_reports_an_empty_result_file_cleanly(
    result_roots: tuple[Path, Path],
) -> None:
    workspace_root, _ = result_roots
    (workspace_root / "aborted.ppl").write_bytes(b"")

    response = TestClient(app).post(
        "/api/results/series",
        json={"rel": "workspace:aborted.ppl", "variable": "PT"},
    )

    assert response.status_code == 400, response.text
    assert "empty" in response.json()["detail"]
