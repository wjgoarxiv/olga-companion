from pathlib import Path

import pytest

from olga_companion.agent import approval_display
from olga_companion.agent.tool_validation import ToolError


class Paths:
    def input_file(self, value, suffixes):
        assert suffixes == {".genkey"}
        return Path(value)


class StringPaths:
    def input_file(self, value, suffixes):
        assert suffixes == {".genkey"}
        return str(Path(value))


def test_run_display_is_derived_from_matching_server_preview(tmp_path):
    source = tmp_path / "case.genkey"
    source.write_text("CASE\n", encoding="utf-8")

    def preview(value, timeout):
        assert value == str(source)
        assert timeout == 45
        return {
            "source": str(source),
            "selection_id": "selection_exact",
            "runtime_id": "olga-2022.1",
            "detection": {"exe": r"C:\\OLGA\\OLGA-2022.1.0.exe"},
            "cwd_template": "/managed/runs/<run_id>",
            "timeout_s": 45,
            "context_generation": 7,
        }

    display = approval_display.build(
        "run_execute",
        {
            "source": str(source),
            "selection_id": "selection_exact",
            "timeout_s": 45,
            "runtime_id": "model-spoof",
            "source_sha256": "0" * 64,
        },
        Paths(),
        preview,
    )

    assert display == {
        "case": "case.genkey",
        "selection_id": "selection_exact",
        "runtime_id": "olga-2022.1",
        "executable": "OLGA-2022.1.0.exe",
        "output_target": "managed-run-sandbox",
        "source_sha256": approval_display.file_sha256(source),
        "timeout_s": 45,
        "context_generation": 7,
    }


def test_run_display_accepts_the_production_string_path_binding(tmp_path):
    source = tmp_path / "case.genkey"
    source.write_text("CASE\n", encoding="utf-8")

    display = approval_display.build(
        "run_execute",
        {"source": str(source), "selection_id": "selection_exact"},
        StringPaths(),
        lambda *_: {
            "selection_id": "selection_exact",
            "runtime_id": "olga-2022.1",
            "detection": {"exe": r"C:\\OLGA\\OLGA-2022.1.0.exe"},
            "timeout_s": 3600,
            "context_generation": 0,
        },
    )

    assert display["case"] == "case.genkey"
    assert display["source_sha256"] == approval_display.file_sha256(source)


def test_run_display_rejects_preview_identity_drift(tmp_path):
    source = tmp_path / "case.genkey"
    source.write_text("CASE\n", encoding="utf-8")
    def preview(*_):
        return {"selection_id": "different"}

    with pytest.raises(ToolError, match="selection"):
        approval_display.build(
            "run_execute",
            {"source": str(source), "selection_id": "selection_exact"},
            Paths(),
            preview,
        )
