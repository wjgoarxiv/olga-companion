"""The synthetic pipe tables are generated, deterministic and the size of a real job."""

from __future__ import annotations

import csv
import importlib.util
from collections import Counter
from pathlib import Path

import pytest

HERE = Path(__file__).parent / "fixtures" / "pipe_tables"


def _generator():
    spec = importlib.util.spec_from_file_location("make_synthetic_network", HERE / "make_synthetic_network.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _rows(name: str) -> list[dict[str, str]]:
    with (HERE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_committed_tables_equal_the_generator_output() -> None:
    module = _generator()
    assert (HERE / "synthetic_network.csv").read_text(encoding="utf-8") == module.large_network().text()
    assert (HERE / "small_branch.csv").read_text(encoding="utf-8") == module.small_branch().text()
    assert module.large_network().text() == module.large_network().text()


def test_the_generator_writes_the_template_doc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _generator()
    target = tmp_path / "pipe_table_template.csv"
    monkeypatch.setattr(module, "TEMPLATE_CSV", target, raising=False)
    module.main()
    assert target.read_text(encoding="utf-8") == module.small_branch().text()


def test_large_table_has_the_size_and_shape_of_a_real_job() -> None:
    rows = _rows("synthetic_network.csv")
    pipes = [row for row in rows if row["pipe"]]
    boundaries = {row["node"]: row["node_kind"] for row in rows if row["node"]}
    ends = {row["flowpath"]: (row["from_node"], row["to_node"]) for row in pipes}
    incoming, outgoing = Counter(), Counter()
    for start, end in ends.values():
        outgoing[start] += 1
        incoming[end] += 1
    junctions = (set(incoming) | set(outgoing)) - set(boundaries)
    degrees = Counter((incoming[name], outgoing[name]) for name in junctions)
    valves = [row for row in pipes if row["valve"]]

    assert len(ends) >= 300
    assert len(junctions) >= 120
    assert len(valves) >= 34 and all(row["valve_schedule"] for row in valves)
    assert degrees[(1, 1)] >= 1
    assert all(min(shape) == 1 and 2 <= sum(shape) <= 7 for shape in degrees)
    assert len(junctions) + len(boundaries) <= 256
    for name, kind in boundaries.items():
        assert (incoming[name], outgoing[name]) == ((0, 1) if kind == "source" else (1, 0))
    for row in pipes:
        assert abs(float(row["elevation_m"])) <= float(row["length_m"])
