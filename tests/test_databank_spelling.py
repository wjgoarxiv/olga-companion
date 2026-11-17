"""Formula and alias names resolve to real databank keys on every .mfl route."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import fluid_table
from olga_companion.agent import approvals, tools
from olga_companion.agent.tool_validation import ToolError
from olga_companion.pvt_engine.components import SUPPORTED_COMPONENTS
from olga_companion.sidecar import app

_DRAFT = {
    "fluid_label": "SYN1",
    "model": "SRK",
    "temperatures": [0.0, 50.0],
    "temperature_unit": "degC",
    "pressures": [1.0, 10.0],
    "pressure_unit": "bar",
    "mfl_rel": "synthetic.mfl",
}
_FAKE_BANK = {
    "METHANE": "METHANE",
    "CO2": "CARBON DIOXIDE",
    "IC4": "2-METHYLPROPANE",
    "NC4": "BUTANE",
    "PROPANE": "PROPANE",
    "ETHANE": "ETHANE",
    "ISOBUTANE": "2-METHYLPROPANE",
    "N-BUTANE": "BUTANE",
}


def _require_databank() -> None:
    if fluid_table.databank_path() is None:
        pytest.skip("Multiflash databank is unavailable here")


def _component_tokens(text: str) -> list[str]:
    block = text[text.lower().rindex("components overwrite"):].split("amounts", 1)[0]
    return re.findall(r"(?m)^\d+ (.+?)(?:\s*;)?[ \t]*$", block)


def _assert_databank_tokens(text: str, names: dict[str, str]) -> None:
    tokens = _component_tokens(text)
    assert tokens
    for token in tokens:
        assert " " not in token
        assert token.upper() in names


def _draft(**changes: object) -> dict:
    body = {**_DRAFT, "components": [{"name": "METHANE", "mole_fraction": 1.0}]}
    body.update(changes)
    return body


def _caused_by_unknown_component(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, fluid_table.UnknownComponentError):
            return True
        current = current.__cause__
    return False


def _approved(args: dict) -> dict:
    from olga_companion import workspace

    payload = tools.approval_payload("fluids_draft_mfl", args)
    token = approvals.mint(
        "fluids_draft_mfl", payload, context_generation=workspace.context_generation(),
    )["token"]
    return {**args, "approval_token": token, "idempotency_key": "k" * 32}


def test_fluid_table_does_not_import_the_engine_at_module_level() -> None:
    tree = ast.parse(Path(fluid_table.__file__).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert "pvt_engine" not in name


def test_known_databank_keys_stay_and_engine_aliases_map() -> None:
    names = dict(_FAKE_BANK)
    assert fluid_table.databank_spelling("CO2", names) == "CO2"
    assert fluid_table.databank_spelling("iC4", names) == "iC4"
    assert fluid_table.databank_spelling("nC4", names) == "nC4"
    assert fluid_table.databank_spelling("C3H8", names) == "PROPANE"
    assert fluid_table.databank_spelling("C2H6", names) == "ETHANE"
    assert fluid_table.databank_spelling("i-C4", names) == "ISOBUTANE"
    assert fluid_table.databank_spelling("n-C4", names) == "N-BUTANE"


def test_missing_engine_keeps_databank_names_and_rejects_formulas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(fluid_table, "databank_names", lambda *_a, **_k: dict(_FAKE_BANK))
    def template(model: str) -> str:
        fluid_table.validate_model(model)
        return "model stub;\n"

    monkeypatch.setattr(fluid_table, "template_text", template)
    monkeypatch.setitem(sys.modules, "olga_companion.pvt_engine.components", None)

    preview = tools.dispatch("fluids_draft_preview", _draft())
    assert "1 METHANE" in preview["mfl_text"]
    with pytest.raises(ToolError, match="Unknown component 'C3H8'") as raised:
        tools.dispatch("fluids_draft_preview", _draft(components=[{"name": "C3H8", "mole_fraction": 1.0}]))
    assert _caused_by_unknown_component(raised.value)

    with pytest.raises(ToolError, match="Unknown component 'C3H8'") as drafted:
        tools.dispatch("fluids_draft_mfl", {
            **_draft(components=[{"name": "C3H8", "mole_fraction": 1.0}]),
            "approval_token": "not-a-token",
            "idempotency_key": "k" * 32,
        })
    assert _caused_by_unknown_component(drafted.value)

    written = tools.dispatch("fluids_draft_mfl", _approved(_draft(mfl_rel="known.mfl")))
    assert "1 METHANE" in Path(tmp_path / "known.mfl").read_text(encoding="utf-8")
    assert written["mfl_path"]

    client = TestClient(app)
    ok = client.post("/api/fluids/draft-preview", json=_draft(mfl_rel="http.mfl"))
    assert ok.status_code == 200
    assert "1 METHANE" in ok.json()["mfl_text"]
    refused = client.post("/api/fluids/draft-preview", json=_draft(
        mfl_rel="http-c3.mfl", components=[{"name": "C3H8", "mole_fraction": 1.0}],
    ))
    assert refused.status_code == 400
    assert "Unknown component 'C3H8'" in refused.json()["detail"]
    assert "ImportError" not in refused.json()["detail"]


def test_real_databank_drafts_every_engine_component_for_each_model() -> None:
    _require_databank()
    names = fluid_table.databank_names()
    share = 1.0 / len(SUPPORTED_COMPONENTS)
    for model in ("PR", "PRA", "SRK"):
        for engine_name in SUPPORTED_COMPONENTS:
            spelled = fluid_table.databank_spelling(engine_name, names)
            text = fluid_table.build_mfl_text(
                fluid_label="SYN",
                components=[{"name": spelled, "mole_fraction": 1.0}],
                model=model,
                temperatures=[0.0, 50.0],
                temperature_unit="degC",
                pressures=[1.0, 100.0],
                pressure_unit="bar",
                tab_abs_path="/mnt/c/Temp/syn_mf.tab",
                databank_names=names,
            )
            _assert_databank_tokens(text, names)
        mixture = [
            {"name": fluid_table.databank_spelling(engine_name, names), "mole_fraction": share}
            for engine_name in SUPPORTED_COMPONENTS
        ]
        mixed = fluid_table.build_mfl_text(
            fluid_label="SYNMIX",
            components=mixture,
            model=model,
            temperatures=[0.0, 50.0],
            temperature_unit="degC",
            pressures=[1.0, 100.0],
            pressure_unit="bar",
            tab_abs_path="/mnt/c/Temp/mix_mf.tab",
            databank_names=names,
        )
        tokens = _component_tokens(mixed)
        assert len(tokens) == len(SUPPORTED_COMPONENTS)
        _assert_databank_tokens(mixed, names)
    for alias, engine_name in (("i-C4", "iC4"), ("n-C4", "nC4")):
        spelled = fluid_table.databank_spelling(alias, names)
        assert spelled.upper() in names
        assert names[spelled.upper()] == names[engine_name.upper()]


def test_preview_accepts_c3h8_from_the_real_databank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_databank()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    result = tools.dispatch("fluids_draft_preview", _draft(
        components=[{"name": "C3H8", "mole_fraction": 1.0}], model="PR",
    ))
    names = fluid_table.databank_names()
    _assert_databank_tokens(result["mfl_text"], names)
    assert "PROPANE" in _component_tokens(result["mfl_text"])
    assert "C3H8" not in _component_tokens(result["mfl_text"])


def test_draft_mfl_accepts_c3h8_from_the_real_databank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_databank()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    tools.dispatch("fluids_draft_mfl", _approved(_draft(
        components=[{"name": "C3H8", "mole_fraction": 1.0}], model="PR", mfl_rel="c3.mfl",
    )))
    text = (tmp_path / "c3.mfl").read_text(encoding="utf-8")
    names = fluid_table.databank_names()
    _assert_databank_tokens(text, names)
    assert "PROPANE" in _component_tokens(text)
    assert "C3H8" not in _component_tokens(text)


def test_api_preview_accepts_c3h8_from_the_real_databank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_databank()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    response = TestClient(app).post("/api/fluids/draft-preview", json=_draft(
        components=[{"name": "C3H8", "mole_fraction": 1.0}], model="PR", mfl_rel="c3.mfl",
    ))
    assert response.status_code == 200
    text = response.json()["mfl_text"]
    names = fluid_table.databank_names()
    _assert_databank_tokens(text, names)
    assert "PROPANE" in _component_tokens(text)
    assert "C3H8" not in _component_tokens(text)
