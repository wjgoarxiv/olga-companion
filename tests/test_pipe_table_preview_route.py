"""The pipe-table wizard's preview: read a workspace table, write nothing.

The wizard (plan item 13) shows what the table holds and which END nodes still need
values, before anything is saved. Saving stays with the chat approval card; this route
never makes a draft, a case or a file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion.sidecar import app

_PIPES = (
    "라인,시작점,끝점,길이 (m),고도차 (m),내경 (mm),조도 (mm)\n"
    "1번 유정,유정A,합류점,500,-5,150,0.045\n2번 유정,유정B,합류점,600,10,150,0.045\n"
    "본선,합류점,분리기,1500,25,250,0.045\n"
)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "net.csv").write_text(_PIPES, encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    monkeypatch.setenv("OLGA_CASE_DRAFT_DIR", str(tmp_path / "drafts"))
    return workspace_root


def _files(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root.parent)) for path in root.parent.rglob("*"))


def test_the_preview_lists_lines_and_the_end_nodes_that_need_values(root: Path) -> None:
    before = _files(root)
    response = TestClient(app).post("/api/pipe-table/preview", json={"path": "net.csv"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lines"] == ["1번 유정", "2번 유정", "본선"]
    assert body["pipes"] == 3
    assert {end["node"]: end["has_values"] for end in body["ends"]} == {"유정A": False, "유정B": False, "분리기": False}
    assert body["junctions"] == ["합류점"]
    assert body["issues"] == []
    assert _files(root) == before


def test_an_end_node_with_a_table_row_is_marked_as_given(root: Path) -> None:
    (root / "net.csv").write_text(
        _PIPES.replace("조도 (mm)\n", "조도 (mm),노드,노드 종류,압력 (bar),온도 (C),가스 분율,물 분율\n")
        .replace(",0.045\n", ",0.045,,,,,,\n") + ",,,,,,,분리기,sink,8,30,1,0.9\n",
        encoding="utf-8",
    )
    body = TestClient(app).post("/api/pipe-table/preview", json={"path": "net.csv"}).json()
    given = {end["node"]: end["has_values"] for end in body["ends"]}
    assert given == {"유정A": False, "유정B": False, "분리기": True}


def test_a_path_outside_the_workspace_is_refused(root: Path) -> None:
    (root.parent / "outside.csv").write_text(_PIPES, encoding="utf-8")
    response = TestClient(app).post("/api/pipe-table/preview", json={"path": str(root.parent / "outside.csv")})
    assert response.status_code == 400


def test_the_wizard_lists_the_workspace_tables(root: Path) -> None:
    (root / "sub").mkdir()
    (root / "sub" / "lines.xlsx").write_bytes(b"")
    (root / "notes.txt").write_text("x", encoding="utf-8")
    response = TestClient(app).get("/api/pipe-table/list")
    assert response.status_code == 200, response.text
    assert sorted(entry["rel"] for entry in response.json()["tables"]) == ["net.csv", "sub/lines.xlsx"]


def test_a_table_with_pipe_names_but_no_line_column_says_so_before_the_chat(root: Path) -> None:
    (root / "net.csv").write_text(
        _PIPES.replace("라인,", "배관,", 1), encoding="utf-8",
    )
    body = TestClient(app).post("/api/pipe-table/preview", json={"path": "net.csv"}).json()
    assert body["lines"] == []
    assert [(issue["row"], issue["code"]) for issue in body["issues"]] == [
        (2, "missing_flowpath"), (3, "missing_flowpath"), (4, "missing_flowpath"),
    ]


def test_a_table_with_problems_lists_them_instead_of_failing(root: Path) -> None:
    (root / "net.csv").write_text("라인,시작점,끝점\nA,S,T\n", encoding="utf-8")
    body = TestClient(app).post("/api/pipe-table/preview", json={"path": "net.csv"}).json()
    assert body["issues"], body
