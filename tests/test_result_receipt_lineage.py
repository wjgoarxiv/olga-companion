from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from olga_companion import result_inventory


def test_only_receipt_listed_outputs_are_receipt_backed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run-123"
    run_dir.mkdir()
    (run_dir / "listed.tpl").write_bytes(b"listed result bytes")
    (run_dir / "historical.tpl").write_bytes(b"historical result bytes")
    monkeypatch.setattr(
        result_inventory,
        "load_run_record",
        lambda _run_dir: {
            "schema_version": 1,
            "state": "completed",
            "ok": True,
            "source": {"name": "case.genkey", "sha256": "a" * 64},
            "runtime": {"candidate_id": "runtime-1", "version": "2022.1"},
            "selection_id": "selection-1",
            "outputs": [{"name": "listed.tpl", "sha256": hashlib.sha256(b"listed result bytes").hexdigest()}],
        },
    )

    results = result_inventory.scan_run_results(tmp_path, list_cap=20, walk_cap=40)
    by_name = {item["name"]: item for item in results}

    assert by_name["listed.tpl"]["lineage_status"] == "receipt_output"
    assert by_name["listed.tpl"]["provenance"]["kind"] == "run_receipt"
    assert by_name["historical.tpl"]["lineage_status"] is None
    assert by_name["historical.tpl"]["provenance"]["kind"] == "unlisted_run_file"
    assert by_name["historical.tpl"]["output_sha256"] is None


def test_a_listed_output_replaced_after_the_run_is_not_receipt_backed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run-456"
    run_dir.mkdir()
    listed = run_dir / "listed.tpl"
    listed.write_bytes(b"bytes the run recorded")
    recorded = hashlib.sha256(listed.read_bytes()).hexdigest()
    monkeypatch.setattr(
        result_inventory,
        "load_run_record",
        lambda _run_dir: {
            "schema_version": 1, "state": "completed", "ok": True,
            "source": {"name": "case.genkey", "sha256": "a" * 64},
            "runtime": {"candidate_id": "runtime-1", "version": "2022.1"},
            "selection_id": "selection-1",
            "outputs": [{"name": "listed.tpl", "sha256": recorded}],
        },
    )

    before = result_inventory.scan_run_results(tmp_path, list_cap=20, walk_cap=40)[0]
    listed.write_bytes(b"bytes a user dropped in later")
    after = result_inventory.scan_run_results(tmp_path, list_cap=20, walk_cap=40)[0]

    assert before["lineage_status"] == "receipt_output"
    assert after["lineage_status"] == "receipt_changed"
    assert after["output_sha256"] == recorded, "the recorded digest stays visible as evidence"


def test_a_receipt_without_a_usable_digest_is_never_reported_as_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run-789"
    run_dir.mkdir()
    (run_dir / "listed.tpl").write_bytes(b"some result bytes")
    monkeypatch.setattr(
        result_inventory,
        "load_run_record",
        lambda _run_dir: {
            "schema_version": 1, "state": "failed", "ok": False,
            "source": {"name": "case.genkey", "sha256": "a" * 64},
            "runtime": {"candidate_id": "runtime-1", "version": "2022.1"},
            "selection_id": "selection-1",
            "outputs": [{"name": "listed.tpl"}],
        },
    )

    result = result_inventory.scan_run_results(tmp_path, list_cap=20, walk_cap=40)[0]

    assert result["lineage_status"] == "receipt_changed"


def test_a_recorded_size_mismatch_proves_change_without_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run-size"
    run_dir.mkdir()
    (run_dir / "listed.tpl").write_bytes(b"result bytes long enough")
    monkeypatch.setattr(
        result_inventory, "load_run_record",
        lambda _d: {"schema_version": 1, "state": "completed", "ok": True,
                    "source": {"name": "c.genkey", "sha256": "a" * 64},
                    "runtime": {"candidate_id": "r", "version": "1"}, "selection_id": "s",
                    "outputs": [{"name": "listed.tpl", "sha256": "b" * 64, "size": 999}]},
    )
    monkeypatch.setattr(result_inventory, "_current_sha256", lambda *_a: pytest.fail("a size mismatch must not be hashed"))

    item = result_inventory.scan_run_results(tmp_path, list_cap=5, walk_cap=20)[0]

    assert item["lineage_status"] == "receipt_changed"


def test_a_same_size_replacement_that_keeps_the_old_mtime_is_caught_within_the_reuse_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    now = [1000.0]
    monkeypatch.setattr(result_inventory, "_clock", lambda: now[0])
    monkeypatch.setattr(result_inventory, "_CTIME_IS_CHANGE_TIME", False)  # the Windows case
    run_dir = tmp_path / "run-same"
    run_dir.mkdir()
    listed = run_dir / "listed.tpl"
    listed.write_bytes(b"original result bytes!")
    recorded = hashlib.sha256(listed.read_bytes()).hexdigest()
    stamp = listed.stat()
    monkeypatch.setattr(
        result_inventory, "load_run_record",
        lambda _d: {"schema_version": 1, "state": "completed", "ok": True,
                    "source": {"name": "c.genkey", "sha256": "a" * 64},
                    "runtime": {"candidate_id": "r", "version": "1"}, "selection_id": "s",
                    "outputs": [{"name": "listed.tpl", "sha256": recorded, "size": stamp.st_size}]},
    )
    status = lambda: result_inventory.scan_run_results(tmp_path, list_cap=5, walk_cap=20)[0]["lineage_status"]  # noqa: E731
    assert status() == "receipt_output"

    listed.write_bytes(b"tampered result bytes!")  # same length
    os.utime(listed, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))  # and the old mtime restored
    now[0] += result_inventory._UNPROVEN_REUSE_SECONDS + 1

    # No stat field can tell, so once the window has passed the bytes are hashed again.
    assert status() == "receipt_changed"
