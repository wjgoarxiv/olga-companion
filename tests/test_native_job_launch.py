"""The installed Windows app starts OLGA itself, with no compiled helper exe.

Bug report 2026-11-13 (0.1.7, enterprise PC): company security software blocked the
helper exe the app compiles into AppData (a permission popup named its folder, only
identity.json was left there) and the run failed with exit 125. On native Windows the
sidecar now launches the engine directly inside a kill-on-close Job Object.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from olga_companion import config, runner
from olga_companion.genkey_static import OlgaInputError


class _Finished:
    pid = 4242
    returncode = 0

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        return None

    def kill(self):
        return None


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, list[dict]]:
    monkeypatch.setattr(runner, "_RUNS", {})
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setattr(config, "project_root", lambda: tmp_path / "appdata")
    case = tmp_path / "case.genkey"
    case.write_text("CASE\n", encoding="utf-8")
    engine = tmp_path / "OLGA-2025.1.0.exe"
    engine.write_bytes(b"engine")
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
    monkeypatch.setattr(runner, "_native_windows", lambda: True)

    def no_helper():
        raise AssertionError("the installed app must not build the Explorer helper")

    monkeypatch.setattr(runner, "ensure_broker", no_helper)
    launches: list[dict] = []

    def fake_launch(command, *, cwd, stdout):
        launches.append({"command": list(command), "cwd": Path(cwd)})
        return _Finished()

    monkeypatch.setattr(runner, "launch_in_job", fake_launch)
    return case, engine, launches


def test_the_installed_app_starts_olga_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case, engine, launches = _setup(tmp_path, monkeypatch)
    preview = runner.preview_run(str(case), timeout_s=60)
    assert preview["launch_strategy"] == "native_job"
    assert preview["broker"] is None

    result = runner.execute_run(
        str(case), approved=True, timeout_s=60, selection_id=preview["selection_id"]
    )

    assert result["state"] == "running"
    assert result["launch_strategy"] == "native_job"
    assert len(launches) == 1
    launch = launches[0]
    assert launch["command"] == [str(engine), "case.genkey"]
    assert launch["cwd"] == Path(result["run_dir"])
    assert (launch["cwd"] / "case.genkey").is_file()
    assert not list((tmp_path / "appdata").rglob("*.exe")), "no exe is written into AppData"


def test_an_engine_changed_after_approval_does_not_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case, engine, launches = _setup(tmp_path, monkeypatch)
    preview = runner.preview_run(str(case), timeout_s=60)
    engine.write_bytes(b"swapped engine")

    with pytest.raises(OlgaInputError, match="OLGA did not start"):
        runner.execute_run(
            str(case), approved=True, timeout_s=60, selection_id=preview["selection_id"]
        )
    assert launches == []


def test_run_capability_does_not_need_the_compiler_on_native_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _case, engine, _launches = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner,
        "detect_olga",
        lambda source_value=None: {
            "detected": True,
            "source": "install-glob",
            "exe": str(engine),
            "kind": "engine",
        },
    )
    monkeypatch.setattr(
        runner,
        "broker_capability",
        lambda: {"available": False, "reason": "Explorer one-shot broker is unavailable: Framework64 csc.exe."},
    )

    capabilities = runner.run_capabilities()

    assert capabilities["live_olga_run"]["enabled"] is True


def _orphan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, out_text: str | None) -> Path:
    """A run started by an earlier sidecar process that ended before writing its end."""
    case, _engine, _launches = _setup(tmp_path, monkeypatch)

    class _Running(_Finished):
        returncode = None

        def poll(self):
            return None

    monkeypatch.setattr(runner, "launch_in_job", lambda command, *, cwd, stdout: _Running())
    monkeypatch.setattr(runner, "_reap", lambda _run_id, _state: None)
    preview = runner.preview_run(str(case), timeout_s=60)
    result = runner.execute_run(
        str(case), approved=True, timeout_s=60, selection_id=preview["selection_id"]
    )
    run_dir = Path(result["run_dir"])
    if out_text is not None:
        out = run_dir / "case.out"
        out.write_text(out_text, encoding="utf-8")
        # A real solver writes seconds after launch; coarse file clocks can trail time_ns().
        later = runner.load_run_record(run_dir)["native_run"]["started_wall_ns"] + 10**9
        os.utime(out, ns=(later, later))
    for state in runner._RUNS.values():
        state.timer.cancel()
    monkeypatch.setattr(runner, "_RUNS", {})
    monkeypatch.setattr(runner, "_SELECTION_BOOT_NONCE", "a-later-sidecar")
    return run_dir


def test_a_run_left_by_a_closed_app_is_closed_and_does_not_block_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _orphan(tmp_path, monkeypatch, None)

    status = runner._status_from_receipt(runner.load_run_record(run_dir), run_dir)

    assert status["state"] == "failed"
    assert status["failure"]["code"] == "run_interrupted"
    assert runner.load_run_record(run_dir)["phase"] == "terminal"
    assert runner.run_update_gate.scan_open_receipts(runner) == []


def test_a_run_that_finished_before_the_app_closed_counts_as_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _orphan(
        tmp_path,
        monkeypatch,
        "INPUT FILE: case.genkey\n...\nNORMAL STOP IN EXECUTION\n",
    )

    status = runner._status_from_receipt(runner.load_run_record(run_dir), run_dir)

    assert status["state"] == "completed"
    assert runner.load_run_record(run_dir)["phase"] == "terminal"


def test_a_run_of_this_sidecar_is_not_closed_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _orphan(tmp_path, monkeypatch, None)
    record = runner.load_run_record(run_dir)
    monkeypatch.setattr(runner, "_SELECTION_BOOT_NONCE", record["native_run"]["supervisor_boot"])

    status = runner._status_from_receipt(record, run_dir)

    assert status["state"] != "failed"
    assert runner.load_run_record(run_dir)["phase"] != "terminal"


def test_olga_gets_an_environment_without_the_packaged_sidecar_folders() -> None:
    from olga_companion.windows_native_launch import child_environment

    bundle = r"C:\Users\me\AppData\Local\Temp\_MEI12345"
    env = child_environment(
        {
            "PATH": bundle + r";C:\Windows\system32;" + bundle + r"\pywin32_system32;C:\OLGA\bin",
            "SSL_CERT_FILE": bundle + r"\certifi\cacert.pem",
            "_MEIPASS2": bundle,
            "_PYI_APPLICATION_HOME_DIR": bundle,
            "PYTHONPATH": r"C:\somewhere",
            "LM_LICENSE_FILE": "27000@licenses",
            "OLGA_APP_DATA_DIR": r"C:\Users\me\AppData\Local\app",
        },
        bundle,
    )

    assert env["PATH"] == r"C:\Windows\system32;C:\OLGA\bin"
    assert env["LM_LICENSE_FILE"] == "27000@licenses"
    for name in ("SSL_CERT_FILE", "_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "PYTHONPATH"):
        assert name not in env


def test_without_a_packaged_sidecar_the_environment_is_kept() -> None:
    from olga_companion.windows_native_launch import child_environment

    env = child_environment({"PATH": r"C:\Windows", "PYTHONPATH": "x"}, None)
    assert env == {"PATH": r"C:\Windows"}
