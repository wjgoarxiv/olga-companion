from __future__ import annotations

import csv
from pathlib import Path
import subprocess
from typing import TypeAlias

import pytest
from PIL import Image

import olga_companion.results as results_module
from olga_companion.genkey_static import file_sha256
from olga_companion.results import (
    _require_tokens,
    extract_csv,
    export_selected_series_csv,
    load_result,
    plot_result,
    results_toolkit_status,
    variable_series,
)
from result_test_support import PPL, TPL
from result_test_support import exports_tmp as exports_tmp

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

pytestmark = pytest.mark.skipif(
    not results_toolkit_status()["available"], reason="OLGA result toolkit scripts are unavailable"
)


def test_extract_csv_writes_only_into_exports(exports_tmp: Path) -> None:
    # PT and QLST both exist as boundary/position trends (no branch qualifier),
    # which is what data_exporter matches when no --branch is given.
    result = extract_csv(str(TPL), ["PT", "QLST"])
    assert result["ok"] is True
    csv_path = Path(result["csv"])
    assert csv_path.exists()
    assert csv_path.is_relative_to(exports_tmp)
    header = csv_path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header == "time_s,PT,QLST"


def test_selected_series_csv_uses_exact_position_series_data(
    exports_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, str | None]] = []
    source_hash = file_sha256(TPL)

    def fake_series(path: str, variable: str, position: str | None = None) -> JsonObject:
        calls.append((path, variable, position))
        return {
            "path": str(TPL),
            "variable": variable,
            "position": "B",
            "unit": "Pa",
            "time_unit": "s",
            "time": [0, 2.5, 10],
            "values": [101.25, 102.5, 99.75],
            "description": "Pressure",
            "analysis": {},
        }

    monkeypatch.setattr(results_module, "variable_series", fake_series)

    first = export_selected_series_csv(str(TPL), "PT", "POSITION - B")
    second = export_selected_series_csv(str(TPL), "PT", "POSITION - B")

    csv_path = Path(first["csv"])
    assert calls == [(str(TPL), "PT", "POSITION - B"), (str(TPL), "PT", "POSITION - B")]
    assert csv_path.is_file() and csv_path.is_relative_to(exports_tmp)
    assert csv_path != Path(second["csv"]), "every selected-series export needs a unique contained filename"
    with csv_path.open(newline="", encoding="utf-8") as handle:
        assert list(csv.reader(handle)) == [
            ["time_s", "PT@B"],
            ["0", "101.25"],
            ["2.5", "102.5"],
            ["10", "99.75"],
        ]
    assert first["download_path"] == first["csv"]
    assert csv_path.name.startswith("selected-series-PT-B-")
    assert first["download_name"] == csv_path.name
    assert first["series_label"] == "PT@B"
    assert first["variable"] == "PT"
    assert first["position"] == "B"
    assert first["unit"] == "Pa"
    assert first["time_unit"] == "s"
    assert first["row_count"] == 3
    assert first["provenance"] == {
        "kind": "selected_series",
        "source_path": str(TPL),
        "source_sha256": source_hash,
        "variable": "PT",
        "requested_position": "POSITION - B",
        "position": "B",
        "unit": "Pa",
        "time_unit": "s",
        "safe_variable": "PT",
        "safe_position": "B",
    }
    assert first["source_mutated"] is False
    assert file_sha256(TPL) == source_hash


@pytest.mark.parametrize(
    "variable, position, message",
    [("PT\n", "POSITION - B", "Invalid variable"), ("PT", "B\n", "Invalid result position")],
)
def test_selected_series_csv_uses_existing_series_validation_before_export(
    exports_tmp: Path, variable: str, position: str, message: str
) -> None:
    before = list(exports_tmp.iterdir())

    with pytest.raises(ValueError, match=message):
        export_selected_series_csv(str(TPL), variable, position)

    assert list(exports_tmp.iterdir()) == before


def test_variable_tokens_are_strictly_validated() -> None:
    with pytest.raises(ValueError, match="Invalid variable"):
        _require_tokens(["PT\n"], "variable")
    with pytest.raises(ValueError, match="Invalid variable"):
        _require_tokens(["-evil"], "variable")
    with pytest.raises(ValueError, match="Invalid variable"):
        _require_tokens(["PT,TM"], "variable")


def test_plot_tpl_produces_png(exports_tmp: Path) -> None:
    result = plot_result(str(TPL), variables=["PT", "TM", "HOL"])
    assert result["ok"] is True
    assert result["plots"], "at least one plot file expected"
    for plot in result["plots"]:
        assert plot.endswith(".png")
        assert Path(plot).exists()
        assert Path(plot).is_relative_to(exports_tmp)


def test_publication_plot_embeds_resolved_font_and_600_dpi(exports_tmp: Path) -> None:
    variable = load_result(str(TPL))["variables"][0]
    result = plot_result(
        str(TPL),
        variables=[variable["variable"]],
        position=variable["position"],
    )
    assert result["ok"] is True
    publication = result["publication"]
    assert publication["font_family"]
    assert Path(publication["font_path"]).is_file()
    png = Path(result["plots"][0])
    pdf = Path(result["documents"][0])
    assert png.is_relative_to(exports_tmp) and pdf.is_relative_to(exports_tmp)
    with Image.open(png) as image:
        assert image.info["dpi"][0] >= 599
    fonts = subprocess.run(["pdffonts", str(pdf)], check=True, capture_output=True, text=True).stdout
    expected_font = publication["font_family"].replace(" ", "").casefold()
    assert expected_font in fonts.replace(" ", "").casefold()


def test_series_interpretation_is_descriptive_and_position_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    class Command:
        exit_code = 0
        stdout = '{"time":[0,5,10],"values":[10,12,15],"unit":"Pa","position":"B"}'

    def fake_run_tool(_name: str, args: list[str], **_kwargs: JsonValue) -> Command:
        captured.extend(args)
        return Command()

    monkeypatch.setattr(results_module, "run_tool", fake_run_tool)
    result = variable_series(str(TPL), "PT", position="POSITION - B")
    assert captured[-2:] == ["--position", "B"]
    assert result["analysis"]["minimum"] == 10
    assert result["analysis"]["maximum"] == 15
    assert result["analysis"]["final"] == 15
    assert result["analysis"]["direction"] == "increasing"
    assert result["analysis"]["scope"] == "descriptive"


def test_plot_ppl_rejects_multiple_variables() -> None:
    with pytest.raises(ValueError, match="exactly one variable"):
        plot_result(str(PPL), variables=["PT", "HOL"], branch="PIPELINE")


def test_plot_ppl_profile_produces_png() -> None:
    result = plot_result(str(PPL), variables=["PT"], branch="PIPELINE")
    assert result["ok"] is True
    assert result["plots"]
    assert all(Path(plot).exists() for plot in result["plots"])
