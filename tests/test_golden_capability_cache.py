"""R6: the 20 s health probe reuses detection while the OLGA exes are unchanged."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from olga_companion import run_queries


def _ctx(exe: Path, calls: list[int]) -> SimpleNamespace:
    def detect_olga(_source=None):
        calls.append(1)
        return {"detected": True, "candidates": [{"exe": str(exe)}]}

    return SimpleNamespace(detect_olga=detect_olga)


def test_unchanged_exe_is_not_detected_again(tmp_path: Path) -> None:
    run_queries._capability_cache.clear()
    exe = tmp_path / "OLGA-2022.1.0.exe"
    exe.write_bytes(b"engine")
    calls: list[int] = []
    ctx = _ctx(exe, calls)
    run_queries.cached_capability_detection(ctx, now=0.0)
    run_queries.cached_capability_detection(ctx, now=20.0)
    assert len(calls) == 1


def test_a_replaced_exe_is_detected_again(tmp_path: Path) -> None:
    run_queries._capability_cache.clear()
    exe = tmp_path / "OLGA-2022.1.0.exe"
    exe.write_bytes(b"engine")
    calls: list[int] = []
    ctx = _ctx(exe, calls)
    run_queries.cached_capability_detection(ctx, now=0.0)
    exe.write_bytes(b"another engine")
    os.utime(exe, ns=(1, 1))
    run_queries.cached_capability_detection(ctx, now=20.0)
    assert len(calls) == 2


def test_the_cache_expires(tmp_path: Path) -> None:
    run_queries._capability_cache.clear()
    exe = tmp_path / "OLGA-2022.1.0.exe"
    exe.write_bytes(b"engine")
    calls: list[int] = []
    ctx = _ctx(exe, calls)
    run_queries.cached_capability_detection(ctx, now=0.0)
    run_queries.cached_capability_detection(ctx, now=run_queries._CAPABILITY_TTL_S + 1)
    assert len(calls) == 2


def test_not_found_is_never_reused(tmp_path: Path) -> None:
    calls: list[int] = []

    def detect_olga(_source=None):
        calls.append(1)
        return {"detected": False, "candidates": []}

    ctx = SimpleNamespace(detect_olga=detect_olga)
    run_queries.cached_capability_detection(ctx, now=0.0)
    run_queries.cached_capability_detection(ctx, now=20.0)
    assert len(calls) == 2


def test_changed_install_globs_detect_again(tmp_path: Path, monkeypatch) -> None:
    from olga_companion import runner

    exe = tmp_path / "OLGA-2022.1.0.exe"
    exe.write_bytes(b"engine")
    calls: list[int] = []
    ctx = _ctx(exe, calls)
    run_queries.cached_capability_detection(ctx, now=0.0)
    monkeypatch.setattr(runner, "OLGA_EXE_GLOBS", [str(tmp_path / "nowhere" / "opi.exe")])
    run_queries.cached_capability_detection(ctx, now=20.0)
    assert len(calls) == 2
