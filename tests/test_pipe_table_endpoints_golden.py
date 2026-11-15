"""Golden equivalence for ``rows_from_endpoints``: its (rows, issues, summary) stay byte-identical.

The fixture ``fixtures/pipe_tables/endpoints_golden.json`` holds the output of the function
before it was split into private helpers, for two kinds of input:

* ``literal`` cases: rows recorded from the existing endpoint tests, stored in the fixture.
* ``generated`` cases: seeded synthetic networks built by ``build_generated`` below, so the
  fixture stays small. Only ``random.Random.random`` is used, which is reproducible.

Each case also records the module budgets it ran under (for example a tiny sample budget),
so every skip, cap and refusal path is pinned. Expected output is the exact JSON text, or a
SHA-256 of it when the text is large. Regenerate the fixture only for a deliberate behaviour
change: ``python tests/test_pipe_table_endpoints_golden.py --write``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import random
import sys
from pathlib import Path

import pytest

from olga_companion import pipe_table_endpoints as endpoints

FIXTURE = Path(__file__).parent / "fixtures" / "pipe_tables" / "endpoints_golden.json"
_TEXT_LIMIT = 20_000


class _Gen:
    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def u(self, low: float, high: float) -> float:
        return low + (high - low) * self._rng.random()

    def below(self, count: int) -> int:
        return min(count - 1, int(self._rng.random() * count))

    def chance(self, probability: float) -> bool:
        return self._rng.random() < probability


def _row(start, end, name, **extra):
    row = {
        "pipe": name,
        "x_start_m": round(start[0], 6), "y_start_m": round(start[1], 6), "z_start_m": round(start[2], 6),
        "x_m": round(end[0], 6), "y_m": round(end[1], 6), "z_m": round(end[2], 6),
        "inner_diameter_m": 0.05,
    }
    row.update(extra)
    return row


def _direction(gen: _Gen) -> tuple[float, float, float]:
    vector = (gen.u(-1, 1), gen.u(-1, 1), gen.u(-1, 1))
    norm = math.sqrt(sum(part * part for part in vector)) or 1.0
    return (vector[0] / norm, vector[1] / norm, vector[2] / norm)


def _tree(gen: _Gen, count: int, flip: float, jitter: float, low: float = 2.0, high: float = 40.0):
    root = (gen.u(-50, 50), gen.u(-50, 50), gen.u(-50, 50))
    open_nodes: list[list] = []  # [point, children]
    rows = []
    for number in range(count):
        if number == 0:
            parent = root
        else:
            slot = open_nodes[gen.below(len(open_nodes))]
            parent = slot[0]
            slot[1] += 1
            if slot[1] >= 3:
                open_nodes.remove(slot)
        vector = _direction(gen)
        length = gen.u(low, high)
        child = (parent[0] + vector[0] * length, parent[1] + vector[1] * length,
                 parent[2] + vector[2] * length)
        open_nodes.append([child, 0])
        start = tuple(part + gen.u(-jitter, jitter) for part in parent) if jitter else parent
        a, b = (child, start) if gen.chance(flip) else (start, child)
        rows.append(_row(a, b, f"T{number}"))
    return rows


def _chain(gen: _Gen, count: int):
    point = (0.0, 0.0, 0.0)
    rows = []
    for number in range(count):
        vector = _direction(gen)
        length = gen.u(0.5, 6.0)
        nxt = (point[0] + vector[0] * length, point[1] + vector[1] * length,
               point[2] + vector[2] * length)
        rows.append(_row(point, nxt, f"C{number}"))
        point = nxt
    return rows


def _tees(gen: _Gen, trunks: int, valves: bool, low: float, high: float, offset: float,
          close: float = 0.3):
    rows = []
    for number in range(trunks):
        origin = (number * 150.0, gen.u(-5, 5), gen.u(-5, 5))
        vector = _direction(gen)
        length = gen.u(low, high)
        end = (origin[0] + vector[0] * length, origin[1] + vector[1] * length,
               origin[2] + vector[2] * length)
        extra = {}
        if valves and gen.chance(0.7):
            position = (0.5, 0.25, 0.9, None, "0.4", "bad", "")[gen.below(7)]
            extra = {"valve": f"V{number}", "valve_schedule": "0:1", "valve_diameter_m": 0.04}
            if position is not None:
                extra["valve_position"] = position
        rows.append(_row(origin, end, f"R{number}", **extra))
        slots = 1 + gen.below(3)
        fractions = [0.15 + 0.7 * (slot + gen.u(0.2, 0.8)) / slots for slot in range(slots)]
        if gen.chance(close):
            fractions.append(fractions[0] + gen.u(0.0, 0.0004) / max(length, 1.0))
        if valves and gen.chance(0.3):
            fractions.append(0.5)
        for branch, frac in enumerate(fractions):
            tap = tuple(origin[axis] + (end[axis] - origin[axis]) * frac for axis in range(3))
            tap = tuple(part + gen.u(-offset, offset) for part in tap)
            vector = _direction(gen)
            far = gen.u(2.5, 20.0)
            tip = (tap[0] + vector[0] * far, tap[1] + vector[1] * far, tap[2] + vector[2] * far)
            rows.append(_row(tap, tip, f"B{number}_{branch}"))
    return rows


def _dirty(gen: _Gen, kind: int):
    rows = _tree(gen, 40, 0.0, 0.0)
    first = rows[0]
    if kind == 0:  # parallel pipe on the same two ends
        rows.append(_row((first["x_start_m"], first["y_start_m"], first["z_start_m"]),
                         (first["x_m"], first["y_m"], first["z_m"]), "DUP"))
    elif kind == 1:  # self loop
        rows.append(_row((900, 0, 0), (900.0004, 0, 0), "LOOP"))
    elif kind == 2:  # ring
        ring = [(800, 0, 0), (810, 0, 0), (810, 10, 0), (800, 10, 0)]
        for index in range(4):
            rows.append(_row(ring[index], ring[(index + 1) % 4], f"RING{index}"))
    elif kind == 3:  # near miss
        rows.append(_row((first["x_m"] + gen.u(0.002, 0.09), first["y_m"], first["z_m"]),
                         (first["x_m"] + 30, first["y_m"], first["z_m"]), "NEAR"))
    elif kind == 4:  # within 1 mm yet separate clusters (ambiguous)
        rows.append(_row((first["x_m"] + 0.0006, first["y_m"] + 0.0006, first["z_m"] + 0.0006),
                         (first["x_m"] + 30, first["y_m"], first["z_m"]), "AMB1"))
        rows.append(_row((first["x_m"] - 0.0006, first["y_m"] - 0.0006, first["z_m"] - 0.0006),
                         (first["x_m"] - 30, first["y_m"], first["z_m"]), "AMB2"))
    elif kind == 5:  # star of eight
        hub = (700.0, 0.0, 0.0)
        for index in range(8):
            rows.append(_row(hub, (700.0 + 10.0 * (index + 1), 5.0 * index, 0.0), f"S{index}"))
    elif kind == 6:  # two in, no out
        rows.append(_row((600, 0, 0), (610, 0, 0), "IN1"))
        rows.append(_row((620, 0, 0), (610, 0, 0), "IN2"))
    elif kind == 7:  # node rows and a pipe with a stated mismatching length
        rows.append({"node": "PASS_1", "node_kind": "source", "pressure_bar": 5.0})
        rows.append(_row((500, 0, 0), (510, 0, 0), "LEN", length_m=25.0))
    elif kind == 8:  # stated elevation mismatch and non-finite coordinates
        rows.append(_row((500, 0, 0), (510, 3, 0), "RISE", elevation_m=9.0))
        rows.append(_row((520, 0, 0), (float("nan"), 0, 0), "NAN"))
    elif kind == 9:  # missing coordinates, text lengths, stray columns
        broken = _row((530, 0, 0), (540, 0, 0), "MISS")
        broken.pop("y_start_m")
        rows.append(broken)
        rows.append(_row((550, 0, 0), (560, 0, 0), "TXT", length_m="ten", flowpath="FP_X"))
        rows.append(_row((570, 0, 0), (580, 0, 0), "TXT2", elevation_m="up", from_node="A"))
        gone = _row((590, 0, 0), (600, 0, 0), "NOEND")
        gone.pop("z_m")
        rows.append(gone)
    return rows


# What the first pass of the seeded tee networks needs: sample count, projection count,
# and (long segments x unique endpoints), measured once on the original function.
_SAMPLE_EDGE = {51: 1199, 52: 989, 53: 1099}
_PROJECTION_EDGE = {51: 122, 52: 96, 53: 98}
_EXACT_EDGE = {54: 216, 55: 216}


def build_generated(name: str, seed: int):
    """Rows, keyword arguments and module budgets of one seeded network."""
    gen = _Gen(seed)
    kwargs: dict[str, object] = {"vertical_axis": "y" if seed % 2 else "z"}
    constants: dict[str, object] = {}
    if name == "tree-clean":
        rows = _tree(gen, 150, 0.0, 0.0)
    elif name == "tree-jitter":
        rows = _tree(gen, 120, 0.0, 0.0004)
    elif name == "tree-coarse-jitter":
        rows = _tree(gen, 80, 0.0, 0.02)
    elif name == "tree-flipped":
        rows = _tree(gen, 100, 0.1, 0.0)
    elif name == "tree-big":
        rows = _tree(gen, 900, 0.0, 0.0, 0.2, 12.0)
        kwargs["roughness_m"] = 4.5e-05
    elif name == "tree-brute":
        rows = _tree(gen, 60, 0.05, 0.0006, 0.5, 6.0)
        kwargs["_brute"] = True
    elif name == "tree-lines":
        rows = _tree(gen, 70, 0.0, 0.0)
        kwargs["lines"] = [index * 3 + 2 for index in range(len(rows))]
    elif name == "chain":
        rows = _chain(gen, 260)
    elif name == "tee":
        rows = _tees(gen, 25, False, 3.0, 40.0, 0.0002)
    elif name == "tee-valves":
        rows = _tees(gen, 25, True, 3.0, 40.0, 0.0)
    elif name == "tee-short":
        rows = _tees(gen, 20, True, 1.0, 1.9, 0.0002)
    elif name == "tee-offset":
        rows = _tees(gen, 20, False, 5.0, 30.0, 0.004, 0.0)
    elif name == "tee-long":
        rows = _tees(gen, 3, False, 8001.0, 9000.0, 0.0005)
        kwargs["roughness_m"] = 1e-05
    elif name == "tee-long-valves":
        rows = _tees(gen, 3, True, 8001.0, 9000.0, 0.0)
    elif name == "tee-sample-budget":
        rows = _tees(gen, 12, False, 3.0, 30.0, 0.0, 0.0)
        constants["_SPLIT_MAX_TOTAL_SAMPLES"] = 400 + seed
    elif name == "tee-sample-budget-tight":
        rows = _tees(gen, 12, False, 3.0, 30.0, 0.0)
        constants["_SPLIT_MAX_TOTAL_SAMPLES"] = 10
    elif name == "tee-projection-budget":
        rows = _tees(gen, 12, False, 3.0, 30.0, 0.0, 0.0)
        constants["_SPLIT_MAX_PROJECTIONS"] = 20 + seed
    elif name == "tee-exact-budget":
        rows = _tees(gen, 6, False, 8001.0, 9000.0, 0.0, 0.0)
        constants["_SPLIT_MAX_EXACT"] = 5
    elif name.startswith("edge-"):
        # Budgets set to exactly what the first pass needs (kept) or one less
        # (tripped): `>` versus `>=` shows up as a different result.
        _, which, side = name.split("-")
        long_rows = seed in _EXACT_EDGE
        rows = _tees(gen, 6 if long_rows else 12, False, 8001.0 if long_rows else 3.0,
                     9000.0 if long_rows else 30.0, 0.0, 0.0)
        need = {"samples": _SAMPLE_EDGE, "proj": _PROJECTION_EDGE, "exact": _EXACT_EDGE}[which][seed]
        constants[{"samples": "_SPLIT_MAX_TOTAL_SAMPLES", "proj": "_SPLIT_MAX_PROJECTIONS",
                   "exact": "_SPLIT_MAX_EXACT"}[which]] = need if side == "eq" else need - 1
    elif name == "tee-depth":
        rows = _tees(gen, 10, False, 3.0, 30.0, 0.0)
        constants["_MAX_SPLIT_DEPTH"] = 0
    elif name == "tee-brute":
        rows = _tees(gen, 8, True, 3.0, 30.0, 0.0002)
        kwargs["_brute"] = True
    elif name == "tee-ring-scan":
        rows = _tees(gen, 14, False, 3.0, 30.0, 0.0002)
        constants["_SCAN_CUTOFF"] = 2
    elif name.startswith("dirty-"):
        rows = _dirty(gen, int(name.split("-")[1]))
    else:
        raise KeyError(name)
    return rows, kwargs, constants


_GENERATED = (
    ("tree-clean", (1, 2, 3)),
    ("tree-jitter", (4, 5)),
    ("tree-coarse-jitter", (6, 7)),
    ("tree-flipped", (8, 9)),
    ("tree-big", (10, 11)),
    ("tree-brute", (12, 13)),
    ("tree-lines", (14, 15)),
    ("chain", (16, 17)),
    ("tee", (18, 19, 20)),
    ("tee-valves", (21, 22, 23, 24)),
    ("tee-short", (25, 26)),
    ("tee-offset", (27, 28)),
    ("tee-long", (29, 30)),
    ("tee-long-valves", (31, 32)),
    ("tee-sample-budget", (33, 34, 35)),
    ("tee-sample-budget-tight", (36,)),
    ("tee-projection-budget", (37, 38)),
    ("tee-exact-budget", (39, 40)),
    ("tee-depth", (41, 42)),
    ("edge-samples-eq", (51, 52, 53)),
    ("edge-samples-minus", (51, 52, 53)),
    ("edge-proj-eq", (51, 52, 53)),
    ("edge-proj-minus", (51, 52, 53)),
    ("edge-exact-eq", (54, 55)),
    ("edge-exact-minus", (54, 55)),
    ("tee-brute", (43, 44)),
    ("tee-ring-scan", (45, 46)),
) + tuple((f"dirty-{kind}", (100 + kind, 200 + kind)) for kind in range(10))


def generated_cases() -> list[dict[str, object]]:
    return [
        {"id": f"{name}/{seed}", "kind": "generated", "name": name, "seed": seed}
        for name, seeds in _GENERATED for seed in seeds
    ]


def serialise(result) -> str:
    out, issues, summary = result
    return json.dumps(
        {"rows": out, "issues": [dataclasses.asdict(issue) for issue in issues], "summary": summary}
    )


def _expected(text: str) -> dict[str, object]:
    record: dict[str, object] = {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "bytes": len(text),
    }
    if len(text) <= _TEXT_LIMIT:
        record["text"] = text
    return record


def run_case(case: dict[str, object], monkeypatch) -> str:
    if case["kind"] == "generated":
        rows, kwargs, constants = build_generated(str(case["name"]), int(case["seed"]))
    else:
        rows = case["rows"]
        kwargs = dict(case["kwargs"])
        constants = dict(case["constants"])
    for name, value in constants.items():
        monkeypatch.setattr(endpoints, name, value)
    return serialise(endpoints.rows_from_endpoints(rows, **kwargs))


def _load() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


_CASES = _load() if FIXTURE.exists() else []


@pytest.mark.parametrize("case", _CASES, ids=[str(case["id"]) for case in _CASES])
def test_rows_from_endpoints_output_is_byte_identical(case, monkeypatch) -> None:
    text = run_case(case, monkeypatch)
    expected = case["expected"]
    assert len(text) == expected["bytes"]
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == expected["sha256"]
    if "text" in expected:
        assert text == expected["text"]


def test_golden_fixture_covers_every_path() -> None:
    assert len(_CASES) >= 100
    outcomes = dict.fromkeys(
        ("clean", "refused", "skipped_clean", "split", "ends_capped", "merge_capped"), 0)
    codes: set[str] = set()
    for case in _CASES:
        with pytest.MonkeyPatch.context() as patch:
            data = json.loads(run_case(case, patch))
        summary = data["summary"]
        codes.update(issue["code"] for issue in data["issues"])
        outcomes["refused" if data["issues"] else "clean"] += 1
        outcomes["skipped_clean"] += bool(summary.get("split_skipped") and not data["issues"])
        outcomes["split"] += bool(summary.get("split_rows"))
        outcomes["ends_capped"] += summary.get("ends_total", 0) > len(summary.get("ends", ()))
        outcomes["merge_capped"] += summary.get("merged_rows_total", 0) > len(summary.get("merged_rows", ()))
    assert all(outcomes.values()), outcomes
    assert codes == set(endpoints.ENDPOINT_ISSUE_CODES)


def _write(harvest_path: str) -> None:
    class _Patch:
        @staticmethod
        def setattr(module, name, value):
            setattr(module, name, value)

    cases: list[dict[str, object]] = []
    harvested = json.loads(Path(harvest_path).read_text(encoding="utf-8"))
    for index, item in enumerate(harvested):
        if len(json.dumps(item["rows"])) > 20_000:
            continue
        cases.append({
            "id": f"literal/{index:03d}", "kind": "literal", "rows": item["rows"],
            "kwargs": item["kwargs"], "constants": item["constants"],
        })
    cases.extend(generated_cases())
    originals = {name: getattr(endpoints, name) for name in dir(endpoints) if name.startswith("_")}
    for case in cases:
        try:
            text = run_case(case, _Patch)
        finally:
            for name, value in originals.items():
                setattr(endpoints, name, value)
        case["expected"] = _expected(text)
    FIXTURE.write_text(json.dumps({"cases": cases}, separators=(",", ":")) + "\n", encoding="utf-8")
    print("wrote", len(cases), "cases", FIXTURE.stat().st_size, "bytes")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--write":
        _write(sys.argv[2])
    else:
        raise SystemExit("usage: --write <harvest.json>")
