"""A .ppl profile figure states its unit and can be drawn in another one."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from olga_companion import result_plot_exports
from olga_companion.agent import tools
from olga_companion.agent.tool_validation import ToolError, validate_tool_arguments
from olga_companion.genkey_static import OlgaInputError, file_sha256

SCRIPT = Path(__file__).resolve().parents[1] / "resources" / "olga-toolkit" / "scripts" / "fast_ppl_plotter.py"
PROFILE = {
    "variable": "PT", "branch": "LINE", "timestep": 7201.788, "timestep_unit": "S",
    "positions": [25.0, 75.0, 125.0], "values": [4.1e6, None, 4.0e6], "unit": "PA",
}


def _plot(tmp_path: Path, **view: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = tmp_path / "case.ppl"
    source.write_bytes(b"profile")
    drawn: list[dict[str, Any]] = []

    def renderer(profile: dict[str, Any], out_dir: Path) -> dict[str, Any]:
        drawn.append(profile)
        png, pdf = out_dir / "LINE_PT_t007201.8.png", out_dir / "LINE_PT_t007201.8.pdf"
        png.write_bytes(b"png")
        pdf.write_bytes(b"pdf")
        return {"png": str(png), "pdf": str(pdf)}

    profile = view.pop("profile", PROFILE)
    options = {"value_unit": None, "time_unit": None, "quantity_kind": "point", "range_spec": None, **view}
    result = result_plot_exports.plot_result(
        str(source), ["PT"], "LINE", None, **options,
        resolve_result=Path, hash_file=file_sha256, exports_root=lambda: tmp_path / "exports",
        require_tokens=lambda values, _kind: values, series_reader=None, publication_renderer=None,
        run_tool=None, result_scripts={}, plot_timeout_s=5,
        profile_reader=lambda *_a: dict(profile), profile_renderer=renderer,
    )
    return result, drawn


def test_a_profile_pdf_with_an_empty_unit_still_draws(tmp_path: Path) -> None:
    # Review 2026-11-27: a pyfas fallback can return unit '' and convert_values refused it.
    result, (drawn,) = _plot(tmp_path, profile={**PROFILE, "unit": ""}, profile_pdf=True)
    assert drawn["values"] == [4.1e6, None, 4.0e6]
    assert result["ok"] is True


def test_a_unit_asked_of_a_unitless_profile_is_refused_in_words(tmp_path: Path) -> None:
    with pytest.raises(OlgaInputError, match="from no unit to bar"):
        _plot(tmp_path, profile={**PROFILE, "unit": ""}, value_unit="bar")


def test_the_catalog_unit_of_a_dash_named_branch_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("result_parser_units", SCRIPT.with_name("result_parser.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "case.ppl"
    path.write_text(
        "'OLGA 2022.1.0'\nPROFILE PLOT\nGEOMETRY ' (M)  '\n"
        "BRANCH\n'LINE-1'\n2\n0.0 100.0\n0.0 1.0\n"
        "BRANCH\n'LINE-10'\n2\n0.0 100.0\n0.0 1.0\n"
        "CATALOG\n3\n"
        "PT 'BOUNDARY:' 'BRANCH:' 'LINE-10' '(BARA)' 'Pressure'\n"
        "PT 'BOUNDARY:' 'BRANCH:' 'LINE-1' '(PA)' 'Pressure'\n"
        "PTX 'BOUNDARY:' 'BRANCH:' 'LINE-1' '(C)' 'Not the variable asked for'\n"
        "TIME SERIES  ' (S)  '\n0.0\n1.0 2.0\n3.0 4.0\n5.0 6.0\n"
    )
    reader = module._SinglePassPpl(str(path))
    assert module.ResultParser._catalog_unit(reader, "PT", "LINE_1") == "PA"
    assert module.ResultParser._catalog_unit(reader, "PT", "LINE-1") == "PA"
    assert module.ResultParser._catalog_unit(reader, "PT", "LINE-10") == "BARA"


def test_a_value_unit_draws_the_converted_profile(tmp_path: Path) -> None:
    result, (drawn,) = _plot(tmp_path, value_unit="bar")
    assert [drawn["values"][0], drawn["values"][2]] == pytest.approx([41.0, 40.0])
    assert drawn["values"][1] is None and drawn["positions"] == PROFILE["positions"]  # the gap stays a gap
    assert drawn["unit"] == "bar"
    assert Path(result["selected_plot"]).suffix == ".png"
    assert Path(result["documents"][0]).suffix == ".pdf"
    assert result["ok"] is True


def test_a_pdf_keeps_the_source_unit(tmp_path: Path) -> None:
    result, (drawn,) = _plot(tmp_path, profile_pdf=True)
    assert drawn["values"] == [4.1e6, None, 4.0e6]
    assert drawn["unit"].casefold() == "pa"
    assert result["documents"]


def test_an_impossible_unit_is_refused_and_leaves_no_folder(tmp_path: Path) -> None:
    with pytest.raises(OlgaInputError, match="convert"):
        _plot(tmp_path, value_unit="kg/s")
    assert not (tmp_path / "exports").exists()


def test_a_time_range_still_belongs_to_trends(tmp_path: Path) -> None:
    with pytest.raises(OlgaInputError):
        _plot(tmp_path, range_spec={"mode": "bounds", "start": 0, "end": 1})


@pytest.mark.parametrize("extra", [{"value_unit": "bar"}, {"value_unit": "bar", "timestep": 60}, {"format": "pdf"}, {"timestep": 60}])
def test_a_profile_takes_a_unit_a_time_and_a_pdf_without_a_position(extra: dict[str, Any]) -> None:
    args = {"path": "workspace:run/case.ppl", "variables": ["PT"], "branch": "LINE", **extra}
    validate_tool_arguments("results_plot", args, tools.TOOLS["results_plot"].parameters)


def test_a_profile_csv_has_no_unit_option() -> None:
    args = {"path": "workspace:run/case.ppl", "variables": ["PT"], "branch": "LINE", "value_unit": "bar"}
    with pytest.raises(ToolError):
        validate_tool_arguments("results_csv", args, tools.TOOLS["results_csv"].parameters)


def test_a_profile_with_a_time_range_is_refused_in_profile_words() -> None:
    args = {"path": "workspace:run/case.ppl", "variables": ["PT"], "branch": "LINE", "time_range": {"start": 0, "end": 1}}
    with pytest.raises(ToolError, match="timestep"):
        validate_tool_arguments("results_plot", args, tools.TOOLS["results_plot"].parameters)


@pytest.mark.parametrize(
    ("tool", "field"),
    [("results_plot", "path"), ("results_csv", "path"), ("results_load", "path"), ("report_figure", "file"),
     ("results_series", "result_id"), ("results_profile", "result_id")],
)
def test_each_result_tool_says_it_takes_a_result_id(tool: str, field: str) -> None:
    described = tools.TOOLS[tool].parameters["properties"][field].get("description", "")
    assert "result_id" in described and "results_inventory" in described


def test_the_toolkit_profile_plot_labels_the_unit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("matplotlib")
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("fast_ppl_plotter_units", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import matplotlib.pyplot as plt

    labels: list[str] = []
    monkeypatch.setattr(plt, "close", lambda fig: labels.append(fig.axes[0].get_ylabel()))
    module._plot_profile([0.0, 1.0], [1.0, 2.0], "PT", "LINE", 1.0, str(tmp_path / "a.png"), unit="PA")
    module._plot_profile([0.0, 1.0], [1.0, 2.0], "PT", "LINE", 1.0, str(tmp_path / "b.png"))
    assert labels == ["PT (PA)", "PT"]
    plotter = object.__new__(module.FastPPLPlotter)
    plotter._units = {("PT", "LINE"): "PA"}
    assert plotter.get_unit("pt", "LINE") == "PA" and plotter.get_unit("HOL", "LINE") is None


def test_the_real_renderer_writes_both_files_and_names_the_time(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    from olga_companion.publication_plot import render_publication_profile

    out = render_publication_profile({**PROFILE, "positions": [25.0, 125.0], "values": [41.0, 40.0], "unit": "bar"}, tmp_path)
    assert Path(out["png"]).name == "LINE_PT_t007201.8.png" and Path(out["png"]).stat().st_size > 1000
    assert Path(out["pdf"]).read_bytes().startswith(b"%PDF")


def test_a_boundary_variable_names_the_branch_as_the_figure_tools_take_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("result_parser_branch", SCRIPT.with_name("result_parser.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ppl = module._parse_catalog_line("ID 'BOUNDARY:' 'BRANCH:' 'LINE_1' '(-)' 'Flow regime'")
    assert (ppl["position"], ppl["unit"], ppl["description"]) == ("LINE_1", "-", "Flow regime")
    tpl = module._parse_catalog_line("VALVDP 'VALVE:' 'V-1' '(PA)' 'Pressure drop'")
    assert tpl["position"] == "VALVE - V-1"


def test_a_small_pressure_drop_is_labelled_with_whole_numbers_not_an_offset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    from olga_companion.publication_plot import render_publication_profile

    offsets: list[str] = []
    close = plt.close
    monkeypatch.setattr(plt, "close", lambda fig: (offsets.append(fig.axes[0].yaxis.get_offset_text().get_text()), close(fig)))
    render_publication_profile({**PROFILE, "positions": [0.07, 0.2], "values": [1.20389, 1.20373], "unit": "bar"}, tmp_path)
    assert offsets == [""]


def test_an_undefined_stretch_breaks_the_line_instead_of_being_bridged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("matplotlib")
    import math

    import matplotlib.pyplot as plt

    from olga_companion.publication_plot import render_publication_profile

    lines: list[list[float]] = []
    markers: list[str] = []
    close = plt.close
    monkeypatch.setattr(plt, "close", lambda fig: (lines.append(list(fig.axes[0].lines[0].get_ydata())), markers.append(fig.axes[0].lines[0].get_marker()), close(fig)))
    profile = {**PROFILE, "positions": [0.0, 100.0, 200.0, 300.0], "values": [50.0, None, None, 40.0], "unit": "bar"}
    render_publication_profile(profile, tmp_path)
    assert [None if math.isnan(v) else v for v in lines[0]] == [50.0, None, None, 40.0]
    assert markers == ["o"]  # a lone point between gaps stays visible
