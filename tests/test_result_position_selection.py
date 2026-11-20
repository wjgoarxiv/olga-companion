"""A trend position is chosen exactly, and branch selectors from the index resolve.

On 2026-11-10 a five-metre air-water run recorded POS_MAIN_1 (first section) and POS_MAIN
(last section). Asking for POS_MAIN returned POS_MAIN_1 because the parser took the first
substring match, and the index label "BRANCH - MAIN" for LIQC was refused against the
parser's "MAIN", so the outlet pressure and the pressure drop were never read.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from olga_companion import results as results_module
from olga_companion.results import _positions_equivalent

_spec = importlib.util.spec_from_file_location(
    "result_parser_under_test",
    Path(__file__).parents[1] / "resources" / "olga-toolkit" / "scripts" / "result_parser.py",
)
parser = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_keep_bytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    _spec.loader.exec_module(parser)
finally:
    sys.dont_write_bytecode = _keep_bytecode

CATALOG = {
    1: "HOL 'POSITION:' 'POS_MAIN_1' '(-)' 'Holdup'",
    3: "PT 'POSITION:' 'POS_MAIN_1' '(PA)' 'Pressure'",
    4: "PT 'POSITION:' 'POS_MAIN' '(PA)' 'Pressure'",
}


def test_exact_position_wins_over_a_longer_name_that_contains_it() -> None:
    pt = {k: v for k, v in CATALOG.items() if v.startswith("PT ")}
    assert parser._select_position(pt, "POS_MAIN") == 4
    assert parser._select_position(pt, "pos_main_1") == 3


def test_a_position_that_names_nothing_is_refused_not_replaced() -> None:
    pt = {k: v for k, v in CATALOG.items() if v.startswith("PT ")}
    with pytest.raises(ValueError, match="POS_OTHER"):
        parser._select_position(pt, "POS_OTHER")


def test_a_longer_position_is_never_taken_for_a_shorter_one() -> None:
    only_first = {3: CATALOG[3]}
    with pytest.raises(ValueError, match="POS_MAIN_1"):
        parser._select_position(only_first, "POS_MAIN")


def test_a_variable_whose_name_contains_another_is_not_picked() -> None:
    # pyfas filter_trends is a substring test, so asking for HOL also lists HOLHL.
    listed = {
        7: "HOLHL 'POSITION:' 'POS_MAIN' '(-)' 'Oil holdup'",
        8: "HOL 'POSITION:' 'POS_MAIN' '(-)' 'Holdup'",
    }
    assert parser._only_variable(listed, "HOL") == {8: listed[8]}
    assert parser._only_variable(listed, "hol") == {8: listed[8]}


@pytest.mark.parametrize("selector", ["BRANCH - MAIN", "Br - MAIN", "branch - main"])
def test_branch_selectors_match_the_parser_branch_name(selector: str) -> None:
    assert _positions_equivalent(selector, "MAIN") is True
    assert _positions_equivalent(selector, "OTHER") is False


@pytest.mark.parametrize("selector", ["BRANCH - -X", "SECTION - Br - -X - PIPE - 1"])
def test_an_extracted_branch_name_is_checked_like_a_raw_one(
    selector: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(results_module, "resolve_result", lambda _path: tmp_path / "case.tpl")
    with pytest.raises(results_module.OlgaInputError, match="Invalid result position"):
        results_module.variable_series("case.tpl", "PT", selector)


def test_variable_series_sends_the_bare_branch_name_to_the_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "case.tpl"
    source.write_bytes(b"branch position source")
    seen: list[list[str]] = []

    class Command:
        exit_code = 0
        stdout = '{"time":[0,1],"values":[0.003,0.004],"unit":"M3","time_unit":"s","position":"MAIN"}'

    def run_tool(_name: str, args: list[str], **_kwargs: object) -> Command:
        seen.append(args)
        return Command()

    monkeypatch.setattr(results_module, "resolve_result", lambda _path: source)
    monkeypatch.setattr(results_module, "run_tool", run_tool)

    result = results_module.variable_series(str(source), "LIQC", "BRANCH - MAIN")

    assert result["position"] == "MAIN"
    assert seen[0][seen[0].index("--position") + 1] == "MAIN"
