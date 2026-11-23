from __future__ import annotations

import hashlib
import errno
import importlib
import json
import re
from pathlib import Path

import pytest

from olga_companion import config, native_dialogs

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


def test_save_as_recovery_record_is_private_durable_redacted_and_survives_reload(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    exports = tmp_path / "exports"
    chosen = tmp_path / "private-destination-parent"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_bytes(b"new export")
    destination = chosen / "customer-secret-name.csv"
    backup = chosen / ".customer-secret-name.csv.recovery.private.bak"
    backup.write_bytes(b"old destination")
    expected_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )

    def retained_backup(*args, **kwargs):
        raise sidecar.SaveAsRecoveryRequiredError(destination, backup, expected_hash)

    monkeypatch.setattr(sidecar, "_copy_export_atomic", retained_backup)
    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-recorded-recovery", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    recovery_id = detail["recovery_id"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,64}", recovery_id)
    assert "instructions" in detail
    records_root = config.private_state_root() / "save-as-recovery"
    record_path = records_root / f"{recovery_id}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["destination"] == str(destination)
    assert record["backup"] == str(backup)
    assert record["expected_hash"] == expected_hash
    assert record["timestamp"]
    assert record_path.stat().st_mode & 0o077 == 0
    assert records_root.stat().st_mode & 0o077 == 0

    recovery_store = importlib.import_module("olga_companion.save_as_recovery")
    importlib.reload(recovery_store)
    lookup = client.get(
        f"/api/native-dialogs/save-as/recovery/{recovery_id}", headers=_headers(token)
    )

    assert lookup.status_code == 200
    body = lookup.json()
    assert set(body) == {"id", "status", "basename", "backup_available", "time"}
    assert body == {
        "id": recovery_id,
        "status": "available",
        "basename": destination.name,
        "backup_available": True,
        "time": record["timestamp"],
    }
    assert str(tmp_path) not in lookup.text
    assert chosen.name not in lookup.text
    assert backup.name not in lookup.text

    backup.unlink()
    missing = client.get(
        f"/api/native-dialogs/save-as/recovery/{recovery_id}", headers=_headers(token)
    )
    assert missing.status_code == 200
    assert missing.json()["status"] == "missing"
    assert missing.json()["backup_available"] is False


def test_save_as_recovery_lookup_requires_auth_and_rejects_forged_ids(
    token: str,
) -> None:
    route = "/api/native-dialogs/save-as/recovery/abcdefghijklmnop"
    assert client.get(route).status_code == 401
    assert client.get(route, headers={"X-Session-Token": "forged"}).status_code == 401
    assert client.get(route, headers=_headers(token)).status_code == 404
    assert (
        client.get(
            "/api/native-dialogs/save-as/recovery/short", headers=_headers(token)
        ).status_code
        == 404
    )


def test_save_as_record_failure_keeps_backup_and_returns_no_misleading_id(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    recovery_store = importlib.import_module("olga_companion.save_as_recovery")
    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_bytes(b"new")
    destination = chosen / "saved.csv"
    backup = chosen / ".saved.csv.recovery.private.bak"
    backup.write_bytes(b"old")
    expected_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    monkeypatch.setattr(
        sidecar,
        "_copy_export_atomic",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            sidecar.SaveAsRecoveryRequiredError(destination, backup, expected_hash)
        ),
    )
    monkeypatch.setattr(
        recovery_store,
        "persist",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError(errno.EIO, "record failed")
        ),
    )

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-record-failed", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "save_as_manual_recovery_required"
    assert "recovery_id" not in detail
    assert "instructions" in detail
    assert backup.is_file() and backup.read_bytes() == b"old"
    assert str(tmp_path) not in response.text
    assert backup.name not in response.text


def test_recovery_record_root_temp_and_final_are_privacy_hardened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olga_companion import save_as_recovery

    root = tmp_path / "private-state" / "save-as-recovery"
    destination = tmp_path / "saved.csv"
    backup = tmp_path / "retained.bak"
    backup.write_bytes(b"old destination")
    expected_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    hardened: list[tuple[Path, bool]] = []
    monkeypatch.setattr(save_as_recovery, "_root", lambda: root)
    monkeypatch.setattr(
        save_as_recovery,
        "harden_private_path",
        lambda path, *, directory: hardened.append((path, directory)),
    )

    recovery_id = save_as_recovery.persist(destination, backup, expected_hash)

    target = root / f"{recovery_id}.json"
    assert hardened[0] == (root, True)
    assert hardened[-1] == (target, False)
    assert any(path.suffix == ".tmp" and not directory for path, directory in hardened)
    assert target.is_file()


def test_recovery_record_final_privacy_failure_returns_no_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olga_companion import save_as_recovery

    root = tmp_path / "private-state" / "save-as-recovery"
    backup = tmp_path / "retained.bak"
    backup.write_bytes(b"old destination")
    expected_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    monkeypatch.setattr(save_as_recovery, "_root", lambda: root)

    def reject_final_record(path: Path, *, directory: bool) -> None:
        if not directory and path.suffix == ".json":
            raise OSError(errno.EACCES, "record ACL failure")

    monkeypatch.setattr(
        save_as_recovery,
        "harden_private_path",
        reject_final_record,
    )

    with pytest.raises(OSError, match="record ACL failure"):
        save_as_recovery.persist(tmp_path / "saved.csv", backup, expected_hash)

    assert list(root.glob("*.json")) == []
    assert list(root.glob("*.tmp")) == []
