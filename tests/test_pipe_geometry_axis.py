"""Y is the vertical axis in OLGA geometry: elevation lives on Y (ZEND stays 0).

The toolkit builder and the viewers must agree on that convention; plan position
lives on X/Z.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLKIT = REPO / "resources" / "olga-toolkit" / "scripts"
VIEWER = REPO / "frontend" / "src" / "flowpathGeometry.mjs"

_NODE_CHECK = """\
import { buildFlowpathProjection } from "%s";
const section = (y1, z1) => ({
  start: { x_m: 0, y_m: 0, z_m: 0 },
  center: { x_m: 5, y_m: y1 / 2, z_m: z1 / 2 },
  end: { x_m: 10, y_m: y1, z_m: z1 },
  chainage_start_m: 0, chainage_end_m: 10,
});
const opts = (view) => ({ view, width: 200, height: 100, padding: 10 });
const out = {};
for (const [name, y1, z1, view] of [
  ["rise", 20, 0, "elevation"], ["flat", 0, 0, "elevation"], ["side", 0, 20, "elevation"],
  ["risePlan", 20, 0, "plan"], ["flatPlan", 0, 0, "plan"], ["sidePlan", 0, 20, "plan"],
]) {
  out[name] = buildFlowpathProjection([section(y1, z1)], opts(view)).segments[0];
}
console.log(JSON.stringify(out));
"""


@pytest.fixture
def _no_toolkit_bytecode(monkeypatch: pytest.MonkeyPatch) -> None:
    # The toolkit ships verbatim: an in-process import must not leave .pyc behind.
    monkeypatch.setattr(sys, "dont_write_bytecode", True)


def _builder_text() -> str:
    sys.path.insert(0, str(TOOLKIT))
    try:
        from genkey_builder import GenkeyBuilder

        builder = GenkeyBuilder("simple_pipeline")
        builder.add_pipe("FP_1", "AXIS-PIPE", 0.1, [5.0, 5.0], [1.0, -0.5])
        return builder.build()
    finally:
        sys.path.remove(str(TOOLKIT))


def _ends(text: str, label: str) -> tuple[float, float, float]:
    line = next(
        line for line in text.splitlines()
        if line.startswith(" PIPE") and f"LABEL={label}" in line
    )
    values = {}
    for axis in ("XEND", "YEND", "ZEND"):
        matched = re.search(rf"{axis}=([0-9.eE+-]+) m", line)
        assert matched is not None, line
        values[axis] = float(matched.group(1))
    return values["XEND"], values["YEND"], values["ZEND"]


def test_builder_writes_the_rise_on_the_vertical_axis(_no_toolkit_bytecode: None) -> None:
    """A 10 m pipe rising 0.5 m ends at YEND=0.5 m with ZEND=0, and the plan
    distance is the horizontal projection so XEND/YEND agree with LENGTH."""

    x_end, y_end, z_end = _ends(_builder_text(), "AXIS-PIPE")

    assert (y_end, z_end) == (0.5, 0.0)
    assert math.isclose(x_end, 9.98747, rel_tol=1e-5)
    # %g formatting keeps 6 significant digits, so the agreement holds to that precision.
    assert math.isclose(x_end**2 + y_end**2, 10.0**2, rel_tol=1e-5)


def test_viewer_draws_elevation_from_y_and_plan_from_x_z(tmp_path: Path) -> None:
    """The elevation view answers to y and ignores z; the plan view is the reverse."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")

    script = tmp_path / "axis-check.mjs"
    script.write_text(_NODE_CHECK % VIEWER.as_uri(), encoding="utf-8")
    completed = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=120
    )
    assert completed.returncode == 0, completed.stderr
    out = json.loads(completed.stdout)

    assert out["rise"] != out["flat"], "elevation must show a rise on Y"
    assert out["side"] == out["flat"], "elevation must ignore Z"
    assert out["risePlan"] == out["flatPlan"], "plan must ignore Y"
    assert out["sidePlan"] != out["flatPlan"], "plan must show Z"
