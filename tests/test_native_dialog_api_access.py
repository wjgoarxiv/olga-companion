from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import config, native_dialogs, workspace
from olga_companion.agent import approvals

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


@pytest.mark.parametrize(
    "route,body",
    [
        (
            "/api/native-dialogs/workspace",
            {"request_id": "pick-root", "context_generation": 0},
        ),
        (
            "/api/native-dialogs/open-case",
            {"request_id": "pick-case", "context_generation": 0},
        ),
        (
            "/api/native-dialogs/save-as",
            {"request_id": "save-export", "artifact": "forged"},
        ),
        ("/api/native-dialogs/cancel", {"request_id": "cancel-one"}),
    ],
)
def test_native_dialog_endpoints_require_session_token(route: str, body: dict) -> None:
    assert client.post(route, json=body).status_code == 401
    assert (
        client.post(route, json=body, headers={"X-Session-Token": "forged"}).status_code
        == 401
    )


def test_dialog_request_models_forbid_extra_and_malformed_ids(token: str) -> None:
    extra = client.post(
        "/api/native-dialogs/workspace",
        json={
            "request_id": "valid-id",
            "context_generation": 0,
            "path": "/attacker/chosen",
        },
        headers=_headers(token),
    )
    malformed = client.post(
        "/api/native-dialogs/open-case",
        json={"request_id": "../escape", "context_generation": 0},
        headers=_headers(token),
    )
    assert extra.status_code == 422
    assert malformed.status_code == 422


def test_choose_workspace_switches_through_safe_context_and_revokes_approvals(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    (old_root / "old.genkey").write_text("old")
    (new_root / "new.genkey").write_text("new")
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(old_root))
    workspace.set_active_rel("old.genkey")
    approval = approvals.mint("run_execute", {"source": "old"})
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda kind, request_id, **kwargs: {
            "status": "selected",
            "path": str(new_root.resolve()),
        },
    )

    response = client.post(
        "/api/native-dialogs/workspace",
        json={
            "request_id": "choose-root",
            "context_generation": workspace.context_generation(),
        },
        headers=_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "selected"
    assert body["root"] == str(new_root.resolve())
    assert [case["name"] for case in body["cases"]] == ["new.genkey"]
    assert body["active"] == {"name": None, "path": None}
    assert body["generation"] == 1
    assert body["revoked"] == 1
    with pytest.raises(approvals.ApprovalError):
        approvals.consume(approval["token"], "run_execute", {"source": "old"})


@pytest.mark.parametrize("suffix", [".txt", ".GENKEY.bak"])
def test_open_case_refuses_non_case_selection(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    selected = tmp_path / f"not-a-case{suffix}"
    selected.write_text("x")
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(selected)},
    )

    response = client.post(
        "/api/native-dialogs/open-case",
        json={
            "request_id": "bad-case",
            "context_generation": workspace.context_generation(),
        },
        headers=_headers(token),
    )

    assert response.status_code == 400


def test_open_case_atomically_switches_parent_then_activates_case(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old"
    selected_dir = tmp_path / "selected"
    old.mkdir()
    selected_dir.mkdir()
    selected = selected_dir / "모델 case.genkey"
    selected.write_text("case")
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(old))
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(selected)},
    )

    response = client.post(
        "/api/native-dialogs/open-case",
        json={
            "request_id": "open-case-1",
            "context_generation": workspace.context_generation(),
        },
        headers=_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "selected"
    assert body["root"] == str(selected_dir.resolve())
    assert body["active"]["name"] == selected.name
    assert body["generation"] == 1
    assert body["revoked"] == 0


def test_context_dialog_requests_require_nonnegative_strict_generation(
    token: str,
) -> None:
    for route in ("/api/native-dialogs/workspace", "/api/native-dialogs/open-case"):
        assert (
            client.post(
                route, json={"request_id": "missing"}, headers=_headers(token)
            ).status_code
            == 422
        )
        assert (
            client.post(
                route,
                json={"request_id": "negative", "context_generation": -1},
                headers=_headers(token),
            ).status_code
            == 422
        )
        assert (
            client.post(
                route,
                json={"request_id": "boolean", "context_generation": True},
                headers=_headers(token),
            ).status_code
            == 422
        )
