from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import results
from olga_companion.genkey_static import CommandResult, OlgaInputError
from olga_companion.result_provenance import ResultSourceChangedError
from olga_companion.sidecar import app


def test_variable_series_rejects_and_does_not_cache_when_source_changes_during_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a result source that changes while its variable series is being parsed.
    source = tmp_path / "moving.tpl"
    source.write_bytes(b"series-before-parse")
    cache: OrderedDict[tuple[int, str, str], dict[str, bool]] = OrderedDict()
    monkeypatch.setattr(results, "resolve_result", lambda _value: source)
    monkeypatch.setattr(results, "_LOAD_CACHE", cache)

    def mutate_during_parse(_name: str, args: list[str], **_kwargs: int) -> CommandResult:
        source.write_bytes(b"series-after-parse")
        stdout = '{"time":[0,1],"values":[10,11],"unit":"bar","time_unit":"s","position":"B"}'
        return CommandResult("result_parser.py", args, 0, stdout, "", False, 1)

    monkeypatch.setattr(results, "run_tool", mutate_during_parse)

    # When the series is read, then the moving source is rejected and uncached.
    with pytest.raises(ResultSourceChangedError, match="changed while it was being read"):
        results.variable_series(str(source), "PT", "B")

    assert cache == OrderedDict()


def test_series_route_returns_clean_error_when_source_changes_during_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given the API reads a result source that changes inside the parser call.
    source = tmp_path / "moving.tpl"
    source.write_bytes(b"series-before-parse")
    monkeypatch.setattr(results, "resolve_result", lambda _value: source)

    def mutate_during_parse(_name: str, args: list[str], **_kwargs: int) -> CommandResult:
        source.write_bytes(b"series-after-parse")
        stdout = '{"time":[0,1],"values":[10,11],"unit":"bar","time_unit":"s","position":"B"}'
        return CommandResult("result_parser.py", args, 0, stdout, "", False, 1)

    monkeypatch.setattr(results, "run_tool", mutate_during_parse)

    # When the series route completes, then it returns the typed public error only.
    response = TestClient(app).post(
        "/api/results/series",
        json={"rel": "moving.tpl", "variable": "PT", "position": "B"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Result source changed while it was being read. Wait for OLGA to finish writing, then retry."
    }


def test_load_result_rejects_and_does_not_cache_when_source_changes_during_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a result source that changes while its index is being parsed.
    source = tmp_path / "moving.tpl"
    source.write_bytes(b"result-before-parse")
    cache: OrderedDict[tuple[int, str, str], dict[str, bool]] = OrderedDict()
    monkeypatch.setattr(results, "resolve_result", lambda _value: source)
    monkeypatch.setattr(results, "_LOAD_CACHE", cache)

    def mutate_during_parse(_path: Path) -> dict[str, bool]:
        source.write_bytes(b"result-after-parse")
        return {"ok": True}

    monkeypatch.setattr(results, "_parse_index", mutate_during_parse)

    # When the result is loaded, then the moving source is rejected and uncached.
    with pytest.raises(OlgaInputError, match="changed while it was being read"):
        results.load_result(str(source))

    assert cache == OrderedDict()


def test_selected_series_csv_rejects_source_change_and_removes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a selected series read that changes its source before publication.
    source = tmp_path / "moving.tpl"
    source.write_bytes(b"series-before-read")
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setattr(results, "resolve_result", lambda _value: source)
    monkeypatch.setattr(results, "exports_root", lambda: exports)

    def mutate_during_series(*_args: str, **_kwargs: str) -> dict[str, str | list[float]]:
        source.write_bytes(b"series-after-read")
        return {
            "variable": "PT",
            "position": "B",
            "unit": "Pa",
            "time_unit": "s",
            "time": [0.0, 1.0],
            "values": [10.0, 11.0],
        }

    monkeypatch.setattr(results, "variable_series", mutate_during_series)

    # When CSV export completes, then it fails closed and retains no CSV.
    with pytest.raises(OlgaInputError, match="changed while it was being read"):
        results.export_selected_series_csv(str(source), "PT", "B")

    assert list(exports.rglob("*.csv")) == []


def test_data_export_csv_rejects_source_change_and_removes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a data exporter that observes a moving source while writing its CSV.
    source = tmp_path / "moving.tpl"
    source.write_bytes(b"export-before-read")
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setattr(results, "resolve_result", lambda _value: source)
    monkeypatch.setattr(results, "exports_root", lambda: exports)

    def mutate_during_export(_name: str, args: list[str], **_kwargs: int) -> CommandResult:
        csv_path = Path(args[args.index("-o") + 1])
        csv_path.write_text("time_s,PT\n0,10\n", encoding="utf-8")
        source.write_bytes(b"export-after-read")
        return CommandResult("data_exporter.py", args, 0, "", "", False, 1)

    monkeypatch.setattr(results, "run_tool", mutate_during_export)

    # When generic CSV export completes, then it fails closed and retains no CSV.
    with pytest.raises(OlgaInputError, match="changed while it was being read"):
        results.extract_csv(str(source), ["PT"])

    assert list(exports.rglob("*.csv")) == []


def test_publication_plot_uses_one_final_hash_and_removes_moving_source_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an A/B/A hash sequence that exposed the former double-final-hash race.
    source = tmp_path / "moving.tpl"
    source.write_bytes(b"publication-source")
    exports = tmp_path / "exports"
    exports.mkdir()
    hashes = iter(["A", "B", "A"])
    hash_calls = 0

    def sequenced_hash(_path: Path) -> str:
        nonlocal hash_calls
        hash_calls += 1
        return next(hashes)

    series: dict[str, str | list[float] | dict[str, int]] = {
        "variable": "PT",
        "position": "B",
        "unit": "Pa",
        "time_unit": "s",
        "time": [0.0],
        "values": [10.0],
        "analysis": {"samples": 1},
        "view": {},
    }

    def render(_series: dict, out_dir: Path) -> dict[str, str]:
        png = out_dir / "PT-B.png"
        pdf = out_dir / "PT-B.pdf"
        png.write_bytes(b"png")
        pdf.write_bytes(b"pdf")
        return {"png": str(png), "pdf": str(pdf)}

    monkeypatch.setattr(results, "resolve_result", lambda _value: source)
    monkeypatch.setattr(results, "exports_root", lambda: exports)
    monkeypatch.setattr(results, "file_sha256", sequenced_hash)
    monkeypatch.setattr(results, "variable_series", lambda *_args, **_kwargs: series)
    monkeypatch.setattr(results, "render_publication_series", render)

    # When the final digest differs, then one final hash rejects and cleans the plot.
    with pytest.raises(OlgaInputError, match="changed while it was being read"):
        results.plot_result(str(source), variables=["PT"], position="B")

    assert hash_calls == 2
    assert list(exports.rglob("*.png")) == []
    assert list(exports.rglob("*.pdf")) == []
