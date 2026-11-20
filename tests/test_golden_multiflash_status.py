"""R14: the status drawer says Multiflash is ready only when Make table can run here."""

from __future__ import annotations

import pytest

from olga_companion import fluid_table, fluids
from olga_companion.multiflash_direct import WINDOWS_PYTHON_ENV


@pytest.fixture(autouse=True)
def _fresh_lookup() -> None:
    fluids._multiflash_lookup.clear()


def _found(monkeypatch: pytest.MonkeyPatch, found: bool) -> list[int]:
    calls: list[int] = []

    def finder() -> dict[str, object]:
        calls.append(1)
        return {"found": found, "exe": "MFBJ01.exe" if found else None}

    monkeypatch.setattr(fluid_table, "find_multiflash", finder)
    return calls


def test_found_and_launchable_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _found(monkeypatch, True)
    monkeypatch.setenv(WINDOWS_PYTHON_ENV, "py.exe")
    caps = fluids.fluid_capabilities()["multiflash"]
    assert caps["enabled"] is True
    assert "Make table" in caps["reason"]


def test_found_but_not_launchable_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _found(monkeypatch, True)
    monkeypatch.setattr(fluids, "_can_launch_multiflash", lambda: False)
    caps = fluids.fluid_capabilities()["multiflash"]
    assert caps["enabled"] is False
    assert "Windows app" in caps["reason"]


def test_missing_multiflash_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _found(monkeypatch, False)
    caps = fluids.fluid_capabilities()["multiflash"]
    assert caps["enabled"] is False
    assert "not found" in caps["reason"]


def test_the_lookup_is_reused_between_health_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _found(monkeypatch, True)
    fluids.fluid_capabilities()
    fluids.fluid_capabilities()
    assert len(calls) == 1


def test_status_does_not_start_a_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    _found(monkeypatch, False)
    monkeypatch.setattr(fluids, "run_tool", lambda *a, **k: pytest.fail("health must not spawn a probe"))
    fluids.fluid_capabilities()


def test_a_not_found_lookup_is_not_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _found(monkeypatch, False)
    fluids.fluid_capabilities()
    fluids.fluid_capabilities()
    assert len(calls) == 2
