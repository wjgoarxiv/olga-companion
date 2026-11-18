from __future__ import annotations

from pathlib import Path
import json
from typing import Any

import pytest

from olga_companion.agent import result_tools, tool_read_tools
from olga_companion.agent.tool_validation import PathBindings, ToolError
from olga_companion.result_provenance import ResultSourceChangedError


def _paths(source: Path) -> PathBindings:
    return PathBindings(
        input_file=lambda value, _suffixes: value,
        result_file=lambda _value: str(source),
        set_active_case=lambda _value: None,
    )


def test_results_inventory_is_newest_first_hashed_and_path_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an opaque workspace result snapshot with older and newer files.
    source = tmp_path / "newest.tpl"
    source.write_bytes(b"stable result source")
    monkeypatch.setattr(
        tool_read_tools.workspace,
        "results_snapshot",
        lambda: {
            "root": str(tmp_path),
            "generation": 7,
            "results": [
                {"id": "workspace:older.tpl", "name": "older.tpl", "suffix": ".tpl", "modified_ns": 1, "origin": "workspace"},
                {"id": "workspace:newest.tpl", "name": "newest.tpl", "suffix": ".tpl", "modified_ns": 2, "origin": "workspace"},
            ],
        },
    )

    # When: Chat discovers only the newest result.
    result = tool_read_tools.results_inventory({"offset": 0, "limit": 1}, _paths(source))

    # Then: the source is hash-bound without publishing a filesystem root or path.
    assert result["total_results"] == 2
    assert result["returned_results"] == 1
    assert result["truncated"] is True
    assert result["workspace_generation"] == 7
    assert result["results"][0]["result_id"] == "workspace:newest.tpl"
    assert result["results"][0]["source_sha256"]
    assert result["results"][0]["lineage"] == {
        "source_kind": "workspace",
        "source_id": "workspace:newest.tpl",
    }
    assert "root" not in result
    assert str(tmp_path) not in str(result)


def test_results_inventory_rejects_a_source_hash_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one result whose digest changes during inventory binding.
    source = tmp_path / "moving.tpl"
    source.write_bytes(b"moving result source")
    monkeypatch.setattr(
        tool_read_tools.workspace,
        "results_snapshot",
        lambda: {
            "root": str(tmp_path),
            "generation": 1,
            "results": [
                {"id": "workspace:moving.tpl", "name": "moving.tpl", "suffix": ".tpl", "modified_ns": 1, "origin": "workspace"},
            ],
        },
    )
    digests = iter(("a" * 64, "b" * 64))
    monkeypatch.setattr(result_tools.results, "file_sha256", lambda _path: next(digests))

    # When / Then: discovery fails closed instead of returning a stale identity.
    with pytest.raises(ResultSourceChangedError):
        tool_read_tools.results_inventory({}, _paths(source))


@pytest.mark.parametrize(
    ("truncation", "expected"),
    [
        ("head", [2.0, 3.0]),
        ("tail", [4.0, 5.0]),
        ("uniform", [2.0, 5.0]),
    ],
)
def test_results_series_returns_a_bounded_numeric_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    truncation: str,
    expected: list[float],
) -> None:
    # Given: a stable six-row PT series and a two-row Chat budget after offset.
    source = tmp_path / "case.tpl"
    source.write_bytes(b"stable result source")

    def fake_series(
        path: str,
        variable: str,
        position: str | None = None,
        **view: Any,
    ) -> dict[str, Any]:
        assert path == str(source)
        assert view["range_spec"] == {"mode": "bounds", "start": 0.0, "end": 5.0}
        return {
            "path": str(source),
            "variable": variable,
            "position": position,
            "unit": "bar",
            "time_unit": "s",
            "time": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
            "values": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
            "analysis": {"samples": 6, "minimum": 10.0, "maximum": 15.0},
            "view": {},
        }

    monkeypatch.setattr(result_tools.results, "variable_series", fake_series)

    # When: Chat requests a bounded page with an explicit strategy.
    result = tool_read_tools.results_series(
        {
            "result_id": "workspace:case.tpl",
            "variable": "PT",
            "position": "OUTLET",
            "offset": 2,
            "row_limit": 2,
            "truncation": truncation,
            "time_range": {"start": 0.0, "end": 5.0},
        },
        _paths(source),
    )

    # Then: numeric rows, units, pagination, analysis and source identity are explicit.
    assert [row["time"] for row in result["rows"]] == expected
    assert result["total_rows"] == 6
    assert result["returned_rows"] == 2
    assert result["row_limit"] == 2
    assert result["units"] == {"time": "s", "value": "bar"}
    assert result["position"] == "OUTLET"
    assert result["time_range"] == {"start": 0.0, "end": 5.0}
    assert result["truncated"] is True
    assert result["truncation"] == truncation
    assert result["analysis"]["samples"] == 6
    assert "path" not in result
    assert str(tmp_path) not in str(result)


def test_results_series_rejects_invalid_runtime_bounds(tmp_path: Path) -> None:
    # Given: validation-bypassing arguments reaching the adapter directly.
    source = tmp_path / "case.tpl"
    source.write_bytes(b"stable result source")

    # When / Then: the adapter still refuses an oversized row budget.
    with pytest.raises(ToolError, match="row_limit"):
        tool_read_tools.results_series(
            {"result_id": "workspace:case.tpl", "variable": "PT", "row_limit": 5001},
            _paths(source),
        )


@pytest.mark.parametrize(
    "result_id",
    ["workspace:a//b.tpl", "workspace:a/", "workspace:a\x7fb.tpl"],
)
def test_result_id_rejects_empty_segments_trailing_slash_and_del(result_id: str) -> None:
    # Given: an identifier that cannot be represented by the frontend grammar.
    # When / Then: backend canonicalization rejects it before filesystem resolution.
    with pytest.raises(ToolError, match="opaque result_id"):
        result_tools.canonical_result_id(result_id)


def test_results_series_applies_a_safe_transcript_row_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a stable result with one thousand rows and a permissive caller limit.
    source = tmp_path / "large.tpl"
    source.write_bytes(b"large stable result")
    monkeypatch.setattr(
        result_tools.results,
        "variable_series",
        lambda *_args, **_kwargs: {
            "time": [float(index) for index in range(1000)],
            "values": [float(index) for index in range(1000)],
            "unit": "bar",
            "time_unit": "s",
            "position": "OUTLET",
            "analysis": {"samples": 1000, "minimum": 0.0, "maximum": 999.0, "mean": 499.5},
        },
    )

    # When: the model requests more rows than fit safely in one transcript result.
    result = tool_read_tools.results_series(
        {
            "result_id": "workspace:large.tpl",
            "variable": "PT",
            "row_limit": 1000,
            "truncation": "uniform",
        },
        _paths(source),
    )

    # Then: metadata remains truthful and the result stays below the tool byte cap.
    assert result["row_limit"] == 1000
    assert result["returned_rows"] == len(result["rows"])
    assert result["returned_rows"] <= 200
    assert result["truncated"] is True
    assert len(json.dumps(result)) < 16_384


def test_results_series_rejects_a_post_read_source_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a source whose hash changes after the series reader returns.
    source = tmp_path / "moving.tpl"
    source.write_bytes(b"moving result")
    monkeypatch.setattr(
        result_tools.results,
        "variable_series",
        lambda *_args, **_kwargs: {
            "time": [0.0],
            "values": [1.0],
            "unit": "bar",
            "time_unit": "s",
            "position": "OUTLET",
            "analysis": {"samples": 1},
        },
    )
    digests = iter(("a" * 64, "b" * 64))
    monkeypatch.setattr(result_tools.results, "file_sha256", lambda _path: next(digests))

    # When / Then: no stale numeric table is issued.
    with pytest.raises(ResultSourceChangedError):
        tool_read_tools.results_series(
            {"result_id": "workspace:moving.tpl", "variable": "PT"},
            _paths(source),
        )
