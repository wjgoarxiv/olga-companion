"""A rebuilt Explorer broker does not void an approved run preview.

Bug report 2026-11-13 (0.1.6, enterprise PC, OLGA 2025.1.0): approving a run gave
"OLGA runtime selection changed after preview". The broker exe is compiled by the
.NET Framework csc.exe, which cannot build deterministically, so every rebuild has a
new SHA-256. When the cached exe disappears between preview and approval (the same
PC earlier lost it outright), the rebuild changed the selection id. The approval now
binds the broker by what it is built from; the exact binary is still checked against
the fresh build before launch.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from olga_companion import config, runner
from olga_companion.genkey_static import OlgaInputError
from olga_companion.windows_broker import BROKER_PROTOCOL, BrokerArtifact


def _artifact(path: Path, payload: bytes, build_id: str = "broker-build") -> BrokerArtifact:
    path.write_bytes(payload)
    return BrokerArtifact(
        path=path,
        sha256=hashlib.sha256(payload).hexdigest(),
        source_sha256="1" * 64,
        build_id=build_id,
        protocol=BROKER_PROTOCOL,
    )


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setattr(runner, "_RUNS", {})
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setattr(config, "project_root", lambda: tmp_path / "appdata")
    case = tmp_path / "case.genkey"
    case.write_text("CASE\n", encoding="utf-8")
    engine = tmp_path / "OLGA-2025.1.0.exe"
    engine.write_bytes(b"engine")
    cache = tmp_path / "cached"
    cache.mkdir()
    detection = {
        "detected": True,
        "source": "install-glob",
        "exe": str(engine),
        "kind": "engine",
        "version": "2025.1.0",
        "sha256": hashlib.sha256(b"engine").hexdigest(),
        "candidate_id": "runtime_native",
        "runtime_id": "runtime_native",
        "evidence": [],
    }
    monkeypatch.setattr(runner, "_require_detected", lambda _source: detection)
    monkeypatch.setattr(runner, "_validate_case", lambda _source: {"valid": True, "command": {}})
    return case, cache / "olga-explorer-broker.exe"


def _no_launch(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    started: list[list[str]] = []

    class _Done:
        pid = 1

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(command, **_kwargs):
        started.append(list(command))
        return _Done()

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    return started


def test_rebuilt_broker_with_new_bytes_keeps_the_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case, exe = _setup(tmp_path, monkeypatch)
    first = _artifact(exe, b"broker build 1")
    monkeypatch.setattr(runner, "ensure_broker", lambda: first)
    preview = runner.preview_run(str(case), timeout_s=60)

    rebuilt = _artifact(exe, b"broker build 2 with a new timestamp")
    monkeypatch.setattr(runner, "ensure_broker", lambda: rebuilt)
    started = _no_launch(monkeypatch)

    result = runner.execute_run(
        str(case), approved=True, timeout_s=60, selection_id=preview["selection_id"]
    )

    assert result["state"] == "running"
    assert result["broker"]["broker_sha256"] == rebuilt.sha256
    assert started, "the run was dispatched"


def test_broker_built_from_other_sources_still_voids_the_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case, exe = _setup(tmp_path, monkeypatch)
    first = _artifact(exe, b"broker build 1")
    monkeypatch.setattr(runner, "ensure_broker", lambda: first)
    preview = runner.preview_run(str(case), timeout_s=60)

    other = _artifact(exe, b"broker from changed sources", build_id="another-build")
    monkeypatch.setattr(runner, "ensure_broker", lambda: other)

    with pytest.raises(OlgaInputError, match="selection changed after preview"):
        runner.execute_run(
            str(case), approved=True, timeout_s=60, selection_id=preview["selection_id"]
        )
