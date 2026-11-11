from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import config, workspace
from olga_companion.agent import tools
from olga_companion.sidecar import app


@pytest.fixture
def path_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    root = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    outside = tmp_path / "outside"
    root.mkdir()
    sandbox.mkdir()
    outside.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setattr(config, "sandbox_root", lambda: sandbox)
    return root, sandbox, outside


def test_input_resolver_allows_workspace_and_sandbox_but_rejects_external_and_symlink_escape(
    path_roots: tuple[Path, Path, Path],
) -> None:
    root, sandbox, outside = path_roots
    workspace_case = root / "workspace.genkey"
    sandbox_case = sandbox / "modified" / "sandbox.genkey"
    external_case = outside / "external.genkey"
    workspace_case.write_text("CASE LABEL=workspace\nENDCASE\n", encoding="utf-8")
    sandbox_case.parent.mkdir()
    sandbox_case.write_text("CASE LABEL=sandbox\nENDCASE\n", encoding="utf-8")
    external_case.write_text("CASE LABEL=external\nENDCASE\n", encoding="utf-8")

    assert workspace.resolve_input_file("workspace.genkey", {".genkey"}) == workspace_case.resolve()
    assert workspace.resolve_input_file(str(sandbox_case), {".genkey"}) == sandbox_case.resolve()
    with pytest.raises(workspace.WorkspaceError, match="workspace or app sandbox"):
        workspace.resolve_input_file(str(external_case), {".genkey"})

    link = root / "linked.genkey"
    try:
        link.symlink_to(external_case)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(workspace.WorkspaceError, match="workspace or app sandbox"):
        workspace.resolve_input_file("linked.genkey", {".genkey"})


@pytest.mark.parametrize(
    ("route", "body", "adapter_name"),
    [
        ("/api/genkey/review", lambda path: {"path": path}, "review_file"),
        ("/api/genkey/modify-copy", lambda path: {"source": path, "keyword": "INTEGRATION", "key": "ENDTIME", "value": "1 h"}, "modify_copy"),
        ("/api/fluids/inspect-tab", lambda path: {"path": path}, "inspect_tab"),
        ("/api/run/preview", lambda path: {"source": path}, "preview_run"),
    ],
)
def test_file_api_routes_reject_external_paths_before_adapter_dispatch(
    path_roots: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    body,
    adapter_name: str,
) -> None:
    _, _, outside = path_roots
    suffix = ".tab" if "fluids" in route else ".genkey"
    external = outside / f"external{suffix}"
    external.write_text("external", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        f"olga_companion.sidecar.{adapter_name}",
        lambda path, *args, **kwargs: calls.append(path) or {"unexpected": True},
    )

    response = TestClient(app).post(route, json=body(str(external)))

    assert response.status_code == 400
    assert calls == []


def test_sweep_preview_rejects_external_base_before_adapter_dispatch(
    path_roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, outside = path_roots
    external = outside / "external.genkey"
    external.write_text("external", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        "olga_companion.sweep_routes.preview_sweep",
        lambda base, *args, **kwargs: calls.append(base) or {"unexpected": True},
    )

    response = TestClient(app).post(
        "/api/sweep/preview",
        json={"base": str(external), "sweeps": ["INTEGRATION.ENDTIME=1 h,2 h"]},
    )

    assert response.status_code == 400
    assert calls == []


def test_agent_tool_rejects_external_case_before_adapter_dispatch(
    path_roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, outside = path_roots
    external = outside / "external.genkey"
    external.write_text("external", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        tools.genkey_static,
        "review_file",
        lambda path: calls.append(path) or {"unexpected": True},
    )

    with pytest.raises(tools.ToolError, match="workspace or app sandbox"):
        tools.dispatch("genkey_review", {"path": str(external)})

    assert calls == []
