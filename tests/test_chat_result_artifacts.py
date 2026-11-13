from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion.agent import result_artifact_tools, tool_read_tools
from olga_companion.agent.tool_validation import PathBindings, ToolError
from olga_companion.genkey_static import OlgaInputError, file_sha256


def _paths(source: Path) -> PathBindings:
    return PathBindings(
        input_file=lambda value, _suffixes: value,
        result_file=lambda _value: str(source),
        set_active_case=lambda _value: None,
    )


def test_results_csv_returns_one_opaque_actionable_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a contained CSV export with private absolute-path producer output.
    source = tmp_path / "source.tpl"
    source.write_bytes(b"stable result")
    exports = tmp_path / "exports"
    artifact = exports / "results" / "request" / "PT.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"time,PT\n0,1\n")
    monkeypatch.setattr(result_artifact_tools.result_artifacts, "exports_root", lambda: exports)
    monkeypatch.setattr(result_artifact_tools.workspace, "context_generation", lambda: 11)
    monkeypatch.setattr(
        result_artifact_tools.results,
        "extract_csv",
        lambda *_args, **_kwargs: {
            "ok": True,
            "csv": str(artifact),
            "download_path": str(artifact),
            "path": str(source),
            "source_sha256_before": file_sha256(source),
        },
    )

    # When: Chat exports a result table.
    receipt = tool_read_tools.results_csv(
        {"path": "workspace:source.tpl", "variables": ["PT"]},
        _paths(source),
    )

    # Then: only a hash-bound opaque receipt crosses the model/public boundary.
    assert receipt["artifact_id"].startswith("artifact_")
    assert receipt["kind"] == "csv"
    assert receipt["mime"] == "text/csv"
    assert receipt["size_bytes"] == artifact.stat().st_size
    assert receipt["sha256"] == file_sha256(artifact)
    assert receipt["suggested_filename"] == "PT.csv"
    assert receipt["workspace_generation"] == 11
    assert receipt["actions"] == ["download", "open_in_results", "native_save_as"]
    assert str(tmp_path) not in str(receipt)


def test_artifact_lineage_rejects_an_absolute_source_identifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a legacy absolute result input and an otherwise valid CSV export.
    source = tmp_path / "source.tpl"
    source.write_bytes(b"stable result")
    exports = tmp_path / "exports"
    artifact = exports / "results" / "request" / "PT.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"time,PT\n0,1\n")
    monkeypatch.setattr(result_artifact_tools.result_artifacts, "exports_root", lambda: exports)
    monkeypatch.setattr(result_artifact_tools.workspace, "context_generation", lambda: 1)
    monkeypatch.setattr(
        result_artifact_tools.results,
        "extract_csv",
        lambda *_args, **_kwargs: {
            "ok": True,
            "csv": str(artifact),
            "source_sha256_before": file_sha256(source),
        },
    )

    # When / Then: Chat must first use results_inventory to obtain a safe result_id.
    with pytest.raises(ToolError, match="result_id|inventory|opaque"):
        tool_read_tools.results_csv(
            {"path": str(source), "variables": ["PT"]},
            _paths(source),
        )


def test_results_csv_reuses_the_selected_series_exporter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one position-selected series export and its view contract.
    source = tmp_path / "source.tpl"
    source.write_bytes(b"stable result")
    exports = tmp_path / "exports"
    artifact = exports / "results" / "request" / "PT.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"time,PT\n1,2\n")
    monkeypatch.setattr(result_artifact_tools.result_artifacts, "exports_root", lambda: exports)
    monkeypatch.setattr(result_artifact_tools.workspace, "context_generation", lambda: 1)
    captured: dict[str, object] = {}

    def fake_selected(*args: object, **kwargs: object) -> dict[str, object]:
        captured.update({"args": args, "kwargs": kwargs})
        return {
            "ok": True,
            "csv": str(artifact),
            "source_sha256_before": file_sha256(source),
        }

    monkeypatch.setattr(result_artifact_tools.results, "export_selected_series_csv", fake_selected)

    # When: Chat requests the same bounded engineering view as the numeric table.
    receipt = tool_read_tools.results_csv(
        {
            "path": "workspace:source.tpl",
            "variables": ["PT"],
            "position": "OUTLET",
            "value_unit": "bar",
            "time_unit": "min",
            "quantity_kind": "point",
            "time_range": {"start": 1.0, "end": 2.0},
        },
        _paths(source),
    )

    # Then: the existing selected-series exporter receives one identical view.
    assert receipt["kind"] == "csv"
    assert captured["args"] == (str(source), "PT", "OUTLET")
    assert captured["kwargs"] == {
        "value_unit": "bar",
        "time_unit": "min",
        "quantity_kind": "point",
        "range_spec": {"mode": "bounds", "start": 1.0, "end": 2.0},
    }


@pytest.mark.parametrize(
    ("requested_format", "expected_kind", "expected_mime"),
    [("png", "png", "image/png"), ("pdf", "pdf", "application/pdf")],
)
def test_results_plot_selects_one_requested_artifact_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requested_format: str,
    expected_kind: str,
    expected_mime: str,
) -> None:
    # Given: one publication render with PNG and PDF outputs.
    source = tmp_path / "source.tpl"
    source.write_bytes(b"stable result")
    exports = tmp_path / "exports"
    png = exports / "results" / "request" / "plot.png"
    pdf = exports / "results" / "request" / "plot.pdf"
    png.parent.mkdir(parents=True)
    png.write_bytes(b"png bytes")
    pdf.write_bytes(b"pdf bytes")
    monkeypatch.setattr(result_artifact_tools.result_artifacts, "exports_root", lambda: exports)
    monkeypatch.setattr(result_artifact_tools.workspace, "context_generation", lambda: 3)
    captured: dict[str, object] = {}

    def fake_plot(*args: object, **kwargs: object) -> dict[str, object]:
        captured.update({"args": args, "kwargs": kwargs})
        return {
            "ok": True,
            "plots": [str(png)],
            "documents": [str(pdf)],
            "source_sha256_before": file_sha256(source),
        }

    monkeypatch.setattr(
        result_artifact_tools.results,
        "plot_result",
        fake_plot,
    )

    # When: Chat requests exactly one export representation.
    receipt = tool_read_tools.results_plot(
        {
            "path": "workspace:source.tpl",
            "variables": ["PT"],
            "position": "OUTLET",
            "value_unit": "bar",
            "time_unit": "min",
            "quantity_kind": "point",
            "time_range": {"start": 60.0, "end": 120.0},
            "format": requested_format,
        },
        _paths(source),
    )

    # Then: one correctly typed receipt is returned without leaking either path.
    assert receipt["kind"] == expected_kind
    assert receipt["mime"] == expected_mime
    assert captured["kwargs"] == {
        "value_unit": "bar",
        "time_unit": "min",
        "quantity_kind": "point",
        "range_spec": {"mode": "bounds", "start": 60.0, "end": 120.0},
    }
    assert str(png) not in str(receipt)
    assert str(pdf) not in str(receipt)


def test_artifact_lookup_is_restart_safe_historical_and_hash_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a registered CSV artifact from an older workspace generation.
    from olga_companion import result_artifacts

    exports = tmp_path / "exports"
    artifact = exports / "results" / "request" / "series.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"time,value\n0,1\n")
    monkeypatch.setattr(result_artifacts, "exports_root", lambda: exports)
    receipt = result_artifacts.register(
        artifact,
        kind="csv",
        lineage={
            "source_kind": "workspace",
            "source_id": "workspace:source.tpl",
            "source_sha256": "a" * 64,
            "operation": "results_csv",
        },
        workspace_generation=4,
    )

    # When: the durable lookup is reopened after the current workspace changes.
    result_artifacts._RECEIPT_CACHE.clear()
    resolved = result_artifacts.resolve(receipt["artifact_id"])

    # Then: historical exports remain readable and still match their receipt.
    assert resolved == artifact.resolve()
    assert receipt["workspace_generation"] == 4
    assert result_artifacts.read_receipt(receipt["artifact_id"]) == receipt

    # When / Then: a changed artifact is never served under the old receipt.
    artifact.write_bytes(b"mutated")
    with pytest.raises(OlgaInputError, match="changed|integrity|hash"):
        result_artifacts.resolve(receipt["artifact_id"])


@pytest.mark.parametrize(
    "artifact_id",
    ["../../outside", "artifact_nothex", "artifact_" + "f" * 31, "artifact_" + "g" * 32],
)
def test_artifact_lookup_rejects_forged_or_traversing_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_id: str,
) -> None:
    # Given: an isolated artifact receipt store.
    from olga_companion import result_artifacts

    monkeypatch.setattr(result_artifacts, "exports_root", lambda: tmp_path / "exports")

    # When / Then: forged identifiers cannot become filesystem paths.
    with pytest.raises(OlgaInputError, match="artifact"):
        result_artifacts.resolve(artifact_id)
