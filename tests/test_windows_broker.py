from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TypeAlias
from unittest.mock import Mock

import pytest

from olga_companion import runner, windows_broker
from olga_companion.windows_broker import (
    BROKER_PROTOCOL,
    BrokerArtifact,
    prepare_broker_run,
)

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]


def _artifact(tmp_path: Path, payload: bytes = b"broker") -> BrokerArtifact:
    path = tmp_path / "cached" / "olga-explorer-broker.exe"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return BrokerArtifact(
        path=path,
        sha256=hashlib.sha256(payload).hexdigest(),
        source_sha256="1" * 64,
        build_id="broker-build",
        protocol=BROKER_PROTOCOL,
    )


def _native_detection(engine: Path) -> JsonObject:
    return {
        "detected": True,
        "source": "install-glob",
        "exe": str(engine),
        "kind": "engine",
        "version": "2022.1.0",
        "sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
        "candidate_id": "runtime_native",
        "runtime_id": "runtime_native",
        "evidence": [],
    }


def test_native_preview_uses_case_only_explorer_broker_and_binds_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "unsafe case name.genkey"
    case.write_text("CASE\n")
    engine = tmp_path / "OLGA-2022.1.0.exe"
    engine.write_bytes(b"engine")
    artifact = _artifact(tmp_path)
    monkeypatch.setattr(
        runner, "_require_detected", lambda _source: _native_detection(engine)
    )
    monkeypatch.setattr(
        runner,
        "_validate_case",
        lambda _source: {"valid": True, "command": {}},
    )
    monkeypatch.setattr(runner, "ensure_broker", lambda: artifact)

    preview = runner.preview_run(str(case), timeout_s=37)

    assert preview["launch_strategy"] == "explorer_one_shot_broker"
    assert preview["command"] == [str(engine), "case.genkey"]
    assert preview["display_command"] == [engine.name, "case.genkey"]
    assert preview["staged_case_name"] == "case.genkey"
    assert preview["broker"] == artifact.to_dict()
    assert "path" not in preview["broker"]
    assert str(artifact.path.parent) not in json.dumps(preview["broker"])

    # The approval binds what the broker is built from. A rebuild with new bytes
    # (csc.exe is not deterministic) keeps it; dispatch checks the exact binary.
    rebuilt = BrokerArtifact(
        path=artifact.path,
        sha256="2" * 64,
        source_sha256=artifact.source_sha256,
        build_id=artifact.build_id,
        protocol=artifact.protocol,
    )
    monkeypatch.setattr(runner, "ensure_broker", lambda: rebuilt)
    assert (
        runner.preview_run(str(case), timeout_s=37)["selection_id"]
        == preview["selection_id"]
    )

    for changed in (
        BrokerArtifact(
            path=artifact.path,
            sha256=artifact.sha256,
            source_sha256="3" * 64,
            build_id=artifact.build_id,
            protocol=artifact.protocol,
        ),
        BrokerArtifact(
            path=artifact.path,
            sha256=artifact.sha256,
            source_sha256=artifact.source_sha256,
            build_id="another-build",
            protocol=artifact.protocol,
        ),
    ):
        monkeypatch.setattr(runner, "ensure_broker", lambda changed=changed: changed)
        assert (
            runner.preview_run(str(case), timeout_s=37)["selection_id"]
            != preview["selection_id"]
        )


def test_script_preview_keeps_existing_direct_python_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case.genkey"
    case.write_text("CASE\n")
    script = tmp_path / "fake_olga.py"
    script.write_text("print('ok')\n")
    detection = {
        "detected": True,
        "exe": str(script),
        "kind": "script",
        "version": None,
        "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "candidate_id": "runtime_script",
        "runtime_id": "runtime_script",
        "evidence": [],
    }
    monkeypatch.setattr(runner, "_require_detected", lambda _source: detection)
    monkeypatch.setattr(
        runner,
        "_validate_case",
        lambda _source: {"valid": True, "command": {}},
    )
    broker = Mock(
        side_effect=AssertionError("script previews must not build the Windows broker")
    )
    monkeypatch.setattr(runner, "ensure_broker", broker)

    preview = runner.preview_run(str(case))

    assert preview["launch_strategy"] == "direct"
    assert preview["command"][-2:] == [str(script), case.name]
    assert preview["staged_case_name"] == case.name
    assert preview["broker"] is None
    broker.assert_not_called()


def test_prepare_broker_run_copies_exe_and_writes_fixed_immutable_request(
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path)
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    engine = tmp_path / "OLGA-2022.1.0.exe"
    engine.write_bytes(b"engine")
    case = run_dir / "case.genkey"
    case.write_bytes(b"CASE")

    prepared = prepare_broker_run(
        run_dir=run_dir,
        artifact=artifact,
        engine=engine,
        engine_sha256=hashlib.sha256(b"engine").hexdigest(),
        staged_case=case,
        staged_case_sha256=hashlib.sha256(b"CASE").hexdigest(),
        timeout_s=19,
    )

    assert prepared.broker_path == run_dir / "olga-explorer-broker.exe"
    assert prepared.request_path == run_dir / "broker-request.json"
    assert prepared.status_path == run_dir / "broker-status.json"
    request = json.loads(prepared.request_path.read_text(encoding="utf-8"))
    assert request["protocol"] == BROKER_PROTOCOL
    assert request["argv"] == ["case.genkey"]
    assert request["staged_case"] == "case.genkey"
    assert request["timeout_s"] == 19
    assert request["broker_sha256"] == artifact.sha256
    assert request["request_id"] == prepared.request_id
    assert not prepared.request_path.stat().st_mode & 0o200
    assert prepared.dispatch_command[-1].lower().endswith("olga-explorer-broker.exe")
    assert not any(
        part.lower().endswith((".cmd", ".bat", ".ps1"))
        for part in prepared.dispatch_command
    )


def test_wsl_dispatch_uses_absolute_explorer_path_for_init(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(windows_broker, "_native_windows", lambda: False)

    command = windows_broker._dispatch_command(tmp_path / "broker.exe")

    explorer = str(windows_broker.EXPLORER_PATH)
    assert command[:3] == [str(windows_broker.WSL_INIT_PATH), explorer, explorer]


def test_native_capability_fails_closed_when_explorer_broker_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = tmp_path / "OLGA-2022.1.0.exe"
    engine.write_bytes(b"engine")
    monkeypatch.setattr(
        runner, "detect_olga", lambda _source=None: _native_detection(engine)
    )
    monkeypatch.setattr(
        runner,
        "broker_capability",
        lambda: {"available": False, "reason": "interactive Explorer is unavailable"},
    )

    capability = runner.run_capabilities()["live_olga_run"]

    assert capability["enabled"] is False
    assert "Explorer" in capability["reason"]


def test_native_windows_host_commands_do_not_use_wsl_init(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    system_root = tmp_path / "Windows"
    csc = system_root / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    explorer = system_root / "explorer.exe"
    csc.parent.mkdir(parents=True)
    csc.write_bytes(b"compiler")
    explorer.write_bytes(b"explorer")
    monkeypatch.setattr(windows_broker.sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", str(system_root))

    paths = windows_broker._runtime_paths()
    compile_command = windows_broker._compiler_command(
        csc,
        tmp_path / "broker.exe",
        (Path("source.cs"), Path("source.Native.cs")),
    )
    dispatch_command = windows_broker._dispatch_command(tmp_path / "broker.exe")

    assert paths["csc"] == csc
    assert paths["explorer"] == explorer
    assert windows_broker.broker_capability()["available"] is True
    assert compile_command[0] == str(csc)
    assert "/init" not in compile_command
    assert dispatch_command[0].lower().endswith("explorer.exe")
    assert "/init" not in dispatch_command


def _windows_visible_directory(prefix: str) -> Path | None:
    """A fresh directory csc.exe can write to: the Windows %TEMP% seen from WSL."""
    if windows_broker._native_windows():
        return Path(tempfile.mkdtemp(prefix=prefix))
    try:
        raw = subprocess.run(
            ["cmd.exe", "/c", "echo %TEMP%"], cwd="/mnt/c", capture_output=True, timeout=30, check=False
        ).stdout.decode("utf-8", errors="replace").strip()
    except (OSError, subprocess.SubprocessError):
        return None
    drive, _, rest = raw.partition(":\\")
    if len(drive) != 1 or not rest:
        return None
    base = Path("/mnt") / drive.lower() / rest.replace("\\", "/")
    return Path(tempfile.mkdtemp(prefix=prefix, dir=base)) if base.is_dir() else None


@pytest.mark.skipif(
    not windows_broker.broker_capability()["available"],
    reason="Windows broker compiler unavailable",
)
def test_checked_in_broker_source_compiles_with_host_framework_csc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a cold cache on a Windows-visible drive (csc.exe cannot see a Linux /tmp).
    cache = _windows_visible_directory("olga-broker-test-")
    if cache is None:
        pytest.skip("no Windows-visible scratch directory is available for csc.exe")
    monkeypatch.setattr(windows_broker, "sandbox_root", lambda: cache)
    try:
        # When: the checked-in source is compiled from scratch.
        artifact = windows_broker.ensure_broker()

        # Then: the executable exists and its identity matches the sources.
        assert artifact.path.is_file()
        assert artifact.sha256 == windows_broker._sha256(artifact.path)
        assert artifact.source_sha256 == windows_broker._source_sha256(
            windows_broker._source_paths()
        )
    finally:
        shutil.rmtree(cache, ignore_errors=True)


@pytest.mark.skipif(
    windows_broker._native_windows() or not windows_broker.broker_capability()["available"],
    reason="needs a WSL host with the Windows compiler (Linux-only paths are valid natively)",
)
def test_a_linux_only_sandbox_is_refused_instead_of_misread_as_c_drive_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: a sandbox below a Linux-only directory (the cause of csc.exe's CS1567).
    monkeypatch.setattr(windows_broker, "sandbox_root", lambda: tmp_path)

    # When / Then: the build fails closed before csc.exe runs, with a recoverable explanation.
    with pytest.raises(windows_broker.BrokerUnavailable, match="Windows drive"):
        windows_broker.ensure_broker()
    assert not (tmp_path / "control").exists()


def test_compiler_diagnostics_in_the_oem_code_page_cannot_crash_the_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olga_companion import windows_broker_artifact

    # Given: csc.exe fails with a Korean OEM-encoded message (0xb8 is not valid UTF-8).
    def failing_run(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 1, stdout="리소스 오류 CS1567".encode("cp949"), stderr=b"")

    monkeypatch.setattr(windows_broker_artifact.subprocess, "run", failing_run)
    sources = windows_broker._source_paths()

    # When: the artifact build runs.
    with pytest.raises(windows_broker.BrokerUnavailable, match="CS1567"):
        windows_broker_artifact.ensure_broker_artifact(
            capability={"available": True},
            sources=sources,
            csc=Path(sys.executable),
            cache_root=tmp_path,
            sha256=windows_broker._sha256,
            source_sha256=windows_broker._source_sha256,
            compiler_command=lambda _csc, out, _sources: ["csc", str(out)],
            atomic_json=windows_broker._atomic_json,
        )


def test_preview_refuses_opi_instead_of_falling_back_to_direct_init(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case.genkey"
    case.write_text("CASE\n")
    opi = tmp_path / "opi.exe"
    opi.write_bytes(b"opi")
    detection = {
        **_native_detection(opi),
        "kind": "opi",
        "candidate_id": "runtime_opi",
        "runtime_id": "runtime_opi",
    }
    monkeypatch.setattr(runner, "_require_detected", lambda _source: detection)

    with pytest.raises(ValueError, match="broker|engine|OPI|unsupported"):
        runner.preview_run(str(case))
    monkeypatch.setattr(runner, "detect_olga", lambda _source=None: detection)
    assert runner.run_capabilities()["live_olga_run"]["enabled"] is False
