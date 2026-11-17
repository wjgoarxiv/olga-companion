"""Engine licence, origin wording, and the companion .mfl written with a generated table."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from olga_companion import config, fluid_table, workspace
from olga_companion.agent import approval_display, approvals, pending_approvals, session_token, tool_schemas, tools
from olga_companion.agent.tool_validation import ToolError
from olga_companion.pvt_engine import generate_table

FLAG = "OLGA_COMPANION_NATIVE_TAB"
ROOT = Path(__file__).resolve().parents[1]
TOOL = "fluids_generate_tab"
DISCLAIMER = (
    "Independent table, not Multiflash-identical. Not qualified for OLGA use; compare before relying on it."
)
GEN: dict[str, Any] = {
    "fluid_label": "SYN_CO2",
    "components": [
        {"name": "CO2", "mole_fraction": 0.95},
        {"name": "N2", "mole_fraction": 0.03},
        {"name": "CH4", "mole_fraction": 0.02},
    ],
    "model": "PR",
    "temperatures": [10, 20],
    "temperature_unit": "degC",
    "pressures": [10, 20],
    "pressure_unit": "bar",
    "tab_rel": "syn_co2.tab",
}
_NAMES = {
    "CARBON DIOXIDE": "CARBON DIOXIDE",
    "CO2": "CARBON DIOXIDE",
    "NITROGEN": "NITROGEN",
    "N2": "NITROGEN",
    "METHANE": "METHANE",
    "CH4": "METHANE",
    # The real databank knows propane and ethane as C3/C2, not by formula.
    "PROPANE": "PROPANE",
    "C3": "PROPANE",
    "ETHANE": "ETHANE",
    "C2": "ETHANE",
}


def _gen(**changes: Any) -> dict[str, Any]:
    return {**json.loads(json.dumps(GEN)), **changes}


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setattr(tools, "TOOLS", tool_schemas.build_tools(tools._HANDLERS))
    session_token.boot_token()
    pending_approvals.revoke_all()
    yield workspace_root
    pending_approvals.revoke_all()


def _approved(args: dict[str, Any]) -> dict[str, Any]:
    payload = tools.approval_payload(TOOL, args)
    token = approvals.mint(TOOL, payload, context_generation=workspace.context_generation())["token"]
    return {**args, "approval_token": token, "idempotency_key": "k" * 32}


def _stub_draft(monkeypatch: pytest.MonkeyPatch, seen: list[str] | None = None) -> None:
    monkeypatch.setattr(fluid_table, "databank_names", lambda *_a, **_k: dict(_NAMES))

    def template(model: str) -> str:
        if seen is not None:
            seen.append(model)
        fluid_table.validate_model(model)
        return "model stub;\n"

    monkeypatch.setattr(fluid_table, "template_text", template)


def test_engine_folder_carries_an_mit_licence() -> None:
    text = (ROOT / "src" / "olga_companion" / "pvt_engine" / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "2026 Woojin Go" in text
    assert "Permission is hereby granted, free of charge" in text


def test_readme_splits_mit_engine_from_apache_and_drops_the_old_licence_wording() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    licence = readme[readme.index("## License"):]
    assert "MIT" in licence
    assert "pvt_engine" in licence
    assert "Apache" in licence
    lowered = readme.casefold()
    assert "local educational use" not in lowered
    assert "never released" not in lowered
    assert "installer never ships" not in lowered
    assert "available in local builds" in lowered or "local build" in lowered


def test_origin_phrases_are_gone_from_user_facing_text() -> None:
    pattern = re.compile(r"clean.?room|functional spec|built from public literature|the spec observed", re.I)
    roots = [ROOT / "README.md", ROOT / "docs", ROOT / "src"]
    hits: list[str] = []
    for base in roots:
        files = [base] if base.is_file() else base.rglob("*")
        for path in files:
            if not path.is_file() or path.suffix.lower() not in {".md", ".py", ""}:
                continue
            if path.suffix == "" and path.name != "README.md":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if pattern.search(text):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == []


def test_generated_header_keeps_the_disclaimer_and_drops_the_origin_clause(tmp_path: Path) -> None:
    target = tmp_path / "neutral.tab"
    generate_table(target, ["CO2"], [1.0], "PR", [1e5, 2e5], [10.0, 20.0], "SYN")
    text = target.read_text(encoding="utf-8")
    assert DISCLAIMER in text
    assert "clean-room" not in text.casefold()
    assert "functional spec" not in text.casefold()
    assert "Peng & Robinson, 1976" in text or "Peng-Robinson" in text
    assert "Lohrenz-Bray-Clark (1964)" in text


def test_pr78_maps_to_the_pra_template() -> None:
    from olga_companion.native_tab import MFL_MODEL

    assert MFL_MODEL == {"PR": "PR", "PR78": "PRA", "SRK": "SRK"}
    assert fluid_table.template_name("PRA") == "PRA.MFL"
    assert fluid_table.template_name("PR") == "PR.MFL"
    assert fluid_table.template_name("SRK") == "RKS.MFL"


def test_generate_tab_writes_the_table_and_a_companion_mfl(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    _stub_draft(monkeypatch, seen)
    result = tools.dispatch(TOOL, _approved(_gen()))

    table = root / "syn_co2.tab"
    draft = (root / "syn_co2.mfl").read_text(encoding="utf-8")
    assert table.is_file()
    assert result["mfl_rel"] == "syn_co2.mfl"
    assert seen == ["PR"]
    assert "1 CO2" in draft
    assert "CARBON DIOXIDE" not in draft
    assert re.search(r"(?m)^3 METHANE ;$", draft)
    assert "syn_co2_mf.tab" in draft
    assert "syn_co2.tab" not in draft.replace("syn_co2_mf.tab", "")


def test_formula_names_map_to_databank_spellings(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_draft(monkeypatch)
    components = [
        {"name": "CO2", "mole_fraction": 0.85},
        {"name": "C2H6", "mole_fraction": 0.05},
        {"name": "C3H8", "mole_fraction": 0.1},
    ]
    result = tools.dispatch(TOOL, _approved(_gen(tab_rel="co2c3.tab", components=components)))

    assert result["mfl_rel"] == "co2c3.mfl"
    draft = (root / "co2c3.mfl").read_text(encoding="utf-8")
    assert "C3H8" not in draft
    assert "C2H6" not in draft
    assert re.search(r"(?m)^3 (PROPANE|C3) ;$", draft)


def test_pr78_draft_uses_the_pra_template(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    _stub_draft(monkeypatch, seen)
    tools.dispatch(TOOL, _approved(_gen(model="PR78", tab_rel="pra.tab", components=[{"name": "CO2", "mole_fraction": 1.0}])))
    assert seen == ["PRA"]
    assert (root / "pra.tab").is_file()
    assert (root / "pra.mfl").is_file()


def test_an_existing_companion_mfl_is_refused_and_left_untouched(root: Path) -> None:
    kept = root / "syn_co2.mfl"
    kept.write_text("keep\n", encoding="utf-8")
    with pytest.raises(ToolError, match="syn_co2.mfl"):
        tools.approval_payload(TOOL, _gen())
    assert kept.read_text(encoding="utf-8") == "keep\n"
    assert not (root / "syn_co2.tab").exists()


def test_a_missing_databank_skips_the_mfl_and_keeps_the_table(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*_a: object, **_k: object) -> dict[str, str]:
        raise fluid_table.FluidTableError("The Multiflash component databank (infodata.db) is unavailable.")

    monkeypatch.setattr(fluid_table, "databank_names", missing)
    result = tools.dispatch(TOOL, _approved(_gen()))
    assert (root / "syn_co2.tab").is_file()
    assert not (root / "syn_co2.mfl").exists()
    assert result["ok"] is True
    note = str(result["mfl_note"]).casefold()
    assert "unavailable" in note or "skipped" in note


def test_a_missing_template_skips_the_mfl_and_keeps_the_table(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fluid_table, "databank_names", lambda *_a, **_k: dict(_NAMES))

    def missing(_model: str) -> str:
        raise fluid_table.FluidTableError("Multiflash sample templates are unavailable.")

    monkeypatch.setattr(fluid_table, "template_text", missing)
    result = tools.dispatch(TOOL, _approved(_gen()))
    assert (root / "syn_co2.tab").is_file()
    assert not (root / "syn_co2.mfl").exists()
    assert "unavailable" in str(result["mfl_note"]).casefold() or "skipped" in str(result["mfl_note"]).casefold()


def test_the_card_and_the_plan_row_name_the_companion_mfl_in_both_locales(root: Path) -> None:
    for locale in ("ko", "en"):
        shown = approval_display.build(TOOL, _gen(), locale=locale)
        match = [row for row in shown["fields"] if row["key"] == "mfl_file"]
        assert match and match[0]["value"] == "syn_co2.mfl"
    plan = approval_display.build("action_plan", {"steps": [{"kind": TOOL, "args": _gen()}]}, locale="en")
    keys = {field["key"] for field in plan["plan"]["steps"][0]["fields"]}
    assert "mfl_file" in keys


def test_capabilities_expose_native_tab_from_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from olga_companion.sidecar import _all_capabilities

    monkeypatch.delenv(FLAG, raising=False)
    assert config.native_tab_enabled() is False
    assert _all_capabilities()["native_tab"] is False
    monkeypatch.setenv(FLAG, "1")
    assert _all_capabilities()["native_tab"] is True


def test_release_collect_still_excludes_the_engine_modules() -> None:
    stray = sorted(
        path.name
        for path in (ROOT / "src" / "olga_companion" / "pvt_engine").rglob("*")
        if path.is_file() and path.suffix != ".py" and "__pycache__" not in path.parts
    )
    assert stray == ["LICENSE"]
    runbook = (ROOT / "docs" / "PACKAGING.md").read_text(encoding="utf-8")
    recipe = runbook[runbook.index("## Step 1"): runbook.index("Copy the result to the Tauri external-binary")]
    assert "--exclude-module olga_companion.pvt_engine" in recipe
    assert "--exclude-module olga_companion.native_tab" in recipe
