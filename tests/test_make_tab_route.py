"""A missing PVTFILE is made from an .mfl in the case folder, only after the user's approve click."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olga_companion import multiflash_direct
from olga_companion.agent import session_token
from olga_companion.sidecar import app

client = TestClient(app)
FIX = Path(__file__).parent / "fixtures" / "multiflash"


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    (root / "case").mkdir(parents=True)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    shutil.copy(FIX / "gas_water.mfl", root / "case" / "gas_water.mfl")
    source = root / "case" / "pipe.genkey"
    source.write_text('CASE LABEL=c\nFILES PVTFILE="fluid.tab"\nENDCASE\n', encoding="utf-8")
    return source


def _engine(request: dict[str, Any]) -> dict[str, Any]:
    table = (FIX / "handwritten_3x3.tab").read_text(encoding="utf-8")
    Path(request["tab_path"]).write_text(table.replace("LABEL = probe", f"LABEL = {request['title']}", 1), encoding="utf-8")
    return {"ok": True, "errors": []}


def _post(body: dict[str, Any], token: bool = True) -> Any:
    headers = {"X-Session-Token": session_token.boot_token()} if token else {}
    return client.post("/api/fluids/make-tab", json=body, headers=headers)


def _use_fake_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    real = multiflash_direct.make_tab
    monkeypatch.setattr(multiflash_direct, "make_tab", lambda *a, **k: real(*a, **{**k, "engine": _engine}))


def test_candidates_list_the_mfl_files_in_the_case_folder(case: Path) -> None:
    response = client.get("/api/fluids/make-tab/candidates", params={"source": str(case)})
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["mfl"]] == ["gas_water.mfl"]


def test_approved_make_writes_the_referenced_table_next_to_the_case(case: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_fake_engine(monkeypatch)
    response = _post({"source": str(case), "reference": "fluid.tab", "mfl": "gas_water.mfl", "approved": True})
    assert response.status_code == 200, response.text
    assert (case.parent / "fluid.tab").is_file()
    body = response.json()
    assert body["valid"] is True and body["tab_name"] == "fluid.tab" and body["fluid_label"] == "GASWATER"
    assert "C:" not in str(body.get("link_proposal")) and str(case.parent) not in response.text


def test_nothing_is_made_without_approval_or_session(case: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_fake_engine(monkeypatch)
    body = {"source": str(case), "reference": "fluid.tab", "mfl": "gas_water.mfl"}
    assert _post({**body, "approved": False}).status_code == 400
    assert _post({**body, "approved": True}, token=False).status_code in (401, 403)
    assert not (case.parent / "fluid.tab").exists()


def test_the_reference_and_mfl_must_be_plain_names_in_the_case_folder(case: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_fake_engine(monkeypatch)
    for reference, mfl in (("../fluid.tab", "gas_water.mfl"), ("fluid.tab", "../gas_water.mfl"), ("fluid.tab", "missing.mfl")):
        response = _post({"source": str(case), "reference": reference, "mfl": mfl, "approved": True})
        assert response.status_code == 400, (reference, mfl)
    assert sorted(p.name for p in case.parent.iterdir()) == ["gas_water.mfl", "pipe.genkey"]


def test_an_engine_warning_comes_back_with_the_table(case: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = multiflash_direct.make_tab
    engine = lambda request: {**_engine(request), "ok": False, "errors": [-20573]}  # noqa: E731
    monkeypatch.setattr(multiflash_direct, "make_tab", lambda *a, **k: real(*a, **{**k, "engine": engine}))
    body = _post({"source": str(case), "reference": "fluid.tab", "mfl": "gas_water.mfl", "approved": True})
    assert body.status_code == 200
    assert "-20573" in body.json()["engine_warnings"][0]
