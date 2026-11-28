"""Past the listing cap the inventory keeps the newest results and says it is capped (review 2026-11-27)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from olga_companion import config, result_inventory, workspace
from olga_companion.agent import tools

BODY = b"'OLGA 2022.1.0' synthetic result body\n"
COUNT = 600


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace_root = tmp_path / "workspace"
    runs_root = tmp_path / "sandbox" / "runs"
    workspace_root.mkdir()
    runs_root.mkdir(parents=True)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setattr(config, "sandbox_root", lambda: tmp_path / "sandbox")
    return workspace_root, runs_root


def _results(folder: Path, count: int, prefix: str = "r") -> None:
    """r000 is the oldest, r599 the newest; created in an order unrelated to their age."""
    for number in sorted(range(count), key=lambda n: (n * 7919) % count):
        path = folder / f"{prefix}{number:03d}.tpl"
        path.write_bytes(BODY)
        stamp = 1_700_000_000_000_000_000 + number * 1_000_000_000
        os.utime(path, ns=(stamp, stamp))


def test_the_listed_results_are_the_newest_and_the_total_is_true(roots):
    workspace_root, _runs = roots
    _results(workspace_root, COUNT)

    pages = [tools.dispatch("results_inventory", {"offset": offset, "limit": 50}) for offset in range(0, 500, 50)]
    names = [item["name"] for page in pages for item in page["results"]]

    assert names == [f"r{number:03d}.tpl" for number in range(COUNT - 1, COUNT - 501, -1)]
    assert {page["total_results"] for page in pages} == {COUNT}
    assert all(page["capped"] for page in pages)
    # `truncated` means another page can be fetched, so paging ends at the last listable page;
    # `capped` and `total_results` say the 100 oldest exist beyond it.
    assert [page["truncated"] for page in pages] == [True] * 9 + [False]
    beyond = tools.dispatch("results_inventory", {"offset": 500, "limit": 50})
    assert beyond["results"] == [] and beyond["truncated"] is False and beyond["capped"] is True


def test_a_small_workspace_is_not_capped(roots):
    workspace_root, _runs = roots
    _results(workspace_root, 3)
    page = tools.dispatch("results_inventory", {"offset": 0, "limit": 100})
    assert page["total_results"] == 3
    assert page["truncated"] is False
    assert page["capped"] is False


def test_run_results_past_the_cap_keep_the_newest(roots):
    _workspace, runs_root = roots
    for number in range(30):
        run_dir = runs_root / f"run-{number:03d}"
        run_dir.mkdir()
        _results(run_dir, 1, prefix=f"case{number:03d}_")
        stamp = 1_700_000_000_000_000_000 + number * 1_000_000_000
        for path in run_dir.iterdir():
            os.utime(path, ns=(stamp, stamp))
    counts: dict = {}
    items = result_inventory.scan_run_results(runs_root, list_cap=10, walk_cap=500, counts=counts)
    assert sorted(item["run_id"] for item in items) == [f"run-{number:03d}" for number in range(20, 30)]
    assert counts == {"found": 30, "walk_capped": False}


def test_hitting_the_walk_cap_is_reported(roots, monkeypatch: pytest.MonkeyPatch):
    workspace_root, _runs = roots
    _results(workspace_root, 60)
    counts: dict = {}
    items = result_inventory.scan_workspace_results(workspace_root, list_cap=500, walk_cap=20, counts=counts)
    assert len(items) <= 20
    assert counts["walk_capped"] is True
    snapshot = workspace.results_snapshot()
    assert snapshot["total_results"] == 60 and snapshot["capped"] is False
    # The snapshot says so too, though every result found fits in the list.
    monkeypatch.setattr(workspace, "_WALK_CAP", 20)
    assert workspace.results_snapshot()["capped"] is True
