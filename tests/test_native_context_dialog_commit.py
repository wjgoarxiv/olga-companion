from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal, assert_never

import pytest

from olga_companion import config, native_dialogs, sidecar, workspace
from olga_companion.agent import session_token


@pytest.mark.parametrize("selection_kind", ["workspace", "case"])
def test_cancel_after_context_selection_commit_does_not_report_cancelled(
    selection_kind: Literal["workspace", "case"],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a selected workspace or case whose commit is complete while endpoint cleanup is paused.
    old_root = tmp_path / "old-root"
    selected_root = tmp_path / "selected-root"
    old_root.mkdir()
    selected_root.mkdir()
    selected_case = selected_root / "selected.genkey"
    selected_case.write_text("case", encoding="utf-8")
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(old_root))
    generation = workspace.context_generation()
    request_id = f"committed-{selection_kind}"
    match selection_kind:
        case "workspace":
            selected_path = selected_root
        case "case":
            selected_path = selected_case
        case unreachable:
            assert_never(unreachable)

    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *_args, **_kwargs: {"status": "selected", "path": str(selected_path)},
    )
    monkeypatch.setattr(
        native_dialogs,
        "cancel_dialog",
        lambda _request_id: {"status": "unavailable", "reason": "request_id is not active"},
    )
    finish_entered = threading.Event()
    release_finish = threading.Event()
    original_finish = native_dialogs.finish_context_dialog

    def finish_after_release(lease: native_dialogs.ContextDialogLease) -> None:
        finish_entered.set()
        assert release_finish.wait(2)
        original_finish(lease)

    monkeypatch.setattr(native_dialogs, "finish_context_dialog", finish_after_release)
    token = session_token.boot_token()
    with ThreadPoolExecutor(max_workers=1) as executor:
        match selection_kind:
            case "workspace":
                future = executor.submit(
                    sidecar.api_native_workspace,
                    sidecar.NativeWorkspaceDialogRequest(
                        request_id=request_id,
                        context_generation=generation,
                    ),
                    token,
                )
            case "case":
                future = executor.submit(
                    sidecar.api_native_open_case,
                    sidecar.NativeOpenCaseDialogRequest(
                        request_id=request_id,
                        context_generation=generation,
                    ),
                    token,
                )
            case unreachable:
                assert_never(unreachable)

        try:
            assert finish_entered.wait(2)
            assert workspace.context_identity()[0] == selected_root.resolve()
            match selection_kind:
                case "workspace":
                    assert workspace.active_workspace()["name"] is None
                case "case":
                    assert workspace.active_workspace()["name"] == selected_case.name
                case unreachable:
                    assert_never(unreachable)

            # When: cancellation arrives after the context mutation committed but before final cleanup.
            cancel_result = sidecar.api_native_dialog_cancel(
                sidecar.NativeDialogCancelRequest(request_id=request_id),
                x_session_token=token,
            )
        finally:
            release_finish.set()

        selection_result = future.result(timeout=2)

    # Then: the committed selection remains selected and cancel reports that no request is active.
    assert selection_result["status"] == "selected"
    assert cancel_result == {"status": "unavailable", "reason": "request_id is not active"}
