"""Every place the product states its version must agree.

The version lives in five files. During the 0.1.1 bump four were updated and
`olga_companion.__version__` was missed, so the packaged app's Settings panel
reported 0.1.1 while its own `/health` endpoint reported 0.1.0 -- and the miss
only surfaced because a rebuilt sidecar was probed by hand.

That matters more than tidiness: the updater compares the running version
against the release feed, so a stale value here means the app misjudges whether
it is up to date.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import olga_companion

PROJECT = Path(__file__).parent.parent


def _json_version(relative: str) -> str:
    return json.loads((PROJECT / relative).read_text(encoding="utf-8"))["version"]


def _toml_version(relative: str, table: str) -> str:
    data = tomllib.loads((PROJECT / relative).read_text(encoding="utf-8"))
    return data[table]["version"]


def _cargo_lock_app_version() -> str:
    lock = tomllib.loads((PROJECT / "src-tauri/Cargo.lock").read_text(encoding="utf-8"))
    (entry,) = [item for item in lock["package"] if item["name"] == "olga-companion"]
    return entry["version"]


def _sources() -> dict[str, str]:
    npm_lock = json.loads((PROJECT / "package-lock.json").read_text(encoding="utf-8"))
    return {
        "package-lock.json": npm_lock["version"],
        "package-lock.json packages['']": npm_lock["packages"][""]["version"],
        "src-tauri/Cargo.lock": _cargo_lock_app_version(),
        "package.json": _json_version("package.json"),
        "src-tauri/tauri.conf.json": _json_version("src-tauri/tauri.conf.json"),
        "src-tauri/Cargo.toml": _toml_version("src-tauri/Cargo.toml", "package"),
        "pyproject.toml": _toml_version("pyproject.toml", "project"),
        "olga_companion.__version__": olga_companion.__version__,
    }


def test_all_version_declarations_agree() -> None:
    sources = _sources()
    distinct = set(sources.values())
    assert len(distinct) == 1, f"version drift: {sources}"


def test_node_floor_is_the_one_the_toolchain_actually_needs() -> None:
    # package.json said ">=22" while Vite 8 and rolldown need 22.12; a 22.0-22.11 user
    # got a cryptic build failure instead of an engines warning.
    manifest = json.loads((PROJECT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((PROJECT / "package-lock.json").read_text(encoding="utf-8"))
    vite = lock["packages"]["node_modules/vite"]["engines"]["node"]

    # Vite/rolldown need 22.12 on the 22 line; the repo's own gates also need native type
    # stripping (22.6+), which excludes the 20.x line Vite alone would allow.
    assert ">=22.12.0" in vite
    assert manifest["engines"]["node"] == ">=22.12.0"
    assert lock["packages"][""]["engines"]["node"] == ">=22.12.0"


def test_version_is_a_plain_semver_triple() -> None:
    # The updater compares these lexically against the release feed, so a stray
    # "v" prefix or build suffix would silently break the comparison.
    for name, value in _sources().items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", value), f"{name} is not semver: {value!r}"
