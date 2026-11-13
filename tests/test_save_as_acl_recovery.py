from __future__ import annotations

import errno
import re
from pathlib import Path

import pytest

from olga_companion import native_dialogs, sidecar_save_as_cleanup

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


def test_second_capture_acl_failure_publishes_usable_recovery_id(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_bytes(b"new output")
    destination = chosen / "saved.csv"
    destination.write_bytes(b"old destination")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    hardening_calls = 0

    def fail_second_hardening(path: Path, *, directory: bool) -> None:
        nonlocal hardening_calls
        del path, directory
        hardening_calls += 1
        if hardening_calls == 2:
            raise OSError(errno.EACCES, "second capture ACL failure")

    monkeypatch.setattr(
        sidecar_save_as_cleanup,
        "harden_private_path",
        fail_second_hardening,
    )

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-second-acl-failure", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    recovery_id = detail["recovery_id"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,64}", recovery_id)
    lookup = client.get(
        f"/api/native-dialogs/save-as/recovery/{recovery_id}",
        headers=_headers(token),
    )
    assert hardening_calls == 2
    assert lookup.status_code == 200
    assert lookup.json()["backup_available"] is True
    assert lookup.json()["status"] == "available"
    assert destination.read_bytes() == b"new output"
    assert str(tmp_path) not in response.text
