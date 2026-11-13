"""Bundled examples install into a workspace and pass the app validator."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from olga_companion import workspace
from olga_companion.agent import session_token
from olga_companion.examples import (
    classify_topology,
    install_example,
    list_examples,
)
from olga_companion.genkey_static import ALLOWED_TOPOLOGIES, review_file
from olga_companion.sidecar import app


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(workspace, "_active_state_path", lambda: tmp_path / "active.json")
    return tmp_path


def test_public_catalog_keeps_only_admitted_examples() -> None:
    listed = list_examples()
    assert [item["id"] for item in listed] == ["air-water-horizontal", "simple-pipeline"]
    assert listed[0]["demo"] is True
    assert listed[1]["topology"] == "simple_pipeline"
    assert all(item["fluid"] == "AIR_WATER" for item in listed)
    reasons = {name: classify_topology(name) for name in sorted(ALLOWED_TOPOLOGIES)}
    assert reasons["simple_pipeline"] == "admitted"
    assert reasons["production_well"] == "out_of_table_range"
    assert reasons["riser"] == "out_of_table_range"
    assert reasons["separator"] == "out_of_table_range"
    assert reasons["subsea_tieback"] == "out_of_table_range"
    assert reasons["well_pipeline"] == "out_of_table_range"
    assert "production_well" not in {item["topology"] for item in listed}


@pytest.mark.parametrize("example_id", ["air-water-horizontal", "simple-pipeline"])
def test_install_writes_a_free_pair_and_validates(ws, example_id: str) -> None:
    installed = install_example(example_id)
    case_path = ws / installed["case_rel"]
    table_path = ws / installed["table_rel"]
    assert case_path.is_file()
    assert table_path.is_file()
    assert table_path.read_bytes()[:20]
    reviewed = review_file(str(case_path))
    assert reviewed["valid"] is True, reviewed["validation"]
    assert workspace.active()["name"] == installed["case_name"]
    assert installed["case_name"] == case_path.name
    assert installed["next"] == "validate"


def test_install_never_overwrites_an_existing_name(ws) -> None:
    (ws / "air_water_horizontal.genkey").write_text("keep-case\n", encoding="utf-8")
    (ws / "air_water.tab").write_text("keep-table\n", encoding="utf-8")
    installed = install_example("air-water-horizontal")
    assert (ws / "air_water_horizontal.genkey").read_text(encoding="utf-8") == "keep-case\n"
    assert (ws / "air_water.tab").read_text(encoding="utf-8") == "keep-table\n"
    assert installed["case_rel"] != "air_water_horizontal.genkey"
    assert installed["table_rel"] != "air_water.tab"
    assert review_file(str(ws / installed["case_rel"]))["valid"] is True


def test_installed_table_bytes_match_the_bundle_and_the_write_is_binary(ws, monkeypatch) -> None:
    import inspect
    import os

    from olga_companion import starter_fluids
    from olga_companion.examples import _place

    seen: list[int] = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *args, **kwargs):
        seen.append(flags)
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    installed = install_example("air-water-horizontal")
    payload = starter_fluids.bundled_table().read_bytes()
    assert (ws / installed["table_rel"]).read_bytes() == payload
    assert "O_BINARY" in inspect.getsource(_place)
    binary = getattr(os, "O_BINARY", 0)
    assert binary == 0 or any(flags & binary for flags in seen)


def test_second_install_reuses_an_identical_air_water_table(ws) -> None:
    first = install_example("air-water-horizontal")
    second = install_example("simple-pipeline")
    tables = sorted(path.name for path in ws.glob("air_water*.tab"))
    assert tables == [first["table_rel"]]
    assert second["table_rel"] == first["table_rel"]
    assert review_file(str(ws / second["case_rel"]))["valid"] is True


def test_unwritable_workspace_is_an_input_error_without_a_path(ws, monkeypatch) -> None:
    from olga_companion.examples import ExampleError

    def boom(*_args, **_kwargs):
        raise OSError(13, "Permission denied", str(ws / "air_water.tab"))

    monkeypatch.setattr("olga_companion.examples._place", boom)
    with pytest.raises(ExampleError, match="not writable") as raised:
        install_example("air-water-horizontal")
    text = str(raised.value)
    assert str(ws) not in text
    assert "air_water" not in text
    assert list(ws.glob("*.genkey")) == []


def test_admission_does_not_cache_a_transient_oserror(monkeypatch) -> None:
    from olga_companion import examples

    examples._ADMITTED.clear()
    calls = {"n": 0}
    real = examples._case_spec_text

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("temporary")
        return real(*args, **kwargs)

    monkeypatch.setattr(examples, "_case_spec_text", flaky)
    first = [item["id"] for item in list_examples()]
    assert "air-water-horizontal" not in first
    second = [item["id"] for item in list_examples()]
    assert "air-water-horizontal" in second


def test_unknown_example_writes_nothing(ws) -> None:
    from olga_companion.examples import ExampleError

    with pytest.raises(ExampleError):
        install_example("not-a-real-example")
    assert list(ws.glob("*.genkey")) == []
    assert list(ws.glob("*.tab")) == []


def test_examples_api_installs_the_demo_and_rejects_a_missing_token(ws) -> None:
    token = session_token.boot_token()
    client = TestClient(app)
    listed = client.get("/api/examples")
    assert listed.status_code == 200
    assert listed.json()["examples"][0]["id"] == "air-water-horizontal"
    denied = client.post("/api/examples/install", json={"id": "air-water-horizontal"})
    assert denied.status_code == 401
    accepted = client.post(
        "/api/examples/install",
        json={"id": "air-water-horizontal"},
        headers={"X-Session-Token": token},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["demo"] is True
    assert (ws / body["case_rel"]).is_file()
    assert workspace.active()["name"] == body["case_name"]
