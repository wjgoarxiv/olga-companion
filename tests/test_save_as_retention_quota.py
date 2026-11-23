from __future__ import annotations

import errno
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from olga_companion import native_dialogs
from olga_companion import sidecar_save_as_retention as retention
from olga_companion.sidecar_save_as_publish import copy_export_atomic

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


def _hold_retention_guard(
    destination: Path,
    acquired: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
) -> None:
    from olga_companion.sidecar_save_as_retention import retention_capacity_guard

    with retention_capacity_guard(0):
        acquired.set()
        release.wait(timeout=5)


def _enter_retention_guard(
    destination: Path,
    entered: multiprocessing.synchronize.Event,
) -> None:
    from olga_companion.sidecar_save_as_retention import retention_capacity_guard

    with retention_capacity_guard(0):
        entered.set()


def test_existing_save_fails_closed_when_retention_quota_is_full(
    token: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    destination = chosen / "saved.csv"
    source.write_bytes(b"bb")
    destination.write_bytes(b"aa")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(retention, "_MAX_RETENTION_BYTES", 4)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )

    first = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-retention-first", "artifact": str(source)},
        headers=_headers(token),
    )
    second = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-retention-full", "artifact": str(source)},
        headers=_headers(token),
    )

    retained = list(tmp_path.glob(".olga-companion-retained-*"))
    retained_files = [path for root in retained for path in root.iterdir()]
    assert first.status_code == 200
    assert second.status_code == 400
    assert destination.read_bytes() == b"bb"
    assert len(retained) == 1
    assert len(retained_files) == 2
    assert sum(path.stat().st_size for path in retained_files) == 4
    assert list(chosen.iterdir()) == [destination]


def test_concurrent_existing_saves_share_one_retention_quota_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "artifact.csv"
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    destination = chosen / "saved.csv"
    source.write_bytes(b"bb")
    destination.write_bytes(b"aa")
    monkeypatch.setattr(retention, "_MAX_RETENTION_BYTES", 4)
    start = threading.Barrier(2)

    def save() -> tuple[str, int]:
        start.wait()
        try:
            return "saved", copy_export_atomic(source, destination)
        except OSError as exc:
            return "failed", exc.errno or 0

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: save(), range(2)))

    assert sorted(outcomes) == [("failed", errno.ENOSPC), ("saved", 2)]
    retained = list(tmp_path.glob(".olga-companion-retained-*"))
    retained_files = [path for root in retained for path in root.iterdir()]
    assert destination.read_bytes() == b"bb"
    assert len(retained) == 1
    assert len(retained_files) == 2
    assert sum(path.stat().st_size for path in retained_files) == 4
    assert list(chosen.iterdir()) == [destination]


def test_retention_quota_is_global_across_destination_bases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "artifact.csv"
    source.write_bytes(b"bb")
    destinations: list[Path] = []
    for name in ("first", "second"):
        chosen = tmp_path / name / "chosen"
        chosen.mkdir(parents=True)
        destination = chosen / "saved.csv"
        destination.write_bytes(b"aa")
        destinations.append(destination)
    monkeypatch.setattr(retention, "_MAX_RETENTION_BYTES", 4)

    first = copy_export_atomic(source, destinations[0])
    with pytest.raises(OSError) as raised:
        copy_export_atomic(source, destinations[1])

    assert first == 2
    assert raised.value.errno == errno.ENOSPC
    retained = list(tmp_path.glob("*/.olga-companion-retained-*"))
    assert len(retained) == 1
    assert sum(path.stat().st_size for root in retained for path in root.iterdir()) == 4
    assert destinations[0].read_bytes() == b"bb"
    assert destinations[1].read_bytes() == b"aa"


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="fork probe covers the POSIX interprocess lock implementation",
)
def test_retention_guard_serializes_sidecar_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("fork")
    destination = tmp_path / "chosen" / "saved.csv"
    destination.parent.mkdir()
    destination.write_bytes(b"aa")
    acquired = context.Event()
    release = context.Event()
    entered = context.Event()
    holder = context.Process(
        target=_hold_retention_guard,
        args=(destination, acquired, release),
    )
    contender = context.Process(
        target=_enter_retention_guard,
        args=(destination, entered),
    )

    holder.start()
    assert acquired.wait(timeout=2)
    contender.start()
    entered_while_held = entered.wait(timeout=0.4)
    release.set()
    holder.join(timeout=3)
    contender.join(timeout=3)

    assert entered_while_held is False
    assert entered.is_set()
    assert holder.exitcode == 0
    assert contender.exitcode == 0
