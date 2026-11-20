"""Approval-gated copy of a chosen .tab to the exact reference name a case expects.

Owner decision 2026-11-16 (B): a PVTFILE the run cannot find from the case folder is fixed by
copying a workspace .tab next to the case under the referenced relative name, only after the
user approves; nothing is copied before that and nothing is ever overwritten.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from olga_companion import config, run_companion_copy, runner, workspace
from olga_companion.agent import approvals, session_token
from olga_companion.sidecar import app
from olga_runtime_test_support import _installed_release

client = TestClient(app)
TAB_TEXT = "PVTTABLE LABEL = A\nPVTTABLE POINT = ( 1.0 , 2.0 )\n"


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    root = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    outside = tmp_path / "outside"
    for folder in (root, sandbox, outside):
        folder.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setattr(config, "sandbox_root", lambda: sandbox)
    return root, sandbox, outside


def _case(root: Path, *references: str, folder: str = "case") -> Path:
    case_dir = root / folder
    case_dir.mkdir(parents=True, exist_ok=True)
    lines = "".join(f'FILES PVTFILE="{reference}"\n' for reference in references)
    case = case_dir / "case.genkey"
    case.write_text(f"CASE LABEL=case\n{lines}ENDCASE\n", encoding="utf-8")
    return case


def _tab(root: Path, name: str = "library/air.tab") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TAB_TEXT, encoding="utf-8")
    return path


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def _body(case: Path, reference: str, tab: Path, **extra: object) -> dict[str, object]:
    return {"source": str(case), "reference": reference, "tab_source": str(tab), **extra}


def _reviewed(tab: Path) -> dict[str, object]:
    data = tab.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def _copy(case: Path, reference: str, tab: Path, **reviewed: object) -> object:
    return client.post(
        "/api/run/companion-copy/execute",
        json=_body(case, reference, tab, approved=True, **(reviewed or _reviewed(tab))),
        headers=_headers(),
    )


def test_an_approved_copy_lands_at_the_referenced_name_with_matching_bytes(roots) -> None:
    root, _, _ = roots
    case = _case(root, "air_water.tab")
    tab = _tab(root)

    response = _copy(case, "air_water.tab", tab)

    assert response.status_code == 200, response.text
    destination = root / "case" / "air_water.tab"
    assert destination.read_bytes() == tab.read_bytes()
    body = response.json()
    assert body["ok"] is True
    assert body["sha256"] == hashlib.sha256(tab.read_bytes()).hexdigest()
    assert body["reference"] == "air_water.tab"
    assert tab.read_text(encoding="utf-8") == TAB_TEXT


def test_a_nested_reference_creates_its_subfolders(roots) -> None:
    root, _, _ = roots
    case = _case(root, "fluids/deep/air_water.tab")
    tab = _tab(root)

    assert _copy(case, "fluids/deep/air_water.tab", tab).status_code == 200
    assert (root / "case" / "fluids" / "deep" / "air_water.tab").read_bytes() == tab.read_bytes()


def test_the_preview_route_describes_the_copy_and_writes_nothing(roots) -> None:
    root, _, _ = roots
    case = _case(root, "fluids/air_water.tab")
    tab = _tab(root)

    response = client.post("/api/run/companion-copy/preview", json=_body(case, "fluids/air_water.tab", tab))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reference"] == "fluids/air_water.tab"
    assert body["tab_source"] == "library/air.tab"
    assert body["copy_to"] == "case/fluids/air_water.tab"
    assert body["sha256"] == hashlib.sha256(tab.read_bytes()).hexdigest()
    assert not (root / "case" / "fluids").exists()


@pytest.mark.parametrize(
    "reference",
    ["../elsewhere/air_water.tab", "fluids/../../air_water.tab", "..\\air_water.tab", "C:\\fluids\\air_water.tab"],
)
def test_a_reference_that_escapes_the_case_folder_is_refused(roots, reference: str) -> None:
    root, _, outside = roots
    case = _case(root, reference)
    tab = _tab(root)

    response = _copy(case, reference, tab)

    assert response.status_code == 400
    assert not (root / "elsewhere").exists()
    assert not (outside / "air_water.tab").exists()
    assert not (root / "air_water.tab").exists()


def test_an_absolute_reference_is_refused(roots) -> None:
    root, _, outside = roots
    absolute = str(outside / "air_water.tab")
    case = _case(root, absolute)
    tab = _tab(root)

    assert _copy(case, absolute, tab).status_code == 400
    assert not (outside / "air_water.tab").exists()


def test_an_existing_destination_is_refused_and_left_untouched(roots) -> None:
    root, _, _ = roots
    case = _case(root, "air_water.tab")
    tab = _tab(root)
    (root / "case" / "air_water.tab").write_text("owner file\n", encoding="utf-8")

    response = _copy(case, "air_water.tab", tab)

    assert response.status_code == 400
    assert "already exists" in response.text
    assert (root / "case" / "air_water.tab").read_text(encoding="utf-8") == "owner file\n"


def test_a_source_outside_the_workspace_is_refused(roots) -> None:
    root, _, outside = roots
    case = _case(root, "air_water.tab")
    foreign = outside / "foreign.tab"
    foreign.write_text(TAB_TEXT, encoding="utf-8")

    response = _copy(case, "air_water.tab", foreign)

    assert response.status_code == 400
    assert not (root / "case" / "air_water.tab").exists()


def test_a_source_in_the_app_sandbox_is_accepted(roots) -> None:
    root, sandbox, _ = roots
    case = _case(root, "air_water.tab")
    staged = sandbox / "runs" / "r1" / "staged.tab"
    staged.parent.mkdir(parents=True)
    staged.write_text(TAB_TEXT, encoding="utf-8")

    assert _copy(case, "air_water.tab", staged).status_code == 200


def test_a_source_that_is_not_a_tab_is_refused(roots) -> None:
    root, _, _ = roots
    case = _case(root, "air_water.tab")
    other = root / "notes.txt"
    other.write_text("not a table\n", encoding="utf-8")

    assert _copy(case, "air_water.tab", other).status_code == 400
    assert not (root / "case" / "air_water.tab").exists()


def test_a_reference_the_case_does_not_make_is_refused(roots) -> None:
    root, _, _ = roots
    case = _case(root, "air_water.tab")
    tab = _tab(root)

    assert _copy(case, "other.tab", tab).status_code == 400
    assert not (root / "case" / "other.tab").exists()


def test_a_reference_that_is_not_a_tab_is_refused(roots) -> None:
    root, _, _ = roots
    case = _case(root, "air_water.txt")
    tab = _tab(root)

    assert _copy(case, "air_water.txt", tab).status_code == 400


def test_nothing_is_copied_without_approval(roots) -> None:
    root, _, _ = roots
    case = _case(root, "fluids/air_water.tab")
    tab = _tab(root)
    body = _body(case, "fluids/air_water.tab", tab)

    refused = client.post("/api/run/companion-copy/execute", json=body, headers=_headers())
    unapproved = client.post(
        "/api/run/companion-copy/execute", json={**body, "approved": False}, headers=_headers()
    )
    no_session = client.post("/api/run/companion-copy/execute", json={**body, "approved": True})

    assert refused.status_code == 400
    assert unapproved.status_code == 400
    assert no_session.status_code == 401
    assert not (root / "case" / "fluids").exists()


def test_the_handler_itself_needs_a_token_bound_to_this_exact_copy(roots) -> None:
    root, _, _ = roots
    case = _case(root, "air_water.tab")
    tab = _tab(root)
    request = {"source": str(case), "reference": "air_water.tab", "tab_source": str(tab)}

    with pytest.raises(approvals.ApprovalError):
        run_companion_copy.execute({**request, "approval_token": ""})
    with pytest.raises(approvals.ApprovalError):
        run_companion_copy.execute({**request, "approval_token": "not-a-minted-token"})
    other = approvals.mint(
        "run_companion_copy", {"unrelated": "payload"}, context_generation=workspace.context_generation()
    )["token"]
    with pytest.raises(approvals.ApprovalError):
        run_companion_copy.execute({**request, "approval_token": other})
    assert not (root / "case" / "air_water.tab").exists()


def test_a_tab_that_changed_after_the_preview_is_not_copied(roots) -> None:
    root, _, _ = roots
    case = _case(root, "air_water.tab")
    tab = _tab(root)
    request = {"source": str(case), "reference": "air_water.tab", "tab_source": str(tab)}
    planned = run_companion_copy.plan(**request)
    token = approvals.mint(
        "run_companion_copy", planned["approved_payload"], context_generation=workspace.context_generation()
    )["token"]
    tab.write_text(TAB_TEXT + "PVTTABLE POINT = ( 3.0 , 4.0 )\n", encoding="utf-8")

    with pytest.raises(approvals.ApprovalError):
        run_companion_copy.execute({**request, "approval_token": token})
    assert not (root / "case" / "air_water.tab").exists()


def test_the_execute_route_refuses_a_tab_that_changed_since_the_preview(roots) -> None:
    root, _, _ = roots
    case = _case(root, "air_water.tab")
    tab = _tab(root)
    previewed = client.post("/api/run/companion-copy/preview", json=_body(case, "air_water.tab", tab)).json()
    tab.write_text(TAB_TEXT + "PVTTABLE POINT = ( 3.0 , 4.0 )\n", encoding="utf-8")

    changed = _copy(case, "air_water.tab", tab, sha256=previewed["sha256"], size=previewed["size"])
    missing = client.post(
        "/api/run/companion-copy/execute",
        json=_body(case, "air_water.tab", tab, approved=True),
        headers=_headers(),
    )

    assert changed.status_code == 400
    assert "changed after the preview" in changed.json()["detail"]
    assert missing.status_code == 400
    assert not (root / "case" / "air_water.tab").exists()


def test_the_execute_route_copies_the_previewed_bytes(roots) -> None:
    root, _, _ = roots
    case = _case(root, "air_water.tab")
    tab = _tab(root)
    previewed = client.post("/api/run/companion-copy/preview", json=_body(case, "air_water.tab", tab)).json()

    response = _copy(case, "air_water.tab", tab, sha256=previewed["sha256"], size=previewed["size"])

    assert response.status_code == 200, response.text
    assert (root / "case" / "air_water.tab").read_bytes() == tab.read_bytes()


def test_a_symlinked_folder_that_leaves_the_case_is_refused(roots) -> None:
    root, _, outside = roots
    case = _case(root, "linked/air_water.tab")
    tab = _tab(root)
    try:
        (root / "case" / "linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    assert _copy(case, "linked/air_water.tab", tab).status_code == 400
    assert not (outside / "air_water.tab").exists()


def test_a_following_run_preview_reports_the_reference_as_found(
    roots, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _, _ = roots
    installs = tmp_path / "installs"
    _installed_release(installs, "2025.1.0", opi=False)
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(runner, "OLGA_EXE_GLOBS", [str(installs / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe")])
    monkeypatch.setattr(runner, "_validate_case", lambda _path: {"valid": True, "command": {}})
    monkeypatch.setattr(
        runner, "ensure_broker", lambda: SimpleNamespace(to_dict=lambda: {"protocol": "test", "sha256": "b" * 64})
    )
    case = _case(root, "fluids/air_water.tab")
    tab = _tab(root)

    before = runner.preview_run(str(case))
    assert before["companions_missing"] == ["fluids/air_water.tab"]

    assert _copy(case, "fluids/air_water.tab", tab).status_code == 200

    after = runner.preview_run(str(case))
    assert after["companions_missing"] == []
    assert [item["found"] for item in after["companions"]] == [True]
