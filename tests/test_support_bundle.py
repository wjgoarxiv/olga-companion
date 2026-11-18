"""N7: the support information names versions and status codes only, never a folder,
a case or the user."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import run_queries, runner, support_bundle
from olga_companion.sidecar import app
from olga_runtime_test_support import _installed_release


@pytest.fixture
def installs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "secret-user" / "installs"
    _installed_release(root, "2022.1.0", opi=True)
    _installed_release(root, "2025.1.0", opi=False)
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(runner, "OLGA_EXE_GLOBS", [str(root / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe"), str(root / "OLGA*" / "opi.exe")])
    run_queries._capability_cache.clear()
    yield root
    run_queries._capability_cache.clear()


def test_the_version_matrix_lists_each_install_found(installs: Path) -> None:
    rows = support_bundle.version_matrix(runner.detect_olga())
    pairs = {(row["version"], row["kind"], row["file"]) for row in rows}
    assert ("2025.1.0", "engine", "OLGA-2025.1.0.exe") in pairs
    assert ("2022.1.0", "engine", "OLGA-2022.1.0.exe") in pairs
    assert ("2022.1.0", "opi", "opi.exe") in pairs
    by_kind = {row["kind"]: row["runnable"] for row in rows}
    assert by_kind == {"engine": True, "opi": False}
    assert sum(row["selected"] for row in rows) == 1


def test_the_bundle_route_has_no_folder_or_user_name(installs: Path) -> None:
    response = TestClient(app).get("/api/support-bundle")
    assert response.status_code == 200, response.text
    bundle = response.json()
    assert bundle["schema"] == 1 and bundle["app_version"]
    assert {"system", "release", "machine"} <= set(bundle["os"])
    assert bundle["olga"]
    text = json.dumps(bundle)
    assert "secret-user" not in text
    assert str(installs) not in text
    assert "\\\\" not in text and "/installs" not in text
    for cap in bundle["capabilities"].values():
        if isinstance(cap, dict):
            assert set(cap) == {"enabled", "reason_code", "reason_params"}


def test_no_install_gives_an_empty_matrix() -> None:
    assert support_bundle.version_matrix({"detected": False, "candidates": []}) == []
