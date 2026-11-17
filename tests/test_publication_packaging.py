from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from olga_companion import sidecar as sidecar_module
from olga_companion.publication_plot import PublicationRendererUnavailableError


PROJECT = Path(__file__).parent.parent
SOURCE = PROJECT / "src"


def _isolated_python(script: str, **environment: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(environment)
    env["PYTHONPATH"] = os.pathsep.join(
        path for path in (str(SOURCE), env.get("PYTHONPATH", "")) if path
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_core_sidecar_imports_when_optional_result_extras_are_absent() -> None:
    # Given: a core installation where every optional result dependency is unavailable.
    script = """
import importlib.abc
import sys

blocked = {"easydict", "matplotlib", "numpy", "pandas", "pyfas"}

class OptionalResultBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in blocked:
            raise ModuleNotFoundError(f"blocked optional dependency: {fullname}")
        return None

sys.meta_path.insert(0, OptionalResultBlocker())

# When: the real sidecar module is imported.
from olga_companion.sidecar import app

# Then: application construction completes without loading result extras.
print(app.title)
"""

    completed = _isolated_python(script)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "OLGA Companion"


def test_publication_capability_fails_closed_without_renderer_extras() -> None:
    # Given: parser availability but no matplotlib/numpy renderer.
    script = """
import importlib.abc
import json
import sys

blocked = {"matplotlib", "numpy"}

class RendererBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in blocked:
            raise ModuleNotFoundError(f"blocked renderer dependency: {fullname}")
        return None

sys.meta_path.insert(0, RendererBlocker())
from olga_companion import results
results._fixture_smoke = lambda: (True, "parser available")

# When: callers inspect the public result capability map.
capability = results.result_capabilities()["publication_export"]

# Then: publication is explicitly disabled with an actionable reason.
print(json.dumps(capability))
"""

    completed = _isolated_python(script)

    assert completed.returncode == 0, completed.stderr
    capability = json.loads(completed.stdout)
    assert capability["enabled"] is False
    assert "matplotlib" in capability["reason"].lower()


def test_publication_render_succeeds_with_a_clean_home(tmp_path: Path) -> None:
    # Given: an empty user home with no developer style scripts or user-installed fonts.
    home = tmp_path / "clean-home"
    mpl_config = tmp_path / "matplotlib-config"
    output = tmp_path / "publication"
    home.mkdir()
    script = f"""
import json
from pathlib import Path
from olga_companion.publication_plot import render_publication_series

series = {{
    "time": [0.0, 5.0, 10.0],
    "values": [10.0, 12.0, 15.0],
    "variable": "PT",
    "position": "POSITION-B",
    "unit": "Pa",
    "time_unit": "s",
}}

# When: the real renderer writes both publication formats.
publication = render_publication_series(series, Path({str(output)!r}))

# Then: its portable style/font metadata describes the generated files.
print(json.dumps(publication))
"""

    completed = _isolated_python(
        script,
        HOME=str(home),
        MPLCONFIGDIR=str(mpl_config),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
    )

    assert completed.returncode == 0, completed.stderr
    publication = json.loads(completed.stdout)
    assert Path(publication["png"]).is_file()
    assert Path(publication["pdf"]).is_file()
    assert publication["font_family"]
    assert Path(publication["font_path"]).is_file()
    assert not Path(publication["font_path"]).is_relative_to(home)
    assert publication["style_source"] == "olga_companion.publication_plot"


def test_publication_route_returns_400_when_renderer_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the optional renderer fails after a valid publication request reaches it.
    def unavailable(*_args: str, **_kwargs: str) -> dict[str, str]:
        raise PublicationRendererUnavailableError("matplotlib")

    monkeypatch.setattr(sidecar_module, "plot_result", unavailable)

    # When: the real HTTP route handles the request.
    response = TestClient(sidecar_module.app).post(
        "/api/results/plot",
        json={"path": "workspace:case.tpl", "variables": ["PT"], "position": "B"},
    )

    # Then: renderer absence is a typed user-facing gate, never a server failure.
    assert response.status_code == 400
    assert "optional matplotlib dependency" in response.json()["detail"]
