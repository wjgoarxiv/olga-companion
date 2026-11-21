from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO

import pytest
from fastapi.testclient import TestClient

from olga_companion import config, native_dialogs, runner, sidecar, workspace
from olga_companion.agent import session_token


def test_superseded_context_request_does_not_launch_before_registry_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an older request paused before show_dialog publishes its registry entry.
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(root))
    generation = workspace.context_generation()
    conversion_entered = threading.Event()
    release_conversion = threading.Event()
    launches: list[list[str]] = []

    def blocked_conversion(_value: Path | str, *, native_windows: bool | None = None) -> str:
        del native_windows
        conversion_entered.set()
        assert release_conversion.wait(2)
        return r"C:\QA"

    class ExitedProcess:
        returncode = 1

        def communicate(self, timeout: float | None = None) -> tuple[None, None]:
            del timeout
            return None, None

    def launch(
        argv: list[str],
        *,
        stdin: int,
        stdout: BinaryIO,
        stderr: BinaryIO,
        env: dict[str, str],
        close_fds: bool,
    ) -> ExitedProcess:
        del stdin, stdout, stderr, env, close_fds
        launches.append(argv)
        return ExitedProcess()

    monkeypatch.setattr(native_dialogs, "local_to_windows", blocked_conversion)
    monkeypatch.setattr(native_dialogs, "_resolve_powershell", lambda: (Path("/bin/true"), ""))
    monkeypatch.setattr(native_dialogs.subprocess, "Popen", launch)
    token = session_token.boot_token()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            sidecar.api_native_workspace,
            sidecar.NativeWorkspaceDialogRequest(
                request_id="prebind-older",
                context_generation=generation,
            ),
            token,
        )
        assert conversion_entered.wait(2)

        # When: a newer exact lease supersedes it before the older registry insertion.
        newer = native_dialogs.begin_context_dialog("prebind-newer", generation)
        try:
            release_conversion.set()
            result = future.result(timeout=2)
        finally:
            native_dialogs.finish_context_dialog(newer)

    # Then: the stale request is rejected without launching a native process.
    assert result == {"status": "superseded", "request_id": "prebind-older"}
    assert launches == []


def test_fastapi_shutdown_terminates_and_unregisters_owned_direct_run(tmp_path: Path) -> None:
    # Given: a direct runner-owned process is live and registered when the app starts shutdown.
    command = [sys.executable, "-c", "import time; time.sleep(300)"]
    process = subprocess.Popen(command, start_new_session=os.name == "posix")
    timer = threading.Timer(300, lambda: None)
    state = runner._RunState(
        popen=process,
        run_dir=tmp_path,
        log_path=tmp_path / "run.log",
        command=command,
        detection={},
        selection_id="shutdown-direct-selection",
        validation_valid=True,
        timeout_s=300,
        started_monotonic=time.monotonic(),
        timer=timer,
        receipt={},
    )
    with runner._REGISTRY_LOCK:
        runner._RUNS["shutdown-direct-run"] = state

    try:
        # When: FastAPI completes its lifespan shutdown.
        with TestClient(sidecar.app):
            assert process.poll() is None

        # Then: the owned process is reaped and its live registry entry is gone.
        assert process.wait(timeout=5) is not None
        with runner._REGISTRY_LOCK:
            assert "shutdown-direct-run" not in runner._RUNS
    finally:
        with runner._REGISTRY_LOCK:
            runner._RUNS.pop("shutdown-direct-run", None)
        if process.poll() is None:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        process.wait(timeout=5)
