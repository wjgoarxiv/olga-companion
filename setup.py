"""Build hook: copy the shared resources into the wheel, so `uvx olga-companion-mcp` finds them.

The desktop app ships the same folders through src-tauri/tauri.conf.json; they stay in
resources/ so both builds read one copy.
"""

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

BUNDLED = ("olga-toolkit", "fluids", "examples")


class BuildWithResources(build_py):
    def run(self) -> None:
        super().run()
        source = Path(__file__).resolve().parent / "resources"
        target = Path(self.build_lib) / "olga_companion" / "resources" / "bundled"
        for name in BUNDLED:
            shutil.copytree(
                source / name,
                target / name,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )


setup(cmdclass={"build_py": BuildWithResources})
