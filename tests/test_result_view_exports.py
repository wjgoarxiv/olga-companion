from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Never, TypeAlias

import pytest

from olga_companion import results as results_module

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ExpectedPlotFailure(RuntimeError):
    message: str

    def __str__(self) -> str:
        return self.message


def test_selected_csv_consumes_the_same_view_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.tpl"
    source.write_bytes(b"read-only source")
    exports = tmp_path / "exports"
    exports.mkdir()
    captured: dict = {}

    monkeypatch.setattr(results_module, "resolve_result", lambda _path: source)
    monkeypatch.setattr(results_module, "exports_root", lambda: exports)

    def fake_series(path: str, variable: str, position: str | None = None, **view: JsonValue) -> JsonObject:
        captured.update(view)
        return {
            "path": str(source),
            "variable": variable,
            "position": position,
            "unit": "bar",
            "time_unit": "min",
            "time": [2.0, 3.0],
            "values": [3.0, 4.0],
            "analysis": {"samples": 2},
            "view": {},
        }

    monkeypatch.setattr(results_module, "variable_series", fake_series)

    exported = results_module.export_selected_series_csv(
        str(source),
        "PT",
        "B",
        value_unit="bar",
        time_unit="min",
        quantity_kind="delta",
        range_spec={"mode": "tail", "fraction": 0.5},
    )

    assert captured == {
        "value_unit": "bar",
        "time_unit": "min",
        "quantity_kind": "delta",
        "range_spec": {"mode": "tail", "fraction": 0.5},
    }
    with Path(exported["csv"]).open(newline="", encoding="utf-8") as handle:
        assert list(csv.reader(handle)) == [["time_min", "PT@B"], ["2.0", "3.0"], ["3.0", "4.0"]]
    assert exported["provenance"]["view"] == {
        "value_unit": "bar",
        "time_unit": "min",
        "quantity_kind": "delta",
        "range": {"mode": "tail", "fraction": 0.5},
    }
    assert source.read_bytes() == b"read-only source"


def test_publication_plot_passes_one_shared_view_to_renderer_without_source_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.tpl"
    source.write_bytes(b"immutable publication source")
    exports = tmp_path / "exports"
    exports.mkdir()
    captured: dict = {}
    viewed = {
        "path": str(source),
        "variable": "TM",
        "position": "B",
        "unit": "F",
        "time_unit": "min",
        "time": [2.0, 3.0],
        "values": [18.0, 36.0],
        "analysis": {"samples": 2, "minimum": 18.0, "maximum": 36.0},
        "view": {
            "value_conversion": {"quantity_kind": "delta", "status": "converted"},
            "time_conversion": {"status": "converted"},
            "range": {"mode": "tail", "fraction": 0.5, "start": 2.0, "end": 3.0, "samples": 2},
        },
    }

    monkeypatch.setattr(results_module, "resolve_result", lambda _path: source)
    monkeypatch.setattr(results_module, "exports_root", lambda: exports)

    def fake_series(path: str, variable: str, position: str | None = None, **view: JsonValue) -> JsonObject:
        assert list(exports.iterdir()) == [], "series validation must precede output directory creation"
        captured["series_request"] = {"path": path, "variable": variable, "position": position, **view}
        return viewed

    def fake_render(series: JsonObject, out_dir: Path) -> dict[str, str]:
        captured["rendered_series"] = series
        png = out_dir / "TM_B.png"
        pdf = out_dir / "TM_B.pdf"
        png.write_bytes(b"png")
        pdf.write_bytes(b"pdf")
        return {"png": str(png), "pdf": str(pdf)}

    monkeypatch.setattr(results_module, "variable_series", fake_series)
    monkeypatch.setattr(results_module, "render_publication_series", fake_render)

    result = results_module.plot_result(
        str(source),
        variables=["TM"],
        position="B",
        value_unit="F",
        time_unit="min",
        quantity_kind="delta",
        range_spec={"mode": "tail", "fraction": 0.5},
    )

    assert captured["series_request"] == {
        "path": str(source),
        "variable": "TM",
        "position": "B",
        "value_unit": "F",
        "time_unit": "min",
        "quantity_kind": "delta",
        "range_spec": {"mode": "tail", "fraction": 0.5},
    }
    assert captured["rendered_series"] is viewed
    assert result["analysis"] is viewed["analysis"]
    assert result["view"] is viewed["view"]
    assert source.read_bytes() == b"immutable publication source"
    assert result["source_mutated"] is False


def test_rejected_publication_series_leaves_no_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion.genkey_static import OlgaInputError

    source = tmp_path / "source.tpl"
    source.write_bytes(b"immutable rejected source")
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setattr(results_module, "resolve_result", lambda _path: source)
    monkeypatch.setattr(results_module, "exports_root", lambda: exports)

    def reject_series(*_args: JsonValue, **_kwargs: JsonValue) -> Never:
        raise OlgaInputError("Result range bounds are reversed.")

    monkeypatch.setattr(results_module, "variable_series", reject_series)

    with pytest.raises(ValueError, match="reversed"):
        results_module.plot_result(
            str(source),
            variables=["PT"],
            position="B",
            range_spec={"mode": "bounds", "start": 2.0, "end": 1.0},
        )

    assert list(exports.iterdir()) == []
    assert source.read_bytes() == b"immutable rejected source"


@pytest.mark.parametrize(
    "suffix, kwargs, message",
    [
        (".tpl", {"variables": None, "position": "B"}, "exactly one variable"),
        (".tpl", {"variables": ["PT"], "value_unit": "bar"}, "require a single position"),
        (".ppl", {"variables": None, "branch": None}, "requires both"),
    ],
)
def test_rejected_plot_arguments_leave_no_output_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    kwargs: dict,
    message: str,
) -> None:
    source = tmp_path / f"source{suffix}"
    source.write_bytes(b"immutable invalid request source")
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setattr(results_module, "resolve_result", lambda _path: source)
    monkeypatch.setattr(results_module, "exports_root", lambda: exports)

    with pytest.raises(ValueError, match=message):
        results_module.plot_result(str(source), **kwargs)

    assert list(exports.iterdir()) == []


def test_publication_time_axis_omits_unknown_unit() -> None:
    from olga_companion.publication_plot import _time_axis_label

    assert _time_axis_label(None) == "Time"
    assert _time_axis_label("") == "Time"
    assert _time_axis_label("min") == "Time (min)"


def test_failed_publication_render_removes_only_its_request_export_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.tpl"
    source.write_bytes(b"immutable render failure source")
    exports = tmp_path / "exports"
    exports.mkdir()
    shared = exports / "keep.txt"
    shared.write_text("keep", encoding="utf-8")
    series = {
        "path": str(source),
        "variable": "PT",
        "position": "B",
        "unit": "bar",
        "time_unit": "min",
        "time": [1.0],
        "values": [2.0],
        "analysis": {"samples": 1},
        "view": {},
    }
    monkeypatch.setattr(results_module, "resolve_result", lambda _path: source)
    monkeypatch.setattr(results_module, "exports_root", lambda: exports)
    monkeypatch.setattr(results_module, "variable_series", lambda *_args, **_kwargs: series)

    def fail_render(_series: JsonObject, out_dir: Path) -> Never:
        (out_dir / "partial.png").write_bytes(b"partial")
        raise ExpectedPlotFailure("renderer failed")

    monkeypatch.setattr(results_module, "render_publication_series", fail_render)

    with pytest.raises(RuntimeError, match="renderer failed"):
        results_module.plot_result(str(source), variables=["PT"], position="B")

    results_root = exports / "results"
    assert not results_root.exists() or list(results_root.iterdir()) == []
    assert shared.read_text(encoding="utf-8") == "keep"
    assert source.read_bytes() == b"immutable render failure source"


def test_failed_plot_tool_removes_only_its_request_export_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.tpl"
    source.write_bytes(b"immutable plot tool failure source")
    exports = tmp_path / "exports"
    exports.mkdir()
    shared = exports / "keep.txt"
    shared.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(results_module, "resolve_result", lambda _path: source)
    monkeypatch.setattr(results_module, "exports_root", lambda: exports)

    def fail_tool(_name: str, args: list[str], **_kwargs: JsonValue) -> Never:
        out_dir = Path(args[args.index("--out-dir") + 1])
        (out_dir / "partial.png").write_bytes(b"partial")
        raise ExpectedPlotFailure("plot tool failed")

    monkeypatch.setattr(results_module, "run_tool", fail_tool)

    with pytest.raises(RuntimeError, match="plot tool failed"):
        results_module.plot_result(str(source), variables=["PT"])

    results_root = exports / "results"
    assert not results_root.exists() or list(results_root.iterdir()) == []
    assert shared.read_text(encoding="utf-8") == "keep"
    assert source.read_bytes() == b"immutable plot tool failure source"
