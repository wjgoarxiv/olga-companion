from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import result_artifacts
from olga_companion.agent import result_artifact_tools, tool_read_tools
from olga_companion.agent.tool_validation import PathBindings, ToolError
from olga_companion.genkey_static import OlgaInputError


def _paths(source: Path) -> PathBindings:
    return PathBindings(
        input_file=lambda value, _suffixes: value,
        result_file=lambda _value: str(source),
        set_active_case=lambda _value: None,
    )


@pytest.mark.parametrize(
    "lineage",
    [
        {
            "source_kind": "workspace",
            "source_id": "/mnt/c/private/source.tpl",
            "source_sha256": "not-a-hash",
            "operation": "unknown",
        },
        {
            "source_kind": "workspace",
            "source_id": "workspace:a//source.tpl",
            "source_sha256": "a" * 64,
            "operation": "results_csv",
        },
        {
            "source_kind": "run",
            "source_id": "workspace:source.tpl",
            "source_sha256": "a" * 64,
            "operation": "results_csv",
        },
        {
            "source_kind": "workspace",
            "source_id": "workspace:source.tpl",
            "source_sha256": "a" * 64,
            "operation": "unknown",
        },
    ],
)
def test_register_rejects_invalid_lineage_before_persisting_or_returning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lineage: result_artifacts.ArtifactLineage,
) -> None:
    # Given: a contained CSV with an absolute, invalid public source identity.
    exports = tmp_path / "exports"
    artifact = exports / "results" / "request" / "series.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"time,value\n0,1\n")
    monkeypatch.setattr(result_artifacts, "exports_root", lambda: exports)

    # When / Then: boundary validation runs before a receipt file or value is issued.
    with pytest.raises(OlgaInputError, match="lineage|receipt|invalid"):
        result_artifacts.register(
            artifact,
            kind="csv",
            lineage=lineage,
            workspace_generation=1,
        )
    receipt_root = exports / ".artifact-receipts"
    assert not receipt_root.exists() or list(receipt_root.iterdir()) == []


def test_report_figure_rejects_a_source_mutation_before_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a figure producer that reports its source changed while rendering.
    source = tmp_path / "source.tpl"
    source.write_bytes(b"moving result")
    exports = tmp_path / "exports"
    figure = exports / "reports" / "request" / "figure.png"
    figure.parent.mkdir(parents=True)
    figure.write_bytes(b"png")
    monkeypatch.setattr(result_artifact_tools.result_artifacts, "exports_root", lambda: exports)
    monkeypatch.setattr(
        result_artifact_tools.reports,
        "generate_figure",
        lambda *_args, **_kwargs: {
            "ok": True,
            "figure": str(figure),
            "sources": [{"mutated": True, "sha256": "a" * 64}],
        },
    )

    # When / Then: a moving source cannot mint a trusted figure receipt.
    with pytest.raises(ToolError, match="changed|mutated|source"):
        tool_read_tools.report_figure(
            {
                "kind": "liqc-timeseries",
                "file": "workspace:source.tpl",
                "branch": "PIPELINE",
            },
            _paths(source),
        )
