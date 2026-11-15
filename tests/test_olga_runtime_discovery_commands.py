from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import runner
from olga_companion.olga_runtime import build_display_command


def test_install_globs_cover_opi_and_native_engine() -> None:
    engine_index = next(
        i
        for i, value in enumerate(runner.OLGA_EXE_GLOBS)
        if "OlgaExecutables/OLGA-" in value
    )
    opi_index = next(
        i for i, value in enumerate(runner.OLGA_EXE_GLOBS) if value.endswith("/opi.exe")
    )

    assert opi_index != engine_index


def test_detect_reports_direct_engine_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = tmp_path / "OLGA 2022.1.0" / "OlgaExecutables" / "OLGA-2022.1.0.exe"
    engine.parent.mkdir(parents=True)
    engine.write_text("stub")
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(
        runner,
        "OLGA_EXE_GLOBS",
        [str(tmp_path / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe")],
    )

    detection = runner.detect_olga()

    assert detection["exe"] == str(engine)
    assert detection["kind"] == "engine"


def test_direct_engine_command_is_gui_proven_case_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_path = tmp_path / "init"
    init_path.write_text("bridge")
    monkeypatch.setattr(runner, "WSL_INIT_PATH", init_path)
    monkeypatch.setattr(runner, "WSL_INTEROP_PATH", tmp_path / "missing-wslinterop")
    engine = "/mnt/c/Program Files/Schlumberger/OLGA 2022.1.0/OlgaExecutables/OLGA-2022.1.0.exe"

    assert runner._build_command(engine, "case.genkey") == [engine, "case.genkey"]


def test_opi_command_uses_batch_file_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "WSL_INIT_PATH", tmp_path / "missing-init")

    assert runner._build_command(
        "C:/Program Files/Schlumberger/OLGA 2022.1.0/opi.exe", "case.genkey"
    ) == [
        "C:/Program Files/Schlumberger/OLGA 2022.1.0/opi.exe",
        "-f",
        "case.genkey",
    ]


def test_display_command_strips_wsl_bridge_and_absolute_runtime_paths() -> None:
    opi = "/mnt/c/Program Files/Schlumberger/OLGA 2022.1.0/opi.exe"
    wsl_command = ["/init", opi, opi, "-f", "case.genkey"]
    engine = "/mnt/c/Program Files/Schlumberger/OLGA 2022.1.0/OlgaExecutables/OLGA-2022.1.0.exe"
    direct_command = [engine, "-nthreads", "12", "case.genkey"]

    assert build_display_command(wsl_command, opi) == ["opi.exe", "-f", "case.genkey"]
    assert build_display_command(direct_command, engine) == [
        "OLGA-2022.1.0.exe",
        "-nthreads",
        "12",
        "case.genkey",
    ]
    assert all(
        "/" not in part and "\\" not in part
        for part in build_display_command(wsl_command, opi)
    )
