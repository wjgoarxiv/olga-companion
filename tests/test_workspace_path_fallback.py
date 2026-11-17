"""A relative path the assistant guessed wrongly still finds the one file it meant.

Live PVT 2026-11-16 (hr01): the CSV sat at the workspace root, but the assistant passed
`olga-hyperreal-qa/hr01_pipes.csv` (the root's own folder name in front) and
`data/hr01_pipes.csv`, and each try failed with "input file not found" and no hint. Three
tool calls went by before it listed the files.
"""
from __future__ import annotations

import pytest

from olga_companion import workspace


@pytest.fixture()
def rooted(tmp_path, monkeypatch):
    root = tmp_path / "olga-hyperreal-qa"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    return root


def _file(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Line,From,To\n", encoding="utf-8")
    return path.resolve()


def test_the_root_folder_name_in_front_is_dropped(rooted):
    table = _file(rooted / "hr01_pipes.csv")
    assert workspace.resolve_input_file("olga-hyperreal-qa/hr01_pipes.csv", {".csv"}) == table


def test_a_wrong_folder_falls_back_to_the_one_file_of_that_name(rooted):
    table = _file(rooted / "tables" / "hr01_pipes.csv")
    assert workspace.resolve_input_file("data/hr01_pipes.csv", {".csv"}) == table


def test_two_files_of_that_name_are_still_refused(rooted):
    _file(rooted / "a" / "hr01_pipes.csv")
    _file(rooted / "b" / "hr01_pipes.csv")
    with pytest.raises(workspace.WorkspaceError, match="more than one file"):
        workspace.resolve_input_file("data/hr01_pipes.csv", {".csv"})


def test_a_path_that_climbs_out_is_still_refused(rooted):
    _file(rooted.parent / "hr01_pipes.csv")
    with pytest.raises(workspace.WorkspaceError):
        workspace.resolve_input_file("../hr01_pipes.csv", {".csv"})


def test_a_miss_names_the_files_of_that_type(rooted):
    _file(rooted / "hr01_pipes.csv")
    _file(rooted / "lines" / "other.csv")
    with pytest.raises(workspace.WorkspaceError) as caught:
        workspace.resolve_input_file("pipes.csv", {".csv"})
    message = str(caught.value)
    assert "input file not found" in message
    assert "hr01_pipes.csv" in message and "lines/other.csv" in message
