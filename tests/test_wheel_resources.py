"""An installed wheel (what the plugin's uvx runs) carries the toolkit, the starter table and the examples."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ("olga-toolkit", "fluids", "examples")

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is needed to build the wheel")

PROBE = """
import json, sys
from olga_companion import config, examples, fluid_table, starter_fluids
table = starter_fluids.bundled_table()
print(json.dumps({
    "module": config.__file__,
    "toolkit": str(config.toolkit_dir()),
    "builder": (config.toolkit_dir() / "scripts" / "genkey_builder.py").is_file(),
    "table": str(table),
    "pickup": fluid_table.pickup_tab(str(table)),
    "catalog": examples._catalog_path().is_file(),
}))
"""


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("wheel")
    source = tmp / "source"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info")
    shutil.copytree(ROOT / "src", source / "src", ignore=ignore)
    for name in BUNDLED:
        shutil.copytree(ROOT / "resources" / name, source / "resources" / name, ignore=ignore)
    for name in ("pyproject.toml", "setup.py", "MANIFEST.in"):
        shutil.copy2(ROOT / name, source / name)
    run = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp / "dist"), str(source)],
        capture_output=True, text=True, timeout=600,
    )
    assert run.returncode == 0, run.stderr[-3000:]
    (built,) = (tmp / "dist").glob("olga_companion-*.whl")
    return built


def test_the_wheel_ships_the_bundled_folders_and_the_console_script(wheel: Path):
    names = set(zipfile.ZipFile(wheel).namelist())
    assert "olga_companion/resources/bundled/fluids/air_water_cpa.tab" in names
    assert "olga_companion/resources/bundled/olga-toolkit/scripts/genkey_builder.py" in names
    assert "olga_companion/resources/bundled/examples/catalog.json" in names
    entry = next(n for n in names if n.endswith(".dist-info/entry_points.txt"))
    assert "olga-companion-mcp = olga_companion.headless_mcp:main" in zipfile.ZipFile(wheel).read(entry).decode()


def test_an_installed_wheel_finds_its_own_resources(wheel: Path, tmp_path: Path):
    site = tmp_path / "site"
    zipfile.ZipFile(wheel).extractall(site)
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "OLGA_TOOLKIT_DIR", "OLGA_WORKSPACE_DIR"}}
    env.update({"PYTHONPATH": str(site), "OLGA_APP_DATA_DIR": str(tmp_path / "data")})
    run = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, cwd=tmp_path, env=env, timeout=120)
    assert run.returncode == 0, run.stderr[-3000:]
    found = json.loads(run.stdout.strip().splitlines()[-1])
    assert Path(found["module"]).is_relative_to(site)
    assert Path(found["toolkit"]).is_relative_to(site)
    assert found["builder"] is True
    assert Path(found["table"]).is_relative_to(site)
    assert found["pickup"]["valid"] is True, found["pickup"]
    assert found["catalog"] is True


def test_the_repo_checkout_still_uses_its_own_resources():
    from olga_companion import config

    if "OLGA_TOOLKIT_DIR" not in os.environ:
        assert config.toolkit_dir() == ROOT / "resources" / "olga-toolkit"
