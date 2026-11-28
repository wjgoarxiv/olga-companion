"""A large .ppl opens in one read, not one read per variable.

pyfas.Ppl re-reads the whole file for every catalog line and every branch while it
initialises, then builds a DataFrame for each variable. A 1 MB result with a few thousand
variables took 35-70 s to load, three times over (variable list, branch list, timestep list),
and again for every profile. These tests count the mechanism (file opens, variables parsed,
modules imported), never the wall clock, and check the answers are the ones pyfas gives.
"""
from __future__ import annotations

import ast
import builtins
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "resources" / "olga-toolkit" / "scripts"
STEPS = [0.0, 900.5, 1800.0, 3600.25]


def _load(name: str, filename: str):
    # Never leave a __pycache__ in the bundled toolkit (test_packaging_config forbids it).
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
        sys.path.remove(str(SCRIPTS))
    return module


def _row(values: list[float]) -> str:
    return " ".join(f"{value:.16e}" for value in values) + " \n"


def _build(path: Path, branches: list[str], names: list[str]) -> list[tuple[str, str]]:
    """A profile file: every branch has every variable; the first name sits on the nodes
    (BOUNDARY, one value per node), the others between them (one value fewer)."""
    nodes = 5
    head = ["'OLGA 2022.1.0'\n", "PROFILE PLOT\n", "GEOMETRY ' (M)  '\n"]
    for number, branch in enumerate(branches):
        head += ["BRANCH\n", f"'{branch}'\n", f"{nodes}\n"]
        head += [_row([100.0 * i + number for i in range(nodes)]), _row([float(i) for i in range(nodes)])]
    entries: list[tuple[str, str]] = []
    catalog: list[str] = []
    for branch in branches:
        for position, name in enumerate(names):
            kind = "'BOUNDARY:'" if position == 0 else "'SECTION:'"
            entries.append((name, branch))
            catalog.append(f"{name} {kind} 'BRANCH:' '{branch}' '(PA)' 'Description of {name}'\n")
    body = ["TIME SERIES  ' (S)  '\n"]
    for step, time in enumerate(STEPS):
        body.append(f"{time:.16e}\n")
        for index, (name, _branch) in enumerate(entries):
            width = nodes if name == names[0] else nodes - 1
            values = [0.5 + 0.01 * index + 0.1 * step + 0.001 * n for n in range(width)]
            if index == 13 and step == 2:
                values[1] = float("nan")  # undefined at that node and time
            if index == 13 and step == 3:
                values[0] = float("inf")
            body.append(_row(values))
    path.write_text("".join(head + ["CATALOG\n", f"{len(entries)}\n"] + catalog + body))
    return entries


class _OpenCounter:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
        self.count = 0
        real_open = builtins.open
        target = str(path)

        def counting_open(file, *args, **kwargs):
            if str(file) == target:
                self.count += 1
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", counting_open)


def _many(tmp_path: Path) -> tuple[Path, list[str], list[str]]:
    branches = [f"PIPE{n}" for n in range(30)]
    names = ["PT", "HOL", "TM", "ID"]
    path = tmp_path / "many.ppl"
    _build(path, branches, names)
    return path, branches, names


def test_a_result_is_opened_once_however_many_variables_it_has(tmp_path, monkeypatch) -> None:
    path, branches, _names = _many(tmp_path)  # 120 catalog lines on 30 branches
    parser_module = _load("result_parser_reads", "result_parser.py")
    reads = _OpenCounter(monkeypatch, path)

    parser = parser_module.ResultParser(str(path))
    parser.list_variables()
    parser.list_branches()
    parser.list_timesteps()
    parser.get_geometry(branches[0])

    assert reads.count <= 2


def test_one_profile_parses_one_variable_not_all_of_them(tmp_path, monkeypatch) -> None:
    path, branches, _names = _many(tmp_path)
    parser_module = _load("result_parser_one_variable", "result_parser.py")
    parser = parser_module.ResultParser(str(path))
    reads = _OpenCounter(monkeypatch, path)
    extracted: list[int] = []
    real_extract = parser_module._SinglePassPpl.extract

    def counting_extract(self, variable_idx):
        extracted.append(variable_idx)
        return real_extract(self, variable_idx)

    monkeypatch.setattr(parser_module._SinglePassPpl, "extract", counting_extract)

    profile = parser.get_profile("HOL", branches[3])

    assert len(extracted) == 1 and reads.count == 0
    assert profile["timestep"] == STEPS[-1] and len(profile["positions"]) == 4


def test_listing_and_profiling_a_ppl_never_imports_pyfas_or_pandas(tmp_path) -> None:
    path, branches, _names = _many(tmp_path)
    script = f"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rp", {str(SCRIPTS / "result_parser.py")!r})
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
parser = module.ResultParser({str(path)!r})
parser.list_variables(); parser.list_branches(); parser.list_timesteps()
parser.get_profile("PT", {branches[0]!r}, timestep=1000)
print(sorted(name for name in ("pyfas", "pandas", "numpy") if name in sys.modules))
"""
    done = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=120)

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


def _sorted_available(message: str) -> str:
    """pyfas lists branches in hash-seed order; ours are in file order (test_ppl_branch_order)."""
    head, sep, listed = message.partition("Available: ")
    if not sep:
        return message
    return head + sep + str(sorted(ast.literal_eval(listed)))


def _answers(parser, branches: list[str], keyed: list[str], names: list[str]) -> str:
    answers: dict[str, object] = {
        "variables": parser.list_variables(),
        "branches": parser.list_branches(),
        "timesteps": parser.list_timesteps(),
    }
    for branch in branches:
        answers[f"geometry {branch}"] = parser.get_geometry(branch)
    asked = [None, STEPS[0], STEPS[-1], 1000.0, 1e9, -5.0]
    for branch in [*keyed, "NO_SUCH_BRANCH"]:
        for name in [*names, "NO_SUCH_VARIABLE"]:
            for timestep in asked:
                try:
                    found: object = parser.get_profile(name, branch, timestep=timestep)
                    # pyfas's own route loses the unit of a respelled name (BR_2); ours is checked below.
                    found = {key: value for key, value in found.items() if key != "unit"}
                except ValueError as exc:
                    found = f"ValueError: {_sorted_available(str(exc))}"
                answers[f"{branch} {name} {timestep}"] = found
    return json.dumps(answers, indent=2, default=str)


def test_the_answers_are_the_ones_pyfas_gives(tmp_path) -> None:
    pytest.importorskip("pyfas")
    # pyfas keys BR-2 as BR_2 and 3RD as BRANCH_3RD; both spellings keep working. No name here is
    # part of another: there pyfas returns the other branch's values (see the tests below).
    branches = ["MAIN", "BR-2", "3RD", "RISER2"]
    names = ["PT", "HOL", "TM", "ID"]
    path = tmp_path / "case.ppl"
    _build(path, branches, names)
    parser_module = _load("result_parser_equal", "result_parser.py")

    fast = parser_module.ResultParser(str(path))
    assert isinstance(fast._reader, parser_module._SinglePassPpl)
    pyfas = parser_module.ResultParser(str(path))
    parser_module._check_pyfas()
    pyfas._reader = parser_module.Ppl(str(path))

    keyed = ["MAIN", "BR_2", "BRANCH_3RD", "RISER2"]
    assert _answers(fast, branches, keyed, names) == _answers(pyfas, branches, keyed, names)
    assert {fast.get_profile(name, branch)["unit"] for name in names for branch in keyed} == {"PA"}
    assert None in fast.get_profile("HOL", "RISER2", timestep=1800.0)["values"]  # NaN is null, in both
    assert None in fast.get_profile("HOL", "RISER2", timestep=3600.25)["values"]  # so is an infinity


def _exact(tmp_path: Path, branches: list[str]):
    path = tmp_path / "names.ppl"
    entries = _build(path, branches, ["PT", "HOL", "TM", "ID"])
    parser = _load("result_parser_names", "result_parser.py").ResultParser(str(path))
    values = {(name, branch): 0.5 + 0.01 * index for index, (name, branch) in enumerate(entries)}
    return parser, values


@pytest.mark.parametrize("branches", [["LINE_3", "LINE_3-10", "LINE_31"], ["LINE_31", "LINE_3-10", "LINE_3"]])
def test_a_branch_whose_name_is_part_of_another_gets_its_own_values(tmp_path, branches) -> None:
    parser, first = _exact(tmp_path, branches)
    for number, branch in enumerate(branches):
        for name in ("PT", "HOL"):
            profile = parser.get_profile(name, branch, timestep=STEPS[0])
            assert profile["values"][0] == pytest.approx(first[(name, branch)])
            assert profile["positions"][0] == pytest.approx(number + (0 if name == "PT" else 50))


def test_every_listed_branch_name_can_be_asked_for(tmp_path) -> None:
    parser, _ = _exact(tmp_path, ["BR-2", "BR_2", "3RD"])
    for branch in parser.list_branches():
        assert parser.get_profile("PT", branch)["branch"] == branch


def test_a_respelled_name_that_fits_two_branches_is_refused(tmp_path) -> None:
    parser, _ = _exact(tmp_path, ["BR-2", "BR.2"])
    with pytest.raises(ValueError, match="BR-2.*BR.2"):
        parser.get_profile("PT", "BR_2")


def test_a_file_the_single_pass_reader_cannot_take_goes_to_pyfas(tmp_path) -> None:
    pytest.importorskip("pyfas")
    parser_module = _load("result_parser_fallback", "result_parser.py")
    path = tmp_path / "empty.ppl"
    path.write_bytes(b"")

    with pytest.raises(Exception) as single_pass:
        parser_module._SinglePassPpl(str(path))
    assert isinstance(single_pass.value, parser_module._PplUnsupported)
    with pytest.raises(Exception) as through_parser:
        parser_module.ResultParser(str(path))
    assert not isinstance(through_parser.value, parser_module._PplUnsupported)  # pyfas's own error


def test_the_profile_plotter_parses_only_what_it_is_asked_for(tmp_path, monkeypatch, capsys) -> None:
    pytest.importorskip("pyfas")
    path, branches, _names = _many(tmp_path)
    plotter_module = _load("fast_ppl_plotter_reads", "fast_ppl_plotter.py")
    reads = _OpenCounter(monkeypatch, path)

    plotter = plotter_module.FastPPLPlotter(str(path))
    positions, values = plotter.get_profile("HOL", branches[4], timestep=1000.0)
    every_step = plotter.get_all_profiles("TM", branches[5])
    capsys.readouterr()

    assert reads.count <= 2
    assert len(every_step) == len(STEPS)

    plotter_module._SinglePassPpl = None  # the pyfas route, for the reference answer
    reference = plotter_module.FastPPLPlotter(str(path))
    ref_positions, ref_values = reference.get_profile("HOL", branches[4], timestep=1000.0)
    capsys.readouterr()
    assert list(positions) == list(ref_positions) and list(values) == list(ref_values)
    assert {t: list(v) for t, v in every_step.items()} == {
        t: list(v) for t, v in reference.get_all_profiles("TM", branches[5]).items()
    }
