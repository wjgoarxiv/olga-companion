from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import native_dialogs, result_artifacts
from olga_companion.agent import session_token
from olga_companion.sidecar import app


def _registered_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, result_artifacts.ArtifactReceipt]:
    exports = tmp_path / "exports"
    artifact = exports / "results" / "request" / "series.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"time,value\n0,1\n")
    monkeypatch.setattr(result_artifacts, "exports_root", lambda: exports)
    receipt = result_artifacts.register(
        artifact,
        kind="csv",
        lineage={
            "source_kind": "workspace",
            "source_id": "workspace:source.tpl",
            "source_sha256": "a" * 64,
            "operation": "results_csv",
        },
        workspace_generation=1,
    )
    return artifact, receipt


def test_artifact_download_route_is_authenticated_and_hash_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one registered artifact and its authenticated local API.
    artifact, receipt = _registered_csv(tmp_path, monkeypatch)
    client = TestClient(app)

    # When / Then: an explicit session token is required even under TestClient.
    denied = client.get(f"/api/artifacts/{receipt['artifact_id']}/download")
    assert denied.status_code == 401
    downloaded = client.get(
        f"/api/artifacts/{receipt['artifact_id']}/download",
        headers={"x-session-token": session_token.boot_token()},
    )
    assert downloaded.status_code == 200
    assert downloaded.content == artifact.read_bytes()
    assert receipt["suggested_filename"] in downloaded.headers["content-disposition"]

    artifact.write_bytes(b"mutated")
    rejected = client.get(
        f"/api/artifacts/{receipt['artifact_id']}/download",
        headers={"x-session-token": session_token.boot_token()},
    )
    assert rejected.status_code == 400


def test_native_save_as_accepts_an_opaque_artifact_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid receipt whose private path only reaches the dialog adapter.
    artifact, receipt = _registered_csv(tmp_path, monkeypatch)
    observed: dict[str, Path | str] = {}

    def cancel_dialog(
        _kind: str,
        _request_id: str,
        *,
        initial_path: Path,
        suggested_name: str,
    ) -> dict[str, str]:
        observed.update(initial_path=initial_path, suggested_name=suggested_name)
        return {"status": "cancelled"}

    monkeypatch.setattr(native_dialogs, "show_dialog", cancel_dialog)

    # When: the frontend submits the opaque artifact reference to Save As.
    response = TestClient(app).post(
        "/api/native-dialogs/save-as",
        json={"request_id": "opaque-save", "artifact": f"artifact:{receipt['artifact_id']}"},
        headers={"x-session-token": session_token.boot_token()},
    )

    # Then: cancellation is truthful and no path is reflected publicly.
    assert response.status_code == 200
    assert response.json() == {"status": "cancelled"}
    assert observed == {"initial_path": artifact.parent, "suggested_name": artifact.name}
    assert str(artifact) not in response.text
