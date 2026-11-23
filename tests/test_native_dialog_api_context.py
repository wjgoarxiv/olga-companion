from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from olga_companion import config, native_dialogs, workspace

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


def test_newer_workspace_dialog_supersedes_older_completion_without_root_mutation(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_root = tmp_path / "dialog-old"
    older_choice = tmp_path / "dialog-older-choice"
    newer_choice = tmp_path / "dialog-newer-choice"
    for path in (old_root, older_choice, newer_choice):
        path.mkdir()
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(old_root))
    generation = workspace.context_generation()
    older_entered = threading.Event()
    release_older = threading.Event()
    cancelled: list[str] = []

    def dialog(_kind: str, request_id: str, **_kwargs):
        if request_id == "older-root":
            older_entered.set()
            assert release_older.wait(2)
            return {"status": "selected", "path": str(older_choice)}
        return {"status": "selected", "path": str(newer_choice)}

    monkeypatch.setattr(native_dialogs, "show_dialog", dialog)
    monkeypatch.setattr(
        native_dialogs,
        "cancel_dialog",
        lambda request_id: (
            cancelled.append(request_id)
            or {"status": "cancelled", "request_id": request_id}
        ),
    )
    responses: dict[str, Any] = {}

    def post_older() -> None:
        responses["older"] = client.post(
            "/api/native-dialogs/workspace",
            json={"request_id": "older-root", "context_generation": generation},
            headers=_headers(token),
        )

    thread = threading.Thread(target=post_older)
    thread.start()
    assert older_entered.wait(1)
    newer = client.post(
        "/api/native-dialogs/workspace",
        json={"request_id": "newer-root", "context_generation": generation},
        headers=_headers(token),
    )
    release_older.set()
    thread.join(2)
    assert not thread.is_alive()

    older = responses["older"]
    assert newer.status_code == 200
    assert newer.json()["root"] == str(newer_choice.resolve())
    assert older.status_code in {200, 409}
    if older.status_code == 200:
        assert older.json()["status"] in {"cancelled", "superseded"}
    assert workspace.context_identity()[0] == newer_choice.resolve()
    assert cancelled == ["older-root"]


def test_newer_same_root_open_case_supersedes_older_case_completion(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "same-root"
    root.mkdir()
    older_case = root / "older.genkey"
    newer_case = root / "newer.genkey"
    older_case.write_text("older")
    newer_case.write_text("newer")
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(root))
    generation = workspace.context_generation()
    older_entered = threading.Event()
    release_older = threading.Event()

    def dialog(_kind: str, request_id: str, **_kwargs):
        if request_id == "older-case":
            older_entered.set()
            assert release_older.wait(2)
            return {"status": "selected", "path": str(older_case)}
        return {"status": "selected", "path": str(newer_case)}

    monkeypatch.setattr(native_dialogs, "show_dialog", dialog)
    responses: list[Any] = []
    thread = threading.Thread(
        target=lambda: responses.append(
            client.post(
                "/api/native-dialogs/open-case",
                json={"request_id": "older-case", "context_generation": generation},
                headers=_headers(token),
            )
        )
    )
    thread.start()
    assert older_entered.wait(1)
    newer = client.post(
        "/api/native-dialogs/open-case",
        json={"request_id": "newer-case", "context_generation": generation},
        headers=_headers(token),
    )
    release_older.set()
    thread.join(2)

    assert newer.status_code == 200
    assert newer.json()["active"]["name"] == newer_case.name
    assert workspace.active_workspace()["name"] == newer_case.name
    assert responses and responses[0].status_code in {200, 409}


def test_stale_context_dialog_is_rejected_before_native_process_and_coordinator_recovers(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_root = tmp_path / "stale-old"
    new_root = tmp_path / "stale-new"
    selected = tmp_path / "selected-after-error"
    for path in (old_root, new_root, selected):
        path.mkdir()
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(old_root))
    stale_generation = workspace.context_generation()
    workspace.switch_root(new_root)
    calls: list[str] = []
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda _kind, request_id, **_kwargs: (
            calls.append(request_id) or {"status": "selected", "path": str(selected)}
        ),
    )

    stale = client.post(
        "/api/native-dialogs/workspace",
        json={"request_id": "stale-dialog", "context_generation": stale_generation},
        headers=_headers(token),
    )
    fresh = client.post(
        "/api/native-dialogs/workspace",
        json={
            "request_id": "fresh-dialog",
            "context_generation": workspace.context_generation(),
        },
        headers=_headers(token),
    )

    assert stale.status_code == 409
    assert calls == ["fresh-dialog"]
    assert fresh.status_code == 200
    assert workspace.context_identity()[0] == selected.resolve()


def test_cancelled_context_dialog_cannot_apply_and_new_request_can_start(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cancel-root"
    cancelled_choice = tmp_path / "cancelled-choice"
    fresh_choice = tmp_path / "fresh-choice"
    for path in (root, cancelled_choice, fresh_choice):
        path.mkdir()
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(root))
    generation = workspace.context_generation()
    entered = threading.Event()
    release = threading.Event()

    def dialog(_kind: str, request_id: str, **_kwargs):
        if request_id == "cancel-context":
            entered.set()
            assert release.wait(2)
            return {"status": "selected", "path": str(cancelled_choice)}
        return {"status": "selected", "path": str(fresh_choice)}

    monkeypatch.setattr(native_dialogs, "show_dialog", dialog)
    monkeypatch.setattr(
        native_dialogs,
        "cancel_dialog",
        lambda request_id: {"status": "cancelled", "request_id": request_id},
    )
    old_responses: list[Any] = []
    thread = threading.Thread(
        target=lambda: old_responses.append(
            client.post(
                "/api/native-dialogs/workspace",
                json={"request_id": "cancel-context", "context_generation": generation},
                headers=_headers(token),
            )
        )
    )
    thread.start()
    assert entered.wait(1)
    cancelled = client.post(
        "/api/native-dialogs/cancel",
        json={"request_id": "cancel-context"},
        headers=_headers(token),
    )
    fresh = client.post(
        "/api/native-dialogs/workspace",
        json={"request_id": "after-cancel", "context_generation": generation},
        headers=_headers(token),
    )
    release.set()
    thread.join(2)

    assert cancelled.json()["status"] == "cancelled"
    assert fresh.status_code == 200
    assert fresh.json()["root"] == str(fresh_choice.resolve())
    assert old_responses[0].json()["status"] in {"cancelled", "superseded"}
    assert workspace.context_identity()[0] == fresh_choice.resolve()


def test_context_dialog_baseexception_and_unavailable_results_release_coordinator(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    root = tmp_path / "exception-root"
    root.mkdir()
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(root))
    generation = workspace.context_generation()
    request = sidecar.NativeWorkspaceDialogRequest(
        request_id="baseexception-dialog", context_generation=generation
    )
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt("injected")),
    )

    with pytest.raises(KeyboardInterrupt, match="injected"):
        sidecar.api_native_workspace(request, x_session_token=token)

    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "unavailable", "reason": "no native host"},
    )
    recovered = sidecar.api_native_workspace(
        sidecar.NativeWorkspaceDialogRequest(
            request_id="after-baseexception", context_generation=generation
        ),
        x_session_token=token,
    )
    assert recovered == {"status": "unavailable", "reason": "no native host"}
