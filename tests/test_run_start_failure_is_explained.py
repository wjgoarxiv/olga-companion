"""A run whose OLGA launch cannot start is refused with the reason, not a bare 500.

Bug report 2026-11-13 (0.1.5, another PC, OLGA 2025.1.0 engine): pressing Run gave
POST /api/run/execute 500 kind=FileNotFoundError and nothing else. The broker path
copies a locally compiled helper exe into the run folder and starts it through
Explorer; when a file in that chain is missing (for example removed by security
software) the OSError escaped as a 500 and the log never said which file.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest

from olga_companion import config, runner
from olga_companion.genkey_static import OlgaInputError
from olga_companion.runtime_logging import LOGGER_NAME
from olga_companion.windows_broker import BROKER_PROTOCOL, BrokerArtifact


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, BrokerArtifact, dict]:
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setattr(config, "project_root", lambda: tmp_path / "appdata")
    case = tmp_path / "case.genkey"
    case.write_text("CASE\n", encoding="utf-8")
    engine = tmp_path / "OLGA-2025.1.0.exe"
    engine.write_bytes(b"engine")
    broker = tmp_path / "cached" / "olga-explorer-broker.exe"
    broker.parent.mkdir(parents=True)
    broker.write_bytes(b"broker")
    artifact = BrokerArtifact(
        path=broker,
        sha256=hashlib.sha256(b"broker").hexdigest(),
        source_sha256="1" * 64,
        build_id="broker-build",
        protocol=BROKER_PROTOCOL,
    )
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
    monkeypatch.setattr(runner, "ensure_broker", lambda: artifact)
    return case, artifact, detection


def test_missing_broker_file_is_refused_with_its_name_and_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    case, artifact, _detection = _setup(tmp_path, monkeypatch)
    preview = runner.preview_run(str(case), timeout_s=60)
    artifact.path.unlink()
    monkeypatch.setattr(logging.getLogger(LOGGER_NAME), "propagate", True)
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)

    with pytest.raises(OlgaInputError) as refused:
        runner.execute_run(
            str(case), approved=True, timeout_s=60, selection_id=preview["selection_id"]
        )

    message = str(refused.value)
    assert "olga-explorer-broker.exe" in message
    assert "OLGA" in message
    lines = [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]
    started = [line for line in lines if line.startswith("run_start_failed")]
    assert len(started) == 1, lines
    assert "strategy=explorer_one_shot_broker" in started[0]
    assert "kind=FileNotFoundError" in started[0]
    assert "file=olga-explorer-broker.exe" in started[0]
    assert str(tmp_path) not in started[0]


def test_explorer_that_cannot_start_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case, _artifact, _detection = _setup(tmp_path, monkeypatch)
    preview = runner.preview_run(str(case), timeout_s=60)

    def no_explorer(*_args, **_kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified", r"C:\Windows\explorer.exe")

    monkeypatch.setattr(runner.subprocess, "Popen", no_explorer)

    with pytest.raises(OlgaInputError, match="explorer.exe"):
        runner.execute_run(
            str(case), approved=True, timeout_s=60, selection_id=preview["selection_id"]
        )


def test_run_refusal_reason_is_logged_without_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from fastapi.testclient import TestClient

    import olga_companion.sidecar as sidecar

    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE\n", encoding="utf-8")

    def refuse(*_args, **_kwargs):
        raise OlgaInputError(r"No suitable OLGA executable detected. C:\Program Files\SLB\OLGA 2025.1.0\bin\olga.exe is not supported.")

    monkeypatch.setattr(sidecar, "preview_run", refuse)
    monkeypatch.setattr(logging.getLogger(LOGGER_NAME), "propagate", True)
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)

    response = TestClient(sidecar.app).post("/api/run/preview", json={"source": "case.genkey"})

    assert response.status_code == 400
    lines = [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME and r.getMessage().startswith("run_refused")]
    assert len(lines) == 1
    assert "route=preview" in lines[0]
    assert "No suitable OLGA executable detected" in lines[0]
    assert "olga.exe" in lines[0]
    assert "Program Files" not in lines[0]


def test_refusal_detail_cuts_folders_that_contain_quotes() -> None:
    from olga_companion.sidecar_run_results_routes import _refusal_detail

    detail = _refusal_detail(r"Cannot open C:\Users\O'Brien\Jo's \"cases\"\case.genkey now")

    assert "case.genkey" in detail
    assert "O'Brien" not in detail
    assert "Users" not in detail


def test_permission_denied_is_not_called_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case, _artifact, _detection = _setup(tmp_path, monkeypatch)
    preview = runner.preview_run(str(case), timeout_s=60)

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "Access is denied", r"C:\Windows\explorer.exe")

    monkeypatch.setattr(runner.subprocess, "Popen", denied)

    with pytest.raises(OlgaInputError) as refused:
        runner.execute_run(
            str(case), approved=True, timeout_s=60, selection_id=preview["selection_id"]
        )

    message = str(refused.value)
    assert "explorer.exe" in message
    assert "not found" not in message
