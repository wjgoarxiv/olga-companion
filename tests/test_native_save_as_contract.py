from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from olga_companion import config, native_dialogs, saved_reveal

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


def test_save_as_rejects_forged_or_traversing_artifact_without_opening_dialog(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def dialog(*args, **kwargs):
        nonlocal called
        called = True
        return {"status": "cancelled"}

    monkeypatch.setattr(native_dialogs, "show_dialog", dialog)
    outside = tmp_path / "outside.csv"
    outside.write_text("secret")
    for artifact in (str(outside), "../../outside.csv"):
        response = client.post(
            "/api/native-dialogs/save-as",
            json={"request_id": "forged-save", "artifact": artifact},
            headers=_headers(token),
        )
        assert response.status_code == 400
    assert called is False


def test_save_as_copies_atomically_preserves_hash_and_hides_destination_path(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    source = exports / "server-generated.csv"
    source.write_bytes("α,β\n1,2\n".encode())
    destination_dir = tmp_path / "chosen"
    destination_dir.mkdir()
    destination = destination_dir / "renamed export.csv"
    monkeypatch.setattr(config, "exports_root", lambda: exports)
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-valid", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "basename", "size", "reveal_id"}
    assert body["status"] == "selected"
    assert body["basename"] == destination.name
    assert body["size"] == source.stat().st_size
    assert saved_reveal.path_for_reveal(body["reveal_id"]) == destination.resolve()
    assert destination.read_bytes() == source.read_bytes()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert not list(destination_dir.glob(".*.tmp"))
    assert str(destination) not in response.text


def test_save_as_rejects_destination_with_mismatched_extension(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    source = exports / "server-generated.csv"
    source.write_text("time,value\n0,1\n")
    destination = tmp_path / "misleading.txt"
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-mismatched-extension", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Selected destination must use the .csv extension."
    )
    assert not destination.exists()
    assert source.read_text() == "time,value\n0,1\n"


def test_save_as_rejects_same_source_and_missing_parent(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    source = exports / "artifact.csv"
    source.write_text("x")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    for index, destination in enumerate((source, tmp_path / "missing" / "copy.csv")):
        monkeypatch.setattr(
            native_dialogs,
            "show_dialog",
            lambda *args, _destination=destination, **kwargs: {
                "status": "selected",
                "path": str(_destination),
            },
        )
        response = client.post(
            "/api/native-dialogs/save-as",
            json={"request_id": f"save-invalid-{index}", "artifact": str(source)},
            headers=_headers(token),
        )
        assert response.status_code == 400
        assert source.read_text() == "x"


def test_cancel_endpoint_delegates_exact_request_id(
    token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []
    monkeypatch.setattr(
        native_dialogs,
        "cancel_dialog",
        lambda request_id: (
            seen.append(request_id) or {"status": "cancelled", "request_id": request_id}
        ),
    )

    response = client.post(
        "/api/native-dialogs/cancel",
        json={"request_id": "exact-request"},
        headers=_headers(token),
    )

    assert response.json() == {"status": "cancelled", "request_id": "exact-request"}
    assert seen == ["exact-request"]


def test_save_as_rejects_existing_hardlink_to_source(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_text("source")
    destination = chosen / "hardlink.csv"
    os.link(source, destination)
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-hardlink", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 400
    assert source.read_text() == destination.read_text() == "source"


def test_save_as_rejects_existing_symlink_to_source(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_text("source")
    destination = chosen / "symlink.csv"
    try:
        destination.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-symlink", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 400
    assert source.read_text() == "source"


def test_save_as_opens_in_requested_workspace_folder(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    source = exports / "report.md"
    source.write_bytes(b"# report\n")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    seen: dict[str, object] = {}

    def dialog(*args, **kwargs):
        seen.update(kwargs)
        return {"status": "cancelled"}

    monkeypatch.setattr(config, "exports_root", lambda: exports)
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(native_dialogs, "show_dialog", dialog)
    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "ws-folder", "artifact": str(source), "initial_path": str(workspace)},
        headers=_headers(token),
    )
    assert response.status_code == 200
    assert seen.get("initial_path") == workspace


def test_save_as_without_workspace_falls_back_to_documents(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    source = exports / "report.md"
    source.write_bytes(b"# report\n")
    seen: dict[str, object] = {}

    def dialog(*args, **kwargs):
        seen.update(kwargs)
        return {"status": "cancelled"}

    monkeypatch.setattr(config, "exports_root", lambda: exports)
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(native_dialogs, "show_dialog", dialog)
    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "no-workspace", "artifact": str(source)},
        headers=_headers(token),
    )
    assert response.status_code == 200
    documents = Path.home() / "Documents"
    expected = documents if documents.is_dir() else source.parent
    assert seen.get("initial_path") == expected
    assert seen.get("initial_path") != exports or expected == exports
