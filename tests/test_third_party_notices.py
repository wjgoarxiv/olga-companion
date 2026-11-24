"""The installer bundles pyfas (GPL-3.0) and easydict (LGPL-3.0), and says so wherever people look."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYFAS_COMMIT = "d7432ec89cbeea1afc88dc7cf617c6df00b11b5e"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_licence_texts_ship_in_full():
    assert "GNU GENERAL PUBLIC LICENSE" in _read("licenses/GPL-3.0.txt")
    assert "END OF TERMS AND CONDITIONS" in _read("licenses/GPL-3.0.txt")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in _read("licenses/LGPL-3.0.txt")


def test_notice_names_the_copyleft_components_and_the_installer_terms():
    notice = _read("NOTICE")
    assert "pyfas" in notice and "GPL-3.0" in notice and PYFAS_COMMIT in notice
    assert "easydict" in notice and "LGPL-3.0" in notice
    assert "installer" in notice


def test_the_pyfas_commit_is_the_one_the_build_installs():
    assert f"pyfas.git@{PYFAS_COMMIT}" in _read("pyproject.toml")


def test_both_readmes_state_the_installer_licence():
    for rel in ("README.md", "README.ko.md"):
        text = _read(rel)
        assert "GPL-3.0" in text and "pyfas" in text and "THIRD-PARTY-LICENSES.txt" in text, rel


def test_the_installer_carries_the_notices():
    resources = json.loads(_read("src-tauri/tauri.conf.json"))["bundle"]["resources"]
    for source in ("../NOTICE", "../LICENSE", "../THIRD-PARTY-LICENSES.txt", "../licenses/"):
        assert source in resources, source


def test_the_bundle_lists_every_python_package_in_the_sidecar():
    text = _read("THIRD-PARTY-LICENSES.txt")
    for name in ("pyfas", "easydict", "numpy", "pandas", "matplotlib", "pydantic", "pywin32", "certifi", "fastapi", "aiohttp"):
        assert f"== {name} " in text, name
