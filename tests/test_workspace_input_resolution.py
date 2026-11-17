"""Contract for resolving a case the inventory listed from a subfolder.

The workspace inventory walks recursively, so the UI can surface — and make
active — a case that does not sit at the workspace root. Tools are then handed
the displayed file name, so bare-name resolution has to reach those cases while
keeping every containment guarantee.
"""
from __future__ import annotations

import pytest

from olga_companion import workspace


@pytest.fixture()
def rooted(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    return tmp_path


def _case(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ENDCASE\n", encoding="utf-8")
    return path


def test_bare_name_resolves_a_case_stored_in_a_subfolder(rooted):
    nested = _case(rooted / "smoke_run" / "smoke_pipeline.genkey")

    resolved = workspace.resolve_input_file("smoke_pipeline.genkey", {".genkey"})

    assert resolved == nested.resolve()


def test_root_level_case_and_explicit_relative_path_still_resolve(rooted):
    root_case = _case(rooted / "demo.genkey")
    nested = _case(rooted / "nested" / "deep.genkey")

    assert workspace.resolve_input_file("demo.genkey", {".genkey"}) == root_case.resolve()
    assert (
        workspace.resolve_input_file("nested/deep.genkey", {".genkey"})
        == nested.resolve()
    )


def test_duplicate_names_are_reported_instead_of_guessed(rooted):
    _case(rooted / "a" / "case.genkey")
    _case(rooted / "b" / "case.genkey")

    with pytest.raises(workspace.WorkspaceError, match="more than one file"):
        workspace.resolve_input_file("case.genkey", {".genkey"})


def test_missing_case_still_reports_not_found(rooted):
    with pytest.raises(workspace.WorkspaceError, match="not found"):
        workspace.resolve_input_file("absent.genkey", {".genkey"})


def test_traversal_outside_the_workspace_is_still_rejected(rooted):
    _case(rooted.parent / "escape.genkey")

    with pytest.raises(workspace.WorkspaceError, match="stay inside"):
        workspace.resolve_input_file("../escape.genkey", {".genkey"})


def test_bare_name_lookup_does_not_bypass_the_suffix_allowlist(rooted):
    _case(rooted / "sub" / "notes.txt")

    with pytest.raises(workspace.WorkspaceError):
        workspace.resolve_input_file("notes.txt", {".genkey"})
