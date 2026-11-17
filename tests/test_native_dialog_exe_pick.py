"""T9 RED: the exe-pick dialog kind, its script branch, and the pick/clear routes."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import native_dialogs, sidecar
from olga_companion.agent import session_token


def _folder_free_branch(name: str) -> str:
    script = native_dialogs.POWERSHELL_DIALOG_SCRIPT
    start = script.index(f"if ($kind -eq '{name}')")
    end = script.index("} elseif ($kind -eq 'save-as')", start)
    if name == "save-as":
        end = len(script)
    return script[start:end]


def test_exe_pick_branch_uses_open_file_dialog_with_exe_filter() -> None:
    branch = _folder_free_branch("exe-pick")
    assert "[System.Windows.Forms.OpenFileDialog]::new()" in branch
    assert "(*.exe)|*.exe" in branch
    assert "$dialog.CheckFileExists = $true" in branch
    assert "$dialog.ShowDialog($owner)" in branch
    assert "@{ status = 'selected'; path =" in branch
    assert "@{ status = 'cancelled' }" in branch


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("OLGA_EXE_PATH", "")
    return TestClient(sidecar.app, raise_server_exceptions=False)


def test_pick_requires_session_token(api: TestClient) -> None:
    assert api.post("/api/run/olga-exe/pick", json={"request_id": "pick-1"}).status_code == 401
    assert api.delete("/api/run/olga-exe/override").status_code == 401


def test_pick_cancelled_passes_through(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sidecar.native_dialogs,
        "show_dialog",
        lambda kind, request_id, **kwargs: {"status": "cancelled"},
    )
    response = api.post(
        "/api/run/olga-exe/pick", json={"request_id": "pick-1"}, headers=_headers()
    )
    assert response.status_code == 200
    assert response.json() == {"status": "cancelled"}


def test_pick_selected_exe_is_saved_and_redetected(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "custom" / "opi.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("stub")
    monkeypatch.setattr(
        sidecar.native_dialogs,
        "show_dialog",
        lambda kind, request_id, **kwargs: {"status": "selected", "path": str(exe)},
    )
    monkeypatch.setattr(
        sidecar, "_selected_dialog_path", lambda result: Path(result["path"])
    )

    response = api.post(
        "/api/run/olga-exe/pick", json={"request_id": "pick-1"}, headers=_headers()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "selected"
    assert body["path"] == str(exe)
    assert body["detection"]["exe"] == str(exe)
    assert body["detection"]["source"] == "manual:settings"


def test_pick_rejects_non_exe(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = tmp_path / "case.genkey"
    case.write_text("CASE\n", encoding="utf-8")
    monkeypatch.setattr(
        sidecar.native_dialogs,
        "show_dialog",
        lambda kind, request_id, **kwargs: {"status": "selected", "path": str(case)},
    )
    monkeypatch.setattr(
        sidecar, "_selected_dialog_path", lambda result: Path(result["path"])
    )

    response = api.post(
        "/api/run/olga-exe/pick", json={"request_id": "pick-1"}, headers=_headers()
    )
    assert response.status_code == 400


def test_override_clear_returns_updated_detection(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion import config

    exe = tmp_path / "custom" / "opi.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("stub")
    config.save_olga_exe_override({"exe": str(exe)})

    first = api.delete("/api/run/olga-exe/override", headers=_headers()).json()
    assert first["cleared"] is True
    assert first["detection"]["source"] != "manual:settings"
    second = api.delete("/api/run/olga-exe/override", headers=_headers()).json()
    assert second["cleared"] is False
