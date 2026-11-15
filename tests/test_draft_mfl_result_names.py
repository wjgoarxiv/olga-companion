"""The .mfl draft write result names its files by workspace-relative path.

Hyper-real round 9 (2026-11-11): after the write approval the card showed only
"mfl_path path-sha256:08a3…" and "tab_abs path-sha256:4a7c…", because absolute paths
are redacted for the model and the result carried no relative name. The preview card
just before it showed hr09_air_water.mfl.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from olga_companion import fluid_table
from olga_companion.agent import tool_side_effects


def test_the_write_result_carries_the_relative_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target: dict[str, Any] = {
        "mfl_rel": "hr09_air_water.mfl",
        "tab_rel": "hr09_air_water.tab",
        "tab_abs": str(tmp_path / "hr09_air_water.tab"),
        "fluid_label": "AIR_WATER",
        "components": [{"name": "WATER", "mole_fraction": 1.0}],
        "model": "CPA",
        "temperatures": [0.0, 25.0],
        "temperature_unit": "degC",
        "pressures": [1.0, 30.0],
        "pressure_unit": "bar",
        "hawater": False,
    }
    monkeypatch.setattr(tool_side_effects, "_consume", lambda *_a: None)
    monkeypatch.setattr(tool_side_effects.workspace, "contained", lambda rel: tmp_path / rel)
    monkeypatch.setattr(fluid_table, "build_mfl_text", lambda **_k: "remove all;")
    monkeypatch.setattr(fluid_table, "write_draft_mfl", lambda path, _text: {"ok": True, "mfl_path": path})

    result = tool_side_effects.fluids_draft_mfl({}, lambda _name, _args: target)

    assert result["mfl_rel"] == "hr09_air_water.mfl"
    assert result["tab_rel"] == "hr09_air_water.tab"
