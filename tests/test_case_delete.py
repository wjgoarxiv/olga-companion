"""0.1.23 row 2: a case file is deleted only after the user's approval, and only to the Recycle Bin."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import case_delete, workspace
from olga_companion.agent.session_token import boot_token
from olga_companion.run_records import write_run_record
from olga_companion.sidecar import app


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setattr(workspace, "_active_state_path", lambda: tmp_path / "active.json")
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(case_delete, "_runs_root", lambda: runs)
    return root


@pytest.fixture
def bin_(tmp_path, monkeypatch, ws):
    """A stand-in Recycle Bin, plus a trap on every permanent delete inside the workspace."""
    recycled: list[Path] = []
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def fake_recycle(path: Path) -> None:
        recycled.append(path)
        os.replace(path, bin_dir / path.name)

    monkeypatch.setattr(case_delete, "recycle", fake_recycle)
    real_unlink, real_remove = Path.unlink, os.remove

    def inside(target) -> bool:
        return Path(target).resolve().is_relative_to(ws.resolve())

    def trap_unlink(self, *args, **kwargs):
        assert not inside(self), f"permanent delete of {self}"
        return real_unlink(self, *args, **kwargs)

    def trap_remove(target, *args, **kwargs):
        assert not inside(target), f"permanent delete of {target}"
        return real_remove(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", trap_unlink)
    monkeypatch.setattr(os, "remove", trap_remove)
    monkeypatch.setattr(os, "unlink", trap_remove)
    return recycled


def _headers(token: str | None = None) -> dict[str, str]:
    return {"X-Session-Token": token if token is not None else boot_token()}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _review(rel: str):
    return TestClient(app).post("/api/case-delete/review", json={"rel": rel}, headers=_headers())


def _delete(rel: str, sha: str, generation: int | None = None, approved: bool = True, token: str | None = None):
    body = {
        "rel": rel,
        "sha256": sha,
        "context_generation": workspace.context_generation() if generation is None else generation,
        "approved": approved,
    }
    return TestClient(app).post("/api/case-delete", json=body, headers=_headers(token))


def _run(runs: Path, run_id: str, case: Path) -> None:
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)
    write_run_record(run_dir, {
        "schema_version": 1, "run_id": run_id, "phase": "terminal", "state": "completed",
        "source": {"name": case.name, "resolved_path": str(case.resolve()), "sha256": _sha(case), "staged_sha256": _sha(case)},
        "companions": [], "runtime": {"candidate_id": "c", "runtime_id": "r", "version": "2022.1.0", "kind": "engine", "exe": "x"},
        "selection_id": "s", "validation": {}, "timestamps": {"prepared_at": None, "started_at": None, "finished_at": None},
        "command": [], "exit_code": 0, "failure": None, "outputs": [],
    })


def test_review_describes_the_case_and_its_results_and_writes_nothing(ws, tmp_path) -> None:
    case = ws / "sub" / "a.genkey"
    case.parent.mkdir()
    case.write_text("CASE A\n")
    _run(tmp_path / "runs", "r1", case)
    _run(tmp_path / "runs", "r2", case)
    before = case.read_bytes()
    response = _review("sub/a.genkey")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "rel": "sub/a.genkey", "name": "a.genkey", "size": len(before), "sha256": _sha(case), "linked_results": 2,
    }
    assert case.read_bytes() == before


@pytest.mark.parametrize("rel", ["b.tab", "sub", "../out.genkey", "missing.genkey", "notes.txt"])
def test_review_refuses_anything_but_a_workspace_genkey(ws, rel) -> None:
    (ws / "b.tab").write_text("t")
    (ws / "sub").mkdir()
    (ws / "notes.txt").write_text("n")
    assert _review(rel).status_code == 400


def test_review_refuses_a_link(ws, tmp_path) -> None:
    target = ws / "real.genkey"
    target.write_text("R")
    try:
        (ws / "link.genkey").symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert _review("link.genkey").status_code == 400
    assert _delete("link.genkey", _sha(target)).status_code == 400


def test_an_approved_delete_sends_the_case_to_the_recycle_bin(ws, bin_) -> None:
    case = ws / "a.genkey"
    case.write_text("CASE A\n")
    other = ws / "b.genkey"
    other.write_text("CASE B\n")
    response = _delete("a.genkey", _sha(case))
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "recycled"
    assert bin_ == [case.resolve()]
    assert not case.exists()
    assert other.read_text() == "CASE B\n"


def test_without_approval_nothing_moves(ws, bin_) -> None:
    case = ws / "a.genkey"
    case.write_text("A")
    assert _delete("a.genkey", _sha(case), approved=False).status_code == 400
    assert bin_ == [] and case.exists()


def test_delete_needs_the_session_token(ws, bin_) -> None:
    case = ws / "a.genkey"
    case.write_text("A")
    assert _delete("a.genkey", _sha(case), token="wrong").status_code == 401
    assert bin_ == [] and case.exists()


def test_a_case_changed_after_the_review_is_not_deleted(ws, bin_) -> None:
    case = ws / "a.genkey"
    case.write_text("A")
    reviewed = _sha(case)
    case.write_text("A changed")
    response = _delete("a.genkey", reviewed)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_source"
    assert bin_ == [] and case.read_text() == "A changed"


def test_a_delete_from_an_older_workspace_context_is_refused(ws, bin_) -> None:
    case = ws / "a.genkey"
    case.write_text("A")
    response = _delete("a.genkey", _sha(case), generation=workspace.context_generation() + 1)
    assert response.status_code == 409
    assert bin_ == [] and case.exists()


def test_deleting_the_open_case_closes_it(ws, bin_) -> None:
    case = ws / "a.genkey"
    case.write_text("A")
    workspace.set_active_rel("a.genkey")
    assert _delete("a.genkey", _sha(case)).status_code == 200
    assert workspace.active() == {"name": None, "path": None}


def test_deleting_another_case_keeps_the_open_one(ws, bin_) -> None:
    (ws / "a.genkey").write_text("A")
    case = ws / "b.genkey"
    case.write_text("B")
    workspace.set_active_rel("a.genkey")
    assert _delete("b.genkey", _sha(case)).status_code == 200
    assert workspace.active()["name"] == "a.genkey"


def test_the_same_delete_sent_twice_moves_the_file_once(ws, bin_) -> None:
    case = ws / "a.genkey"
    case.write_text("A")
    sha = _sha(case)
    assert _delete("a.genkey", sha).status_code == 200
    assert _delete("a.genkey", sha).status_code == 400
    assert len(bin_) == 1


def test_a_failed_recycle_leaves_the_case_and_says_nothing_was_deleted(ws, monkeypatch) -> None:
    case = ws / "a.genkey"
    case.write_text("A")

    def broken(path: Path) -> None:
        raise case_delete.CaseDeleteError("The Recycle Bin refused the file; nothing was deleted.")

    monkeypatch.setattr(case_delete, "recycle", broken)
    response = _delete("a.genkey", _sha(case))
    assert response.status_code == 400
    assert "nothing was deleted" in response.json()["detail"]["message"]
    assert case.exists()


def test_off_windows_the_recycle_bin_refuses_and_keeps_the_file(tmp_path, monkeypatch) -> None:
    case = tmp_path / "a.genkey"
    case.write_text("A")
    monkeypatch.setattr(case_delete.os, "name", "posix")
    with pytest.raises(case_delete.CaseDeleteError):
        case_delete.recycle(case)
    assert case.exists()


_OK = {"drive_type": 3, "volume_found": True, "no_recycle_policy": False, "nuke_on_delete": 0, "max_capacity_mb": 1024, "size": 4096}


def test_a_fixed_drive_with_the_recycle_bin_on_is_allowed() -> None:
    assert case_delete.bin_refusal(**_OK) is None


@pytest.mark.parametrize("change", [
    {"drive_type": 2},  # removable
    {"drive_type": 4},  # network
    {"volume_found": False},
    {"no_recycle_policy": True},
    {"nuke_on_delete": 1},  # "Remove files immediately"
    {"max_capacity_mb": 0},
    {"size": 2 * 1024 * 1024 * 1024},
])
def test_any_sign_that_windows_would_delete_for_good_refuses(change) -> None:
    reason = case_delete.bin_refusal(**{**_OK, **change})
    assert reason and "nothing was deleted" in reason


def test_a_volume_never_configured_uses_the_windows_default_recycle_bin() -> None:
    assert case_delete.bin_refusal(**{**_OK, "nuke_on_delete": None, "max_capacity_mb": None}) is None


def test_recycle_asks_the_gate_before_calling_windows(tmp_path, monkeypatch) -> None:
    case = tmp_path / "a.genkey"
    case.write_text("A")
    monkeypatch.setattr(case_delete, "_on_windows", lambda: True)
    monkeypatch.setattr(case_delete, "_recycle_refusal", lambda path: "The Recycle Bin is off for this drive; nothing was deleted.")
    with pytest.raises(case_delete.CaseDeleteError, match="nothing was deleted"):
        case_delete.recycle(case)
    assert case.exists()


def test_the_module_never_deletes_permanently() -> None:
    source = Path(case_delete.__file__).read_text(encoding="utf-8")
    for call in (".unlink(", "os.remove(", "os.unlink(", "rmtree("):
        assert call not in source
