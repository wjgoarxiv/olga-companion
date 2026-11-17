"""W2-L3b (M8): run receipts carry their workspace root.

Mint tags the receipt at preflight time; records minted before the tag
(workspace_root absent) keep validating and scan with root None, which the
UI treats as other-workspace. Invented fixture names only.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from olga_companion.result_inventory import scan_run_results
from olga_companion.run_records import write_run_record
from olga_companion.runner import execute_run

FAKE_OLGA = Path(__file__).parent / "fixtures" / "fake_olga" / "fake_olga.py"
FLUID_TAB = Path(__file__).parent / "fixtures" / "fluids" / "fluid.tab"
SAMPLE_ROOT = Path(__file__).parent / "fixtures" / "cases"
SIMPLE = SAMPLE_ROOT / "simple_pipeline.genkey"

pytestmark = pytest.mark.skipif(not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable")

# scan_run_results only lists .tpl/.ppl files of at least MIN_RESULT_BYTES.
FIXTURE_BYTES = b"OLGA result fixture padding for inventory scan tests. " * 4


def _case(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    case = tmp_path / "case.genkey"
    case.write_text(SIMPLE.read_text().replace('"./dummy_fluid.tab"', '"./fluid.tab"'))
    shutil.copy2(FLUID_TAB, tmp_path / "fluid.tab")
    return case


def _wait_for_receipt(run_dir: Path, phase: str, timeout_s: float = 30) -> dict[str, Any]:
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


def _seed_isolated_run(tmp_path: Path, record: dict[str, Any]) -> Path:
    """Copy a receipt into an isolated runs root with a scannable file.

    The shared sandbox is polluted by parallel lanes, so scan assertions run
    against tmp_path instead of the live run directory.
    """
    run_dir = tmp_path / "runs" / record["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    write_run_record(run_dir, record)
    (run_dir / "case.tpl").write_bytes(FIXTURE_BYTES)
    return run_dir


def _run_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[dict[str, Any], Path]:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setenv("FAKE_OLGA_RESULTS", "1")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    started = execute_run(str(_case(tmp_path)), approved=True)
    run_dir = Path(started["run_dir"])
    record = _wait_for_receipt(run_dir, "terminal")
    assert record["run_id"] == started["run_id"]
    return record, tmp_path


def test_mint_tags_workspace_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    record, _ = _run_once(monkeypatch, tmp_path)

    assert Path(record["workspace_root"]).resolve() == tmp_path.resolve()


def test_scan_surfaces_minted_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    record, workspace = _run_once(monkeypatch, tmp_path)
    run_dir = _seed_isolated_run(tmp_path / "isolated", record)

    items = scan_run_results(run_dir.parent, list_cap=50, walk_cap=500)
    names = [item["name"] for item in items if item.get("run_id") == record["run_id"]]

    assert names == ["case.tpl"]
    assert all(Path(item["root"]).resolve() == workspace.resolve() for item in items)


def test_legacy_receipt_without_root_validates_and_scans_as_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record, _ = _run_once(monkeypatch, tmp_path)
    legacy = dict(record)
    legacy.pop("workspace_root", None)
    run_dir = _seed_isolated_run(tmp_path / "isolated", legacy)

    items = scan_run_results(run_dir.parent, list_cap=50, walk_cap=500)
    legacy_items = [item for item in items if item.get("run_id") == record["run_id"]]

    assert [item["name"] for item in legacy_items] == ["case.tpl"]
    # The root key must be present-but-None: absent keys read the same via
    # .get, so presence itself is the surfacing contract the UI filters on.
    assert all("root" in item and item["root"] is None for item in legacy_items)
