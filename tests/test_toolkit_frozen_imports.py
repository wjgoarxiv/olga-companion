"""Every third-party module a bundled toolkit script imports is reachable for PyInstaller.

The frozen sidecar runs toolkit scripts in its own interpreter (--tool-script), and
PyInstaller bundles only what it finds from olga_companion (--collect-submodules).
Hyper-real round 4 (2026-11-11): report_figure failed in the installed app only; the
frozen run of figure_generator.py stopped on
"ModuleNotFoundError: No module named 'matplotlib.animation'".
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "resources" / "olga-toolkit" / "scripts"
MANIFEST = ROOT / "src" / "olga_companion" / "toolkit_bundle_imports.py"
# Imported inside try/except ImportError by the scripts, and not project dependencies.
OPTIONAL = {"OpenOPC", "openpyxl", "style_presets"}


def _imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def _toolkit_third_party() -> dict[str, list[str]]:
    local = {path.stem for path in SCRIPTS.glob("*.py")}
    found: dict[str, list[str]] = {}
    for script in sorted(SCRIPTS.glob("*.py")):
        for name in _imports(ast.parse(script.read_text(encoding="utf-8"))):
            top = name.split(".")[0]
            if top in local or top in OPTIONAL or top in sys.stdlib_module_names or top == "__future__":
                continue
            found.setdefault(name, []).append(script.name)
    return found


def test_the_manifest_names_every_toolkit_import() -> None:
    manifest = _imports(ast.parse(MANIFEST.read_text(encoding="utf-8")))
    missing = {name: users for name, users in _toolkit_third_party().items() if name not in manifest}
    assert missing == {}


# matplotlib imports the writer for a file format only when savefig runs, so PyInstaller
# never sees it. Round 6 (build I): results_plot failed four times in the installed app with
# "No module named 'matplotlib.backends.backend_pdf'" (publication_plot writes a .pdf).
FORMAT_BACKENDS = {
    "pdf": "matplotlib.backends.backend_pdf",
    "png": "matplotlib.backends.backend_agg",
    "svg": "matplotlib.backends.backend_svg",
}


def test_every_figure_format_the_code_writes_has_its_backend_in_the_manifest() -> None:
    import re

    sources = [*SCRIPTS.glob("*.py"), *(ROOT / "src" / "olga_companion").rglob("*.py")]
    written = {
        match
        for path in sources
        if path.resolve() != MANIFEST.resolve()
        and "savefig" in (text := path.read_text(encoding="utf-8"))
        for match in re.findall(r"\.(pdf|png|svg)\b", text)
    }
    manifest = _imports(ast.parse(MANIFEST.read_text(encoding="utf-8")))
    assert "pdf" in written and "png" in written
    assert {fmt: FORMAT_BACKENDS[fmt] for fmt in written if FORMAT_BACKENDS[fmt] not in manifest} == {}


def test_the_manifest_is_never_imported_at_runtime() -> None:
    package = ROOT / "src" / "olga_companion"
    importers = [
        path.relative_to(ROOT).as_posix()
        for path in package.rglob("*.py")
        if path != MANIFEST and "toolkit_bundle_imports" in path.read_text(encoding="utf-8")
    ]
    assert importers == []
