from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import genkey_static, genkey_tool_runner, sidecar
from olga_companion.flowpath_details import load_flowpath_details
from olga_companion.genkey_static import OlgaInputError


def test_missing_toolkit_script_error_is_path_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_root = tmp_path / "operator-private-toolkit"
    monkeypatch.setattr(genkey_static, "toolkit_dir", lambda: private_root)

    with pytest.raises(OlgaInputError) as captured:
        genkey_static._script_path("pipe_mapper", {"pipe_mapper": "missing.py"})

    assert str(private_root) not in str(captured.value)
    assert "missing.py" in str(captured.value)


def test_frozen_tool_command_reenters_the_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "genkey_parser.py"
    monkeypatch.setattr(genkey_tool_runner.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        genkey_tool_runner.sys,
        "executable",
        "olga-companion-sidecar.exe",
    )

    assert genkey_tool_runner.tool_command(script, ["case.genkey"]) == [
        "olga-companion-sidecar.exe",
        "--tool-script",
        str(script),
        "case.genkey",
    ]


def test_packaged_tool_reentry_is_bounded_to_the_toolkit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    toolkit = tmp_path / "toolkit"
    scripts = toolkit / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "fixture.py"
    script.write_text("print('packaged-tool-ok')\n", encoding="utf-8")
    monkeypatch.setattr(sidecar, "toolkit_dir", lambda: toolkit)

    assert sidecar._run_packaged_tool(str(script), []) == 0
    assert "packaged-tool-ok" in capsys.readouterr().out
    assert sidecar._run_packaged_tool(str(tmp_path / "outside.py"), []) == 2


def test_tool_output_is_bounded_before_json_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "pipe_mapper.py"
    script.write_text("import sys\nsys.stdout.write('x' * 129)\n", encoding="utf-8")

    monkeypatch.setattr(genkey_static, "_script_path", lambda *_args: script)
    monkeypatch.setattr(genkey_static, "toolkit_dir", lambda: tmp_path)

    result = genkey_static.run_tool(
        "pipe_mapper",
        ["case.genkey", "FLOWPATH_A", "--json"],
        names={"pipe_mapper": script.name},
        max_output_bytes=128,
    )

    assert result.exit_code == genkey_static.TOOL_OUTPUT_LIMIT_EXIT_CODE
    assert len(result.stdout.encode("utf-8")) <= 128
    assert "output limit" in result.stderr.lower()


def test_tool_is_stopped_while_it_is_still_emitting_oversized_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "pipe_mapper.py"
    script.write_text(
        "import sys\nwhile True:\n sys.stdout.write('x' * 65536)\n sys.stdout.flush()\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(genkey_static, "_script_path", lambda *_args: script)
    monkeypatch.setattr(genkey_static, "toolkit_dir", lambda: tmp_path)

    result = genkey_static.run_tool(
        "pipe_mapper",
        ["case.genkey", "FLOWPATH_A", "--json"],
        names={"pipe_mapper": script.name},
        timeout_s=5,
        max_output_bytes=128,
    )

    assert result.exit_code == genkey_static.TOOL_OUTPUT_LIMIT_EXIT_CODE
    assert result.elapsed_ms < 2_000


def test_oversized_genkey_is_rejected_before_any_parser_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = tmp_path / "oversized.genkey"
    case.write_bytes(b"x" * 129)
    calls: list[str] = []
    monkeypatch.setattr(genkey_static, "MAX_GENKEY_INPUT_BYTES", 128, raising=False)
    monkeypatch.setattr(
        genkey_static,
        "run_tool",
        lambda script_key, *_args, **_kwargs: calls.append(script_key),
    )

    with pytest.raises(OlgaInputError, match="input size limit"):
        load_flowpath_details(case, "FLOWPATH_A")

    assert calls == []
