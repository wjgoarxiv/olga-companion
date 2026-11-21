"""0.1.22 row 9: a result offers "Edit from this run" only while the case it ran from is still in the
workspace with the exact bytes the run recorded; otherwise it carries the reason instead."""

from __future__ import annotations

import hashlib
from pathlib import Path

from test_case_edit_routes import ws  # noqa: F401

from olga_companion.result_inventory import scan_run_results
from olga_companion.run_records import write_run_record


def _run(runs: Path, run_id: str, source: dict) -> None:
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "case.tpl").write_text("OLGA trend file header line\n", encoding="utf-8")
    write_run_record(run_dir, {
        "schema_version": 1, "run_id": run_id, "phase": "terminal", "state": "completed",
        "source": {"name": "x.genkey", "staged_sha256": source.get("sha256"), **source},
        "companions": [], "runtime": {"candidate_id": "c", "runtime_id": "r", "version": "2022.1.0", "kind": "engine", "exe": "x"},
        "selection_id": "s", "validation": {}, "timestamps": {"prepared_at": None, "started_at": None, "finished_at": None},
        "command": [], "exit_code": 0, "failure": None, "outputs": [{"name": "case.tpl", "sha256": None}],
    })


def _case(root: Path, name: str, text: str) -> tuple[Path, str]:
    path = root / "cases" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _edit_sources(runs: Path) -> dict[str, dict]:
    return {item["run_id"]: item["edit_source"] for item in scan_run_results(runs, list_cap=50, walk_cap=500)}


def test_the_unchanged_case_of_a_run_can_be_edited(ws: Path, tmp_path: Path) -> None:  # noqa: F811
    case, sha = _case(ws, "a.genkey", "CASE LABEL=a\n")
    runs = tmp_path / "runs"
    _run(runs, "run-a", {"resolved_path": str(case), "sha256": sha})
    assert _edit_sources(runs)["run-a"] == {"rel": "cases/a.genkey"}


def test_review_r1_a_case_whose_name_another_case_shares_is_not_offered(ws: Path, tmp_path: Path) -> None:  # noqa: F811
    # The workspace makes a case active by its file name, so two cases named x.genkey cannot be told apart.
    case, sha = _case(ws, "x.genkey", "CASE LABEL=a\n")
    twin = ws / "other" / "x.genkey"
    twin.parent.mkdir(parents=True)
    twin.write_text("CASE LABEL=b\n", encoding="utf-8")
    runs = tmp_path / "runs"
    _run(runs, "run-a", {"resolved_path": str(case), "sha256": sha})
    assert _edit_sources(runs)["run-a"] == {"reason": "same_name"}


def test_a_changed_case_gives_the_reason_instead(ws: Path, tmp_path: Path) -> None:  # noqa: F811
    case, sha = _case(ws, "a.genkey", "CASE LABEL=a\n")
    runs = tmp_path / "runs"
    _run(runs, "run-a", {"resolved_path": str(case), "sha256": sha})
    case.write_text("CASE LABEL=changed\n", encoding="utf-8")
    assert _edit_sources(runs)["run-a"] == {"reason": "changed"}


def test_a_deleted_case_gives_the_reason_instead(ws: Path, tmp_path: Path) -> None:  # noqa: F811
    case, sha = _case(ws, "a.genkey", "CASE LABEL=a\n")
    runs = tmp_path / "runs"
    _run(runs, "run-a", {"resolved_path": str(case), "sha256": sha})
    case.unlink()
    assert _edit_sources(runs)["run-a"] == {"reason": "missing"}


def test_a_case_outside_the_workspace_is_not_offered(ws: Path, tmp_path: Path) -> None:  # noqa: F811
    outside, sha = _case(tmp_path / "elsewhere", "a.genkey", "CASE LABEL=a\n")
    runs = tmp_path / "runs"
    _run(runs, "run-a", {"resolved_path": str(outside), "sha256": sha})
    assert _edit_sources(runs)["run-a"] == {"reason": "outside_workspace"}


def test_a_run_without_a_recorded_source_path_is_not_offered(ws: Path, tmp_path: Path) -> None:  # noqa: F811
    runs = tmp_path / "runs"
    _run(runs, "run-a", {"sha256": hashlib.sha256(b"old receipt").hexdigest()})
    assert _edit_sources(runs)["run-a"] == {"reason": "unrecorded"}
