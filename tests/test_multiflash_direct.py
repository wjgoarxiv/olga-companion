"""The app makes an OLGA .tab from an .mfl by running the installed Multiflash engine itself."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from olga_companion import multiflash_direct as md
from olga_companion.fluid_table import FluidTableError

FIX = Path(__file__).parent / "fixtures" / "multiflash"


def _text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_the_table_command_is_read_in_the_units_in_effect_before_it() -> None:
    request = md.read_table_request(_text("gas_water.mfl"))
    assert request["label"] == "GASWATER"
    assert request["temperatures_k"] == [260.0, 300.0, 340.0]
    assert request["pressures_pa"] == [50000.0, 1000000.0, 5000000.0]
    assert request["moles"] == [0.8, 0.1, 0.1]
    assert request["components"] == ["METHANE", "ETHANE", "WATER"]
    assert request["grid_source"] == "mfl"


def test_an_explicit_unit_in_the_table_command_wins() -> None:
    text = _text("gas_water.mfl").replace("temperatures 260 300\n  340 ;", "temperatures C -10 20 60 ;").replace(
        "pressures\n  50000 1000000 5000000", "pressures bar 1 10 50"
    )
    request = md.read_table_request(text)
    assert request["temperatures_k"] == pytest.approx([263.15, 293.15, 333.15])
    assert request["pressures_pa"] == pytest.approx([1e5, 1e6, 5e6])


def test_an_mfl_without_a_table_command_gets_the_stated_default_grid() -> None:
    request = md.read_table_request(_text("no_table.mfl"))
    assert request["grid_source"] == "default"
    assert request["moles"] == [0.9, 0.1]
    assert min(request["pressures_pa"]) <= 50_000.0
    assert max(request["pressures_pa"]) >= 30_000_000.0
    assert min(request["temperatures_k"]) <= 253.15
    assert max(request["temperatures_k"]) >= 423.15


def test_an_mfl_without_amounts_is_refused() -> None:
    with pytest.raises(FluidTableError, match="composition"):
        md.read_table_request("components overwrite 1 METHANE ;\n")


def test_amounts_that_do_not_match_the_components_are_refused() -> None:
    with pytest.raises(FluidTableError, match="3 components"):
        md.read_table_request(_text("gas_water.mfl").replace("amounts .8 .1 .1;", "amounts .8 .2;"))


def test_engine_error_codes_are_explained_from_multiflash_own_list() -> None:
    message = md.explain_error(20575, FIX / "mini.err")
    assert message.startswith("Test record two title.")
    assert "detail line one" in message
    assert md.explain_error(99999, FIX / "mini.err") == "Multiflash error 99999."


def _workspace(tmp_path: Path) -> Path:
    case_dir = tmp_path / "ws"
    case_dir.mkdir()
    shutil.copy(FIX / "gas_water.mfl", case_dir / "gas_water.mfl")
    return case_dir / "gas_water.mfl"


def test_make_tab_writes_a_new_valid_table_next_to_the_mfl(tmp_path: Path) -> None:
    mfl = _workspace(tmp_path)
    seen: dict[str, Any] = {}

    def engine(request: dict[str, Any]) -> dict[str, Any]:
        seen.update(request)
        table = (FIX / "handwritten_3x3.tab").read_text(encoding="utf-8")
        Path(request["tab_path"]).write_text(table.replace("LABEL = probe", f"LABEL = {request['title']}", 1), encoding="utf-8")
        return {"ok": True, "errors": []}

    result = md.make_tab(str(mfl), "case_fluid.tab", engine=engine)
    target = mfl.parent / "case_fluid.tab"
    assert target.is_file()
    assert result["valid"] is True
    assert result["tab_name"] == "case_fluid.tab"
    assert result["grid_source"] == "mfl"
    assert seen["tab_path"] != str(target)  # written beside it first, then moved into place
    assert not [p for p in mfl.parent.iterdir() if p.name.startswith(".")]


def test_make_tab_never_overwrites(tmp_path: Path) -> None:
    mfl = _workspace(tmp_path)
    (mfl.parent / "gas_water.tab").write_text("mine", encoding="utf-8")
    with pytest.raises(FluidTableError, match="already exists"):
        md.make_tab(str(mfl), None, engine=lambda request: {"ok": True, "errors": []})
    assert (mfl.parent / "gas_water.tab").read_text(encoding="utf-8") == "mine"


def test_an_engine_failure_leaves_no_table_and_says_why(tmp_path: Path) -> None:
    mfl = _workspace(tmp_path)

    def engine(request: dict[str, Any]) -> dict[str, Any]:
        Path(request["tab_path"]).write_text("", encoding="utf-8")
        return {"ok": False, "errors": [20575]}

    with pytest.raises(FluidTableError, match="20575"):
        md.make_tab(str(mfl), None, engine=engine, error_file=FIX / "mini.err")
    assert sorted(p.name for p in mfl.parent.iterdir()) == ["gas_water.mfl"]


def test_the_target_name_must_be_a_plain_tab_file_name(tmp_path: Path) -> None:
    mfl = _workspace(tmp_path)
    for bad in ("../x.tab", "sub/x.tab", "x.txt", ""):
        with pytest.raises(FluidTableError):
            md.make_tab(str(mfl), bad, engine=lambda request: {"ok": True, "errors": []})


def test_an_engine_warning_is_reported_and_the_table_is_kept(tmp_path: Path) -> None:
    """Multiflash numbers its warnings below zero; a real two-phase fluid ends with -20573."""
    mfl = _workspace(tmp_path)

    def engine(request: dict[str, Any]) -> dict[str, Any]:
        table = (FIX / "handwritten_3x3.tab").read_text(encoding="utf-8")
        Path(request["tab_path"]).write_text(table.replace("LABEL = probe", f"LABEL = {request['title']}", 1), encoding="utf-8")
        return {"ok": False, "errors": [-20573], "load_errors": [-20573]}

    result = md.make_tab(str(mfl), "case.tab", engine=engine, error_file=FIX / "mini.err")
    assert (mfl.parent / "case.tab").is_file()
    assert result["engine_warnings"] == ["Test record four title. Test record four detail."]


def test_an_error_next_to_a_warning_still_fails(tmp_path: Path) -> None:
    mfl = _workspace(tmp_path)
    with pytest.raises(FluidTableError, match="error 20575.*Test record two"):
        md.make_tab(str(mfl), None, engine=lambda request: {"ok": False, "errors": [-20573, 20575]}, error_file=FIX / "mini.err")
    assert sorted(p.name for p in mfl.parent.iterdir()) == ["gas_water.mfl"]


def test_a_failure_without_any_code_still_fails(tmp_path: Path) -> None:
    mfl = _workspace(tmp_path)
    with pytest.raises(FluidTableError, match="could not make"):
        md.make_tab(str(mfl), None, engine=lambda request: {"ok": False, "errors": []})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("{base}", False),
        ("{hawater}", True),
        ("{lower}", True),
        ("{title}", False),
        ("{comment}", False),
    ],
)
def test_the_high_accuracy_water_model_is_on_only_when_the_table_command_says_so(
    tmp_path: Path, text: str, expected: bool
) -> None:
    base = _text("gas_water.mfl")
    import re

    command = re.search(r'table\s+olga\s+"[^"]*"', base, re.IGNORECASE)
    assert command is not None
    head = command.group(0)
    variants = {
        "base": base,
        "hawater": base.replace(head, f"{head} info HAWATER"),
        "lower": base.replace(head, f"{head} hawater"),
        "title": base.replace(head, head.replace('"', '"hawater_', 1)),
        "comment": f"# HAWATER #\n{base}",
    }
    mfl = tmp_path / "f.mfl"
    mfl.write_text(variants[text.strip("{}")], encoding="utf-8")
    seen: dict[str, Any] = {}

    def engine(request: dict[str, Any]) -> dict[str, Any]:
        seen.update(request)
        return {"ok": False, "errors": [20575]}

    with pytest.raises(FluidTableError):
        md.make_tab(str(mfl), None, engine=engine)
    assert seen["ha_water"] is expected


def test_an_mfl_without_a_table_command_keeps_the_water_model_off() -> None:
    assert md.read_table_request(_text("no_table.mfl"))["ha_water"] is False


def test_the_engine_child_keeps_the_water_model_off_by_default() -> None:
    from olga_companion import multiflash_child

    source = Path(multiflash_child.__file__).read_text(encoding="utf-8")
    assert 'request.get("ha_water", False)' in source


@pytest.mark.parametrize(
    "command",
    [
        'table olga "a.tab" HAWATER title "X" temperatures C 10 20; pressures bar 1 2;\nset physprops 2VCS;\n',
        "table olga a.tab title X temperatures 280 300 ; pressures 100000 200000 ; ;\n",
    ],
)
def test_a_table_command_the_app_cannot_read_is_refused_not_replaced_by_the_default_grid(command: str) -> None:
    with pytest.raises(FluidTableError, match="table olga"):
        md.read_table_request(_text("no_table.mfl") + command)


def test_an_unknown_warning_code_is_called_a_warning(tmp_path: Path) -> None:
    assert md.explain_error(-99999, FIX / "mini.err") == "Multiflash warning -99999."
    assert md.explain_error(-99999, tmp_path / "absent.err") == "Multiflash warning -99999."
