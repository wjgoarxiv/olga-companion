"""Endpoints pre-pass: a table of per-pipe start/end x/y/z becomes flowpath rows.

All fixtures are synthetic and built inside the tests. No customer file is read.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from olga_companion.pipe_table import PipeTable
from olga_companion.pipe_table_endpoints import rows_from_endpoints
from olga_companion.pipe_table_import import ImportOptions, build_case_spec

OPTIONS = ImportOptions(
    pvt_reference="fluid.tab", fluid_label="TEST_FLUID", thermal={"model": "adiabatic"},
    end_time_s=600.0, max_section_m=1.0,
)

DIAM = 0.05
ROUGH = 5e-05


def _pipe(start, end, *, diameter=DIAM, roughness=ROUGH, pipe="P", extra=None):
    row = {
        "pipe": pipe,
        "x_start_m": float(start[0]), "y_start_m": float(start[1]), "z_start_m": float(start[2]),
        "x_m": float(end[0]), "y_m": float(end[1]), "z_m": float(end[2]),
        "inner_diameter_m": float(diameter),
    }
    if roughness is not None:
        row["roughness_m"] = float(roughness)
    if extra:
        row.update(extra)
    return row


def _spec(rows, node_rows):
    table = PipeTable(
        rows=tuple(rows) + tuple(node_rows), issues=(), header_row=1,
        ignored_columns=(), lines=tuple(range(1, len(rows) + len(node_rows) + 1)),
    )
    return build_case_spec(table, OPTIONS)


def _digest(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def test_vertical_axis_is_required() -> None:
    rows = [_pipe((0, 0, 0), (1, 0, 0))]
    with pytest.raises(ValueError, match="vertical_axis"):
        rows_from_endpoints(rows, vertical_axis="x")  # type: ignore[arg-type]


def test_chain_of_three_pipes_becomes_one_flowpath() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10, 0, 0), (20, 0, 0), pipe="P2"),
        _pipe((20, 0, 0), (30, 0, 0), pipe="P3"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    assert len(out) == 3
    assert len({row["flowpath"] for row in out}) == 1
    assert summary["flowpaths"] == 1
    assert out[0]["from_node"] == out[1]["from_node"] == out[2]["from_node"]
    assert out[0]["to_node"] == out[1]["to_node"] == out[2]["to_node"]


def test_junction_with_one_side_single_is_kept() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="TRUNK"),
        _pipe((10, 0, 0), (10, 5, 0), pipe="A"),
        _pipe((10, 0, 0), (10, -5, 0), pipe="B"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    assert summary["junctions"] == 1
    assert summary["flowpaths"] == 3
    ends = {entry["name"] for entry in summary["ends"]}
    assert len(ends) == 3


def test_degree_one_ends_are_listed_with_coordinates() -> None:
    rows = [_pipe((0, 0, 0), (5, 0, 0), pipe="P1")]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    assert len(summary["ends"]) == 2
    by_name = {entry["name"]: entry for entry in summary["ends"]}
    assert by_name[out[0]["from_node"]]["x_m"] == pytest.approx(0.0)
    assert by_name[out[0]["to_node"]]["x_m"] == pytest.approx(5.0)


def test_endpoints_within_1mm_join() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10.0009, 0, 0), (20, 0, 0), pipe="P2"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    assert summary["flowpaths"] == 1


def test_chain_cannot_drift_across_two_steps() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10.0009, 0, 0), (20, 0, 0), pipe="P2"),
        _pipe((10.0018, 0, 0), (30, 0, 0), pipe="P3"),
    ]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    assert issues != ()
    assert any(issue.row == 3 for issue in issues)


def test_near_miss_between_1mm_and_01m_is_refused() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10.05, 0, 0), (20, 0, 0), pipe="P2"),
    ]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    assert any(issue.row == 2 for issue in issues)


def test_two_pipes_sharing_both_ends_are_refused() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((0, 0, 0), (10, 0, 0), pipe="P2"),
    ]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    assert any(issue.row in (1, 2) for issue in issues)
    assert [(issue.row, issue.field) for issue in issues] == [(2, "x_m")]


def test_cycle_is_refused() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10, 0, 0), (5, 8, 0), pipe="P2"),
        _pipe((5, 8, 0), (0, 0, 0), pipe="P3"),
    ]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    assert issues != ()
    assert [(issue.row, issue.field) for issue in issues] == [(3, "x_m")]


def test_stated_length_mismatch_is_refused() -> None:
    rows = [_pipe((0, 0, 0), (10, 0, 0), pipe="P1", extra={"length_m": 12.0})]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    assert any(issue.row == 1 and "length" in issue.field for issue in issues)


def test_stated_rise_mismatch_is_refused() -> None:
    rows = [_pipe((0, 0, 0), (10, 0, 4), pipe="P1", extra={"elevation_m": 0.0})]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="z")
    assert out == []
    assert any(issue.row == 1 for issue in issues)


def test_roughness_option_fills_a_missing_column() -> None:
    rows = [_pipe((0, 0, 0), (5, 0, 0), pipe="P1", roughness=None)]
    assert "roughness_m" not in rows[0]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y", roughness_m=ROUGH)
    assert issues == ()
    assert out[0]["roughness_m"] == pytest.approx(ROUGH)


def test_z_up_axes_are_reordered_to_y_up() -> None:
    rows = [_pipe((1, 2, 3), (4, 6, 8), pipe="P1")]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="z")
    assert issues == ()
    assert out[0]["x_m"] == pytest.approx(4.0)
    assert out[0]["y_m"] == pytest.approx(8.0)
    assert out[0]["z_m"] == pytest.approx(6.0)
    assert out[0]["x_start_m"] == pytest.approx(1.0)
    assert out[0]["y_start_m"] == pytest.approx(3.0)
    assert out[0]["z_start_m"] == pytest.approx(2.0)


def test_bad_junction_orientation_is_refused() -> None:
    # Two in and two out at one node: the existing rule needs one side single.
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="A"),
        _pipe((0, 5, 0), (10, 0, 0), pipe="B"),
        _pipe((10, 0, 0), (20, 0, 0), pipe="C"),
        _pipe((10, 0, 0), (20, 5, 0), pipe="D"),
    ]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    assert issues != ()
    assert sorted((issue.row, issue.field) for issue in issues) == [
        (1, "from_node"), (2, "from_node"), (3, "from_node"), (4, "from_node"),
    ]


def _int_pipe(start, end, *, pipe="P"):
    return {
        "pipe": pipe,
        "x_start_m": start[0], "y_start_m": start[1], "z_start_m": start[2],
        "x_m": end[0], "y_m": end[1], "z_m": end[2],
        "inner_diameter_m": 0.05, "roughness_m": ROUGH,
    }


def test_int_coordinates_are_accepted() -> None:
    rows = [_int_pipe((0, 0, 0), (10, 0, 0))]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    assert len(out) == 1
    assert out[0]["x_m"] == 10.0


def test_non_numeric_length_and_rise_are_refused() -> None:
    rows = [_pipe((0, 0, 0), (10, 0, 0), pipe="P1", extra={"length_m": "long"})]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    assert [(issue.row, issue.field) for issue in issues] == [(1, "length_m")]
    rows = [_pipe((0, 0, 0), (10, 0, 4), pipe="P1", extra={"elevation_m": "high"})]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="z")
    assert out == []
    assert [(issue.row, issue.field) for issue in issues] == [(1, "elevation_m")]


def test_short_pipe_is_not_a_near_miss() -> None:
    rows = [_pipe((0, 0, 0), (0.05, 0, 0), pipe="P1")]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    assert summary["flowpaths"] == 1
    assert len(out) == 1


def test_reversed_row_order_chains_topologically() -> None:
    rows = [
        _pipe((10, 0, 0), (20, 0, 0), pipe="P2"),
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    assert summary["flowpaths"] == 1
    assert [row["pipe"] for row in out] == ["P1", "P2"]


def test_exact_1mm_joins_and_exact_01m_is_refused() -> None:
    close = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10.001, 0, 0), (20.001, 0, 0), pipe="P2"),
    ]
    out, issues, summary = rows_from_endpoints(close, vertical_axis="y")
    assert issues == ()
    assert summary["flowpaths"] == 1
    far = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10.1, 0, 0), (20.1, 0, 0), pipe="P2"),
    ]
    out, issues, _summary = rows_from_endpoints(far, vertical_axis="y")
    assert out == []
    assert any(issue.row == 2 for issue in issues)
    assert [(issue.row, issue.field) for issue in issues] == [(1, "x_m"), (2, "x_start_m")]
    apart = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10.1001, 0, 0), (20.1001, 0, 0), pipe="P2"),
    ]
    out, issues, summary = rows_from_endpoints(apart, vertical_axis="y")
    assert issues == ()
    assert summary["flowpaths"] == 2


def test_stated_length_and_rise_within_tolerance_are_accepted() -> None:
    rows = [_pipe((0, 0, 0), (10, 0, 0), pipe="P1", extra={"length_m": 10.1})]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    assert len(out) == 1
    rows = [_pipe((0, 0, 0), (10, 0, 0), pipe="P1", extra={"length_m": 10.005})]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    rows = [_pipe((0, 0, 0), (10, 4, 0), pipe="P1", extra={"elevation_m": 4.03})]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    assert len(out) == 1


def test_y_axis_keeps_coordinates() -> None:
    rows = [_pipe((1, 2, 3), (4, 6, 8), pipe="P1")]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    assert (out[0]["x_m"], out[0]["y_m"], out[0]["z_m"]) == (4.0, 6.0, 8.0)
    assert (out[0]["x_start_m"], out[0]["y_start_m"], out[0]["z_start_m"]) == (1.0, 2.0, 3.0)


def test_custom_lines_name_the_rows() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10.05, 0, 0), (20, 0, 0), pipe="P2"),
    ]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y", lines=[101, 102])
    assert out == []
    assert {issue.row for issue in issues} == {101, 102}


def test_junction_with_more_than_7_pipes_is_refused() -> None:
    rows = [_pipe((0, 0, 0), (10, 0, 0), pipe="TRUNK")]
    for rank in range(7):
        rows.append(_pipe((10, 0, 0), (20, float(rank), 0), pipe=f"L{rank}"))
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    assert sorted((issue.row, issue.field) for issue in issues) == [
        (number, "from_node") for number in range(1, 9)
    ]


def test_missing_and_nan_coordinates_are_refused() -> None:
    row = _pipe((0, 0, 0), (5, 0, 0), pipe="P1")
    row["x_m"] = None
    out, issues, _summary = rows_from_endpoints([row], vertical_axis="y")
    assert out == []
    assert [(issue.row, issue.field) for issue in issues] == [(1, "x_m")]
    row = _pipe((0, 0, 0), (5, 0, 0), pipe="P1")
    row["y_start_m"] = float("nan")
    out, issues, _summary = rows_from_endpoints([row], vertical_axis="y")
    assert out == []
    assert [(issue.row, issue.field) for issue in issues] == [(1, "x_start_m")]


def test_node_row_passes_through() -> None:
    rows = [
        _pipe((0, 0, 0), (5, 0, 0), pipe="P1"),
        {"node": "SRC", "node_kind": "source", "pressure_pa": 500000.0,
         "temperature_c": 25.0, "gas_fraction": 1.0, "water_fraction": 0.0},
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == ()
    assert summary["pipes"] == 1
    assert any(row.get("node") == "SRC" for row in out)


def test_20k_coincident_pipes_are_refused_quickly() -> None:
    import time

    pipes = [
        _pipe((0, 0, 0), (10, 0, 0), pipe=f"P{number}")
        for number in range(20000)
    ]
    started = time.perf_counter()
    out, issues, _summary = rows_from_endpoints(pipes, vertical_axis="y")
    elapsed = time.perf_counter() - started
    assert out == []
    assert issues != ()
    assert elapsed < 20


def test_none_lines_carry_no_row_number() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10.05, 0, 0), (20, 0, 0), pipe="P2"),
    ]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y", lines=[None, None])
    assert out == []
    assert issues != ()
    assert {issue.row for issue in issues} == {None}


def test_20k_pipes_finish_quickly() -> None:
    import time

    pipes = [
        _pipe((10.0 * number, 0, 0), (10.0 * number + 10.0, 0, 0),
              pipe=f"P{number}", roughness=None)
        for number in range(20000)
    ]
    started = time.perf_counter()
    out, issues, summary = rows_from_endpoints(pipes, vertical_axis="y", roughness_m=ROUGH)
    elapsed = time.perf_counter() - started
    assert issues == ()
    assert summary["flowpaths"] == 1
    assert len(out) == 20000
    assert elapsed < 10


# A 12-pipe tree with 2 junctions, written Z-up (vertical on Z).
_ZUP = [
    ((0, 0, 0), (10, 0, 0), 0.05, "T1"),
    ((10, 0, 0), (20, 0, 0), 0.05, "T2"),
    ((20, 0, 0), (30, 0, 0), 0.05, "T3"),
    ((30, 0, 0), (35, 5, 0), 0.04, "A1"),
    ((35, 5, 0), (40, 5, 2), 0.04, "A2"),
    ((30, 0, 0), (30, -10, 5), 0.04, "B1"),
    ((30, 0, 0), (50, 0, 10), 0.04, "J1J2"),
    ((50, 0, 10), (55, 0, 12), 0.04, "C1"),
    ((55, 0, 12), (60, 5, 12), 0.04, "C2"),
    ((50, 0, 10), (50, 10, 15), 0.04, "D1"),
    ((50, 0, 10), (45, -5, 8), 0.04, "E1"),
    ((50, 0, 10), (60, -5, 10), 0.04, "F1"),
]


def _swap(point):
    x, y, z = point
    return (x, z, y)


def test_12_pipe_tree_with_2_junctions_matches_its_flowpath_twin() -> None:
    endpoint_rows = [
        _pipe(s, e, diameter=d, roughness=None, pipe=name) for s, e, d, name in _ZUP
    ]
    out, issues, summary = rows_from_endpoints(
        endpoint_rows, vertical_axis="z", roughness_m=ROUGH,
    )
    assert issues == (), [ (i.row, i.field, i.reason) for i in issues ]
    assert summary["junctions"] == 2
    assert len(summary["ends"]) == 7

    ends = {entry["name"]: entry for entry in summary["ends"]}
    source_name = next(
        name for name, entry in ends.items()
        if entry["x_m"] == pytest.approx(0.0) and entry["y_m"] == pytest.approx(0.0)
    )
    node_rows = []
    for name in ends:
        kind = "source" if name == source_name else "sink"
        node_rows.append({
            "node": name, "node_kind": kind,
            "pressure_pa": 500000.0 if kind == "source" else 100000.0,
            "temperature_c": 25.0,
            "gas_fraction": 1.0 if kind == "source" else 0.5,
            "water_fraction": 0.0,
        })
    endpoint_result = _spec(list(out), node_rows)
    assert endpoint_result.issues == (), [
        (i.row, i.field, i.reason) for i in endpoint_result.issues
    ]

    # Hand-written Y-up twin: the same network with Y vertical, grouped into
    # the same 8 flowpaths the pre-pass must produce.
    groups = [
        ("FP_TRUNK", ["T1", "T2", "T3"], "SRC", "J1"),
        ("FP_A", ["A1", "A2"], "J1", "OUT_A"),
        ("FP_B", ["B1"], "J1", "OUT_B"),
        ("FP_J", ["J1J2"], "J1", "J2"),
        ("FP_C", ["C1", "C2"], "J2", "OUT_C"),
        ("FP_D", ["D1"], "J2", "OUT_D"),
        ("FP_E", ["E1"], "J2", "OUT_E"),
        ("FP_F", ["F1"], "J2", "OUT_F"),
    ]
    twin_rows = []
    for flowpath, names, start, end in groups:
        for position, name in enumerate(names):
            (s, e), (diam, _label) = next(
                ((s, e), (d, n)) for s, e, d, n in _ZUP if n == name
            )
            ys, ye = _swap(s), _swap(e)
            row: dict[str, object] = {
                "flowpath": flowpath, "pipe": name,
                "from_node": start, "to_node": end,
                "x_m": float(ye[0]), "y_m": float(ye[1]), "z_m": float(ye[2]),
                "inner_diameter_m": float(diam), "roughness_m": float(ROUGH),
            }
            if position == 0:
                row["x_start_m"] = float(ys[0])
                row["y_start_m"] = float(ys[1])
                row["z_start_m"] = float(ys[2])
            twin_rows.append(row)
    twin_nodes = [
        {"node": "SRC", "node_kind": "source", "pressure_pa": 500000.0,
         "temperature_c": 25.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"node": "OUT_A", "node_kind": "sink", "pressure_pa": 100000.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"node": "OUT_B", "node_kind": "sink", "pressure_pa": 100000.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"node": "OUT_C", "node_kind": "sink", "pressure_pa": 100000.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"node": "OUT_D", "node_kind": "sink", "pressure_pa": 100000.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"node": "OUT_E", "node_kind": "sink", "pressure_pa": 100000.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"node": "OUT_F", "node_kind": "sink", "pressure_pa": 100000.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
    ]
    twin_result = _spec(twin_rows, twin_nodes)
    assert twin_result.issues == (), [
        (i.row, i.field, i.reason) for i in twin_result.issues
    ]
    assert _digest(endpoint_result.spec) == _digest(twin_result.spec)


def test_ends_use_the_sheet_frame_for_z_up() -> None:
    rows = [_pipe((1, 2, 3), (4, 6, 9), pipe="P1")]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="z")
    assert issues == ()
    by_name = {entry["name"]: entry for entry in summary["ends"]}
    assert (by_name[out[0]["from_node"]]["x_m"],
            by_name[out[0]["from_node"]]["y_m"],
            by_name[out[0]["from_node"]]["z_m"]) == (1.0, 2.0, 3.0)
    assert (by_name[out[0]["to_node"]]["x_m"],
            by_name[out[0]["to_node"]]["y_m"],
            by_name[out[0]["to_node"]]["z_m"]) == (4.0, 6.0, 9.0)
    assert (out[0]["y_m"], out[0]["z_m"]) == (9.0, 6.0)


def _brute_cluster(points):
    clusters = []
    for pid, point in enumerate(points):
        placed = False
        for members in clusters:
            import math as _math

            if all(_math.dist(point, points[mid]) <= 0.001 + 1e-12 for mid in members):
                members.append(pid)
                placed = True
                break
        if not placed:
            clusters.append([pid])
    return clusters


def test_cluster_matches_brute_force_pairwise() -> None:
    from olga_companion.pipe_table_endpoints import _cluster_points

    import random

    rng = random.Random(20260306)
    steps = [0.0, 0.0004, 0.0008, 0.0012, 0.0016, 0.002]
    for _trial in range(5):
        points = []
        for _ in range(120):
            base = (rng.choice([0, 10, 20]), rng.choice([0, 5]), rng.choice([0, 2]))
            points.append((base[0] + rng.choice(steps),
                           base[1] + rng.choice(steps),
                           base[2] + rng.choice(steps)))
        points += points[:20]
        order = list(range(len(points)))
        rng.shuffle(order)
        shuffled = [points[i] for i in order]
        got = _cluster_points(shuffled)
        want = _brute_cluster(shuffled)
        assert got == want


def test_rows_from_endpoints_matches_brute_force() -> None:
    import random

    for seed in (11, 22, 33):
        rng = random.Random(20260300 + seed)
        rows = []
        for number in range(24):
            ax, ay = rng.choice([0, 20, 40]), rng.choice([0, 20])
            bx, by = rng.choice([0, 20, 40]), rng.choice([0, 20])
            rows.append(_pipe(
                (ax + rng.uniform(0, 0.002), ay + rng.uniform(0, 0.002),
                 rng.uniform(0, 0.002)),
                (bx + rng.uniform(0, 0.002), by + rng.uniform(0, 0.002),
                 rng.uniform(0, 0.002)),
                pipe=f"P{number}"))
        grid = rows_from_endpoints(rows, vertical_axis="y")
        brute = rows_from_endpoints(rows, vertical_axis="y", _brute=True)
        assert grid == brute


def test_dense_ring_matches_brute_force() -> None:
    rows = []
    pitch, length = 0.005, 0.002
    for ix in range(15):
        for iy in range(10):
            for iz in range(2):
                start = (ix * pitch, iy * pitch, iz * pitch)
                rows.append(_pipe(start, (start[0] + length, start[1], start[2]),
                                 pipe=f"L{len(rows)}"))
    # Boundary distances, far from the lattice so they pair only with each other.
    rows.append(_pipe((9.95, 0.0, 0.0), (10.0, 0.0, 0.0), pipe="MM1"))
    rows.append(_pipe((10.001001, 0.0, 0.0), (10.051001, 0.0, 0.0), pipe="MM2"))
    rows.append(_pipe((19.95, 0.0, 0.0), (20.0, 0.0, 0.0), pipe="CM1"))
    rows.append(_pipe((20.099, 0.0, 0.0), (20.149, 0.0, 0.0), pipe="CM2"))
    rows.append(_pipe((29.95, 0.0, 0.0), (30.0, 0.0, 0.0), pipe="FAR1"))
    rows.append(_pipe((30.101, 0.0, 0.0), (30.151, 0.0, 0.0), pipe="FAR2"))
    # An exact tie: H1 and H2 sit exactly 5 mm from G's end (3-4-5 triangle).
    rows.append(_pipe((39.95, 0.0, 0.0), (40.0, 0.0, 0.0), pipe="TIE0"))
    rows.append(_pipe((40.003, 0.004, 0.0), (40.053, 0.004, 0.0), pipe="TIE1"))
    rows.append(_pipe((40.003, -0.004, 0.0), (40.053, -0.004, 0.0), pipe="TIE2"))
    grid = rows_from_endpoints(rows, vertical_axis="y")
    brute = rows_from_endpoints(rows, vertical_axis="y", _brute=True)
    assert grid == brute
    _out, issues, _summary = grid
    assert _out == []
    assert {issue.code for issue in issues} == {"endpoints_near_miss"}


def test_clustering_5000_points_in_a_1cm_cube() -> None:
    from olga_companion.pipe_table_endpoints import _cluster_points

    import random
    import time

    rng = random.Random(7)
    points = [(rng.uniform(0, 0.01), rng.uniform(0, 0.01), rng.uniform(0, 0.01))
              for _ in range(5000)]
    started = time.perf_counter()
    clusters = _cluster_points(points)
    elapsed = time.perf_counter() - started
    assert sum(map(len, clusters)) == 5000
    assert elapsed < 2


def test_5000_ends_in_one_cell_finish_quickly() -> None:
    import time

    step = 0.1 / 17

    def lattice(x: int, y: int, z: int) -> tuple[float, float, float]:
        return (step * x, step * y, step * z)

    rows = []
    for z in range(18):
        for y in range(18):
            for x in range(0, 18, 2):
                if len(rows) < 2500:
                    rows.append(_pipe(lattice(x, y, z), lattice(x + 1, y, z),
                                      pipe=f"P{len(rows)}"))
    started = time.perf_counter()
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    elapsed = time.perf_counter() - started
    assert out == []
    assert issues
    assert {issue.code for issue in issues} == {"endpoints_near_miss"}
    assert elapsed < 2


def test_pipe_end_touching_a_mid_segment_splits_a_junction() -> None:
    rows = [
        _pipe((0, 0, 0), (20, 0, 0), pipe="BAR"),
        _pipe((10, 0, 0), (10, 10, 0), pipe="STEM"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == (), [(i.row, i.field, i.code) for i in issues]
    assert summary["junctions"] == 1
    assert summary["flowpaths"] == 3
    assert len(summary["split_rows"]) == 1
    assert summary["split_rows"][0]["at"] == [10.0, 0.0, 0.0]
    assert {row["pipe"] for row in out} == {"BAR", "STEM"}


def test_short_spool_inside_a_chain_is_kept() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10, 0, 0), (10.05, 0, 0), pipe="P2"),
        _pipe((10.05, 0, 0), (20.05, 0, 0), pipe="P3"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == (), [(i.row, i.field, i.code) for i in issues]
    assert summary["flowpaths"] == 1
    assert [row["pipe"] for row in out] == ["P1", "P2", "P3"]


def test_two_floods_within_01m_finish_quickly() -> None:
    import time

    rows = []
    for number in range(3000):
        rows.append(_pipe((0, 0, 0), (10, 0, 0), pipe=f"A{number}"))
        rows.append(_pipe((0.05, 0, 0), (10.05, 0, 0), pipe=f"B{number}"))
    started = time.perf_counter()
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    elapsed = time.perf_counter() - started
    assert out == []
    assert sum(1 for issue in issues if issue.code == "endpoints_near_miss") == 4
    assert elapsed < 10


_ENDPOINT_CASES = [
    ("endpoints_start_missing",
     [{**_pipe((0, 0, 0), (10, 0, 0), pipe="P1"), "x_start_m": None}], "y", set()),
    ("endpoints_end_missing",
     [{**_pipe((0, 0, 0), (10, 0, 0), pipe="P1"), "x_m": None}], "y", set()),
    ("endpoints_start_not_finite",
     [{**_pipe((0, 0, 0), (10, 0, 0), pipe="P1"), "y_start_m": float("nan")}], "y", set()),
    ("endpoints_end_not_finite",
     [{**_pipe((0, 0, 0), (10, 0, 0), pipe="P1"), "z_m": float("inf")}], "y", set()),
    ("endpoints_length_not_number",
     [_pipe((0, 0, 0), (10, 0, 0), pipe="P1", extra={"length_m": "long"})], "y", set()),
    ("endpoints_length_mismatch",
     [_pipe((0, 0, 0), (10, 0, 0), pipe="P1", extra={"length_m": 12.0})],
     "y", {"stated_m", "actual_m"}),
    ("endpoints_rise_not_number",
     [_pipe((0, 0, 0), (10, 0, 4), pipe="P1", extra={"elevation_m": "high"})], "z", set()),
    ("endpoints_rise_mismatch",
     [_pipe((0, 0, 0), (10, 0, 4), pipe="P1", extra={"elevation_m": 0.0})],
     "z", {"stated_m", "actual_m"}),
    ("endpoints_ambiguous_node",
     [_pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
      _pipe((10.0009, 0, 0), (20, 0, 0), pipe="P2"),
      _pipe((10.0018, 0, 0), (30, 0, 0), pipe="P3")], "y", {"other_row"}),
    ("endpoints_near_miss",
     [_pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
      _pipe((10.05, 0, 0), (20, 0, 0), pipe="P2")], "y", {"other_row", "distance_mm"}),
    ("endpoints_parallel_pipes",
     [_pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
      _pipe((0, 0, 0), (10, 0, 0), pipe="P2")], "y", {"other_row"}),
    ("endpoints_self_loop",
     [_pipe((5, 0, 0), (5, 0, 0), pipe="P1")], "y", set()),
    ("endpoints_cycle",
     [_pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
      _pipe((10, 0, 0), (5, 8, 0), pipe="P2"),
      _pipe((5, 8, 0), (0, 0, 0), pipe="P3")], "y", set()),
    ("endpoints_chain_orientation",
     [_pipe((0, 0, 0), (10, 0, 0), pipe="A"),
      _pipe((0, 5, 0), (10, 0, 0), pipe="B")], "y", {"incoming", "outgoing", "at"}),
    ("endpoints_junction_degree",
     [_pipe((0, 0, 0), (10, 0, 0), pipe="A"),
      _pipe((0, 5, 0), (10, 0, 0), pipe="B"),
      _pipe((10, 0, 0), (20, 0, 0), pipe="C"),
      _pipe((10, 0, 0), (20, 5, 0), pipe="D")],
     "y", {"incoming", "outgoing"}),
    ("endpoints_columns_given",
     [{**_pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
       "flowpath": "FP", "from_node": "A", "to_node": "B"}],
     "y", {"column"}),
    ("endpoints_valve_at_split",
     [_pipe((0, 0, 0), (10, 0, 0), pipe="BAR", extra={
         "valve": "V1", "valve_position": 0.5,
         "valve_schedule": "0:1", "valve_diameter_m": 0.04}),
      _pipe((5, 0, 0), (5, 0, 5), pipe="STEM")],
     "y", {"position"}),
]
# Codes that only fire with extra call arguments.
_ENDPOINT_CALL_CASES = [
    ("endpoints_split_recursion",
     [_pipe((0, 0, 0), (10, 0, 0), pipe="BAR"),
      _pipe((5, 0, 0), (5, 0, 5), pipe="STEM")],
     "y", set(), {"_depth": 10}),
]


@pytest.mark.parametrize(
    "code,rows,axis,param_keys,call_kwargs",
    [pytest.param(code, rows, axis, keys, {}, id=code) for code, rows, axis, keys in _ENDPOINT_CASES]
    + [pytest.param(code, rows, axis, keys, kwargs, id=code)
       for code, rows, axis, keys, kwargs in _ENDPOINT_CALL_CASES],
)
def test_each_endpoint_code_fires_with_its_params(code, rows, axis, param_keys, call_kwargs) -> None:
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis=axis, **call_kwargs)
    assert out == []
    matching = [issue for issue in issues if issue.code == code]
    assert matching, f"no issue with code {code}: {issues!r}"
    for issue in matching:
        assert set(issue.params.keys()) == set(param_keys)


def test_endpoint_codes_seen_equal_the_registry() -> None:
    from olga_companion.pipe_table_endpoints import ENDPOINT_ISSUE_CODES

    seen: set[str] = set()
    for code, rows, axis, _keys in _ENDPOINT_CASES:
        _out, issues, _summary = rows_from_endpoints(rows, vertical_axis=axis)
        seen.update(issue.code for issue in issues if issue.code == code)
    for code, rows, axis, _keys, kwargs in _ENDPOINT_CALL_CASES:
        _out, issues, _summary = rows_from_endpoints(rows, vertical_axis=axis, **kwargs)
        seen.update(issue.code for issue in issues if issue.code == code)
    assert seen == set(ENDPOINT_ISSUE_CODES)


def test_ring_with_a_5cm_gap_is_refused_on_rows_3_and_1() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10, 0, 0), (5, 8, 0), pipe="P2"),
        _pipe((5, 8, 0), (0.05, 0, 0), pipe="P3"),
    ]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    assert {(issue.row, issue.code) for issue in issues} == {
        (1, "endpoints_near_miss"), (3, "endpoints_near_miss"),
    }


def test_chain_of_three_3cm_spools_is_accepted() -> None:
    rows = [
        _pipe((0, 0, 0), (0.03, 0, 0), pipe="P1"),
        _pipe((0.03, 0, 0), (0.06, 0, 0), pipe="P2"),
        _pipe((0.06, 0, 0), (0.09, 0, 0), pipe="P3"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == (), [(i.row, i.field, i.code) for i in issues]
    assert summary["flowpaths"] == 1
    assert [row["pipe"] for row in out] == ["P1", "P2", "P3"]


def test_tee_with_a_5cm_stub_is_accepted() -> None:
    # The stub touches the main pipe mid-segment, so the main pipe splits
    # there and a junction forms; the stub is accepted, not refused.
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((5, 0, 0), (5, 0, 0.05), pipe="P2"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == (), [(i.row, i.field, i.code) for i in issues]
    assert summary["flowpaths"] == 3
    assert summary["junctions"] == 1
    assert summary["ends_total"] == 3
    assert len(summary["split_rows"]) == 1
    assert len(out) == 3


def test_near_miss_between_two_short_pipe_components_is_refused() -> None:
    rows = [
        _pipe((0, 0, 0), (0.05, 0, 0), pipe="P1"),
        _pipe((0.10, 0, 0), (0.15, 0, 0), pipe="P2"),
    ]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    assert {(issue.row, issue.code) for issue in issues} == {
        (1, "endpoints_near_miss"), (2, "endpoints_near_miss"),
    }


def test_single_absurdly_long_pipe_finishes_within_one_second() -> None:
    import time

    started = time.perf_counter()
    out, issues, summary = rows_from_endpoints(
        [_pipe((0.0, 0.0, 0.0), (10_000_000.0, 0.0, 0.0), pipe="LONG")],
        vertical_axis="y",
    )
    elapsed = time.perf_counter() - started
    assert issues == (), [issue.message for issue in issues]
    assert len(out) == 1
    assert summary["flowpaths"] == 1
    assert elapsed < 1, f"took {elapsed:.2f}s"


def test_split_heavy_twenty_thousand_row_table_stays_bounded() -> None:
    import time

    rows = []
    for n in range(10_000):
        base = 10.0 * n
        rows.append(_pipe((base, 0.0, 0.0), (base + 10.0, 0.0, 0.0), pipe=f"T{n}"))
        rows.append(
            _pipe((base + 5.0, 0.0, 0.0), (base + 5.0, 0.0, 5.0), pipe=f"S{n}")
        )
    started = time.perf_counter()
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    elapsed = time.perf_counter() - started
    assert issues == (), [issue.message for issue in issues]
    assert len(summary["split_rows"]) == 10_000
    assert elapsed < 6, f"took {elapsed:.2f}s"


def _valved_tee(position: object) -> list[dict[str, object]]:
    return [
        _pipe((0, 0, 0), (10, 0, 0), pipe="BAR", extra={
            "valve": "V1", "valve_position": position,
            "valve_schedule": "0:1", "valve_diameter_m": 0.04}),
        _pipe((5, 0, 0), (5, 0, 5), pipe="STEM"),
    ]


def test_valve_exactly_at_a_split_point_is_refused() -> None:
    out, issues, _summary = rows_from_endpoints(
        _valved_tee(0.5), vertical_axis="y")
    assert out == []
    assert [(issue.row, issue.code) for issue in issues] == [
        (1, "endpoints_valve_at_split")]
    assert issues[0].params == {"position": 0.5}


def test_valve_stays_on_the_piece_containing_its_position() -> None:
    out, issues, summary = rows_from_endpoints(
        _valved_tee(0.25), vertical_axis="y")
    assert issues == (), [issue.message for issue in issues]
    assert summary["flowpaths"] == 3
    valved = [row for row in out if row.get("valve") == "V1"]
    assert len(valved) == 1
    assert (valved[0]["x_start_m"], valved[0]["x_m"]) == (0.0, 5.0)
    assert valved[0]["valve_position"] == 0.5
    assert valved[0]["valve_schedule"] == "0:1"
    assert valved[0]["valve_diameter_m"] == 0.04
    assert all("valve" not in key for row in out if row is not valved[0]
               for key in row if key.startswith("valve"))


def test_valve_at_three_quarters_stays_on_the_second_piece() -> None:
    out, issues, _summary = rows_from_endpoints(
        _valved_tee(0.75), vertical_axis="y")
    assert issues == (), [issue.message for issue in issues]
    valved = [row for row in out if row.get("valve") == "V1"]
    assert len(valved) == 1
    assert (valved[0]["x_start_m"], valved[0]["x_m"]) == (5.0, 10.0)
    assert valved[0]["valve_position"] == 0.5


def test_valve_in_the_middle_of_three_pieces() -> None:
    rows = [
        _pipe((0, 0, 0), (12, 0, 0), pipe="BAR", extra={
            "valve": "V1", "valve_position": 0.75,
            "valve_schedule": "0:1", "valve_diameter_m": 0.04}),
        _pipe((4, 0, 0), (4, 0, 5), pipe="S1"),
        _pipe((8, 0, 0), (8, 0, 5), pipe="S2"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == (), [issue.message for issue in issues]
    assert summary["flowpaths"] == 5
    valved = [row for row in out if row.get("valve") == "V1"]
    assert len(valved) == 1
    assert (valved[0]["x_start_m"], valved[0]["x_m"]) == (8.0, 12.0)
    assert valved[0]["valve_position"] == 0.25
    assert all("valve" not in key for row in out if row is not valved[0]
               for key in row if key.startswith("valve"))


def test_unparseable_valve_position_stays_on_the_first_piece() -> None:
    out, issues, _summary = rows_from_endpoints(
        _valved_tee("half"), vertical_axis="y")
    assert issues == (), [issue.message for issue in issues]
    valved = [row for row in out if row.get("valve") == "V1"]
    assert len(valved) == 1
    assert (valved[0]["x_start_m"], valved[0]["x_m"]) == (0.0, 5.0)
    assert valved[0]["valve_position"] == "half"


def test_sample_budget_trip_sets_split_skipped(monkeypatch) -> None:
    import olga_companion.pipe_table_endpoints as endpoints

    monkeypatch.setattr(endpoints, "_SPLIT_MAX_TOTAL_SAMPLES", 10, raising=False)
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="BAR"),
        _pipe((5, 0, 0), (5, 0, 5), pipe="STEM"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == (), [issue.message for issue in issues]
    assert summary.get("split_skipped") is True
    assert summary["flowpaths"] == 2


def test_budget_tripping_table_stays_under_300mb() -> None:
    import tracemalloc

    rows = []
    for n in range(2000):
        base = 2500.0 * n
        rows.append(_pipe((base, 0.0, 0.0), (base + 2000.0, 0.0, 0.0),
                          pipe=f"T{n}"))
    tracemalloc.start()
    try:
        _out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    finally:
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert issues == (), [issue.message for issue in issues]
    assert summary.get("split_skipped") is True
    assert peak < 300_000_000, f"peak {peak / 1e6:.0f} MB"


def _banded_longs(n_longs: int, n_shorts: int) -> list[dict[str, object]]:
    rows = []
    for i in range(n_longs):
        rows.append(_pipe((0.0, 300.0 * i, 0.0), (9000.0, 300.0 * i, 0.0),
                          pipe=f"L{i}"))
    for j in range(n_shorts):
        gx, gy = divmod(j, 56)
        rows.append(_pipe((20000.0 + 300.0 * gx, 300.0 * gy, 0.0),
                          (20010.0 + 300.0 * gx, 300.0 * gy, 0.0),
                          pipe=f"S{j}"))
    return rows


def test_exact_trip_drops_the_whole_split_pass(monkeypatch) -> None:
    import olga_companion.pipe_table_endpoints as endpoints

    monkeypatch.setattr(endpoints, "_SPLIT_MAX_EXACT", 0)
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="BAR"),
        _pipe((5, 0, 0), (5, 0, 5), pipe="STEM"),
        _pipe((0, 20000, 0), (9000, 20000, 0), pipe="LONG"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == (), [issue.message for issue in issues]
    assert summary.get("split_skipped") is True
    assert summary.get("split_rows", []) == []
    assert summary["flowpaths"] == 3


def test_projection_trip_reports_split_skipped(monkeypatch) -> None:
    import olga_companion.pipe_table_endpoints as endpoints

    monkeypatch.setattr(endpoints, "_SPLIT_MAX_PROJECTIONS", 0)
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="BAR"),
        _pipe((5, 0, 0), (5, 0, 5), pipe="STEM"),
    ]
    out, issues, summary = rows_from_endpoints(rows, vertical_axis="y")
    assert issues == (), [issue.message for issue in issues]
    assert summary.get("split_skipped") is True
    assert summary["flowpaths"] == 2


def test_exact_count_trip_reports_split_skipped() -> None:
    out, issues, summary = rows_from_endpoints(
        _banded_longs(300, 3100), vertical_axis="y")
    assert issues == (), [issue.message for issue in issues]
    assert summary.get("split_skipped") is True
    assert summary.get("split_rows", []) == []


def test_heavy_exact_pass_finishes_quickly() -> None:
    import time

    started = time.perf_counter()
    out, issues, summary = rows_from_endpoints(
        _banded_longs(100, 1900), vertical_axis="y")
    elapsed = time.perf_counter() - started
    assert issues == (), [issue.message for issue in issues]
    assert summary.get("split_skipped") is False
    assert elapsed < 10, f"took {elapsed:.2f}s"


def test_input_rows_survives_splits() -> None:
    out, issues, summary = rows_from_endpoints([
        _pipe((0, 0, 0), (10, 0, 0), pipe="BAR"),
        _pipe((5, 0, 0), (5, 0, 5), pipe="STEM"),
    ], vertical_axis="y")
    assert issues == (), [issue.message for issue in issues]
    assert summary["input_rows"] == 2
    assert summary["pipes"] == 3


def test_touch_on_a_20km_pipe_splits() -> None:
    out, issues, summary = rows_from_endpoints([
        _pipe((0, 0, 0), (20000, 0, 0), pipe="BAR"),
        _pipe((10002.5, 0, 0), (10002.5, 0, 5), pipe="STEM"),
    ], vertical_axis="y")
    assert issues == (), [issue.message for issue in issues]
    assert summary["flowpaths"] == 3
    assert summary.get("split_skipped") is False
    assert summary["split_rows"] == [{"line": 1, "at": [10002.5, 0.0, 0.0]}]


def test_split_recursion_depth_is_guarded() -> None:
    rows = [
        _pipe((0, 0, 0), (10, 0, 0), pipe="BAR"),
        _pipe((5, 0, 0), (5, 0, 5), pipe="STEM"),
    ]
    out, issues, _summary = rows_from_endpoints(
        rows, vertical_axis="y", _depth=10)
    assert out == []
    assert [(issue.row, issue.code) for issue in issues] == [
        (1, "endpoints_split_recursion")]
    grown, grown_issues, grown_summary = rows_from_endpoints(
        rows, vertical_axis="y", _depth=9)
    assert grown_issues == (), [issue.message for issue in grown_issues]
    assert grown_summary["split_rows"]


def test_collinear_overlap_is_refused() -> None:
    out, issues, _summary = rows_from_endpoints([
        _pipe((0, 0, 0), (10, 0, 0), pipe="A"),
        _pipe((3, 0, 0), (7, 0, 0), pipe="B"),
    ], vertical_axis="y")
    assert out == []
    assert [(issue.row, issue.code) for issue in issues] == [
        (1, "endpoints_parallel_pipes")]
    assert issues[0].params == {"other_row": 2}


def test_near_miss_created_by_a_split_point_is_refused() -> None:
    out, issues, _summary = rows_from_endpoints([
        _pipe((0, 0, 0), (10, 0, 0), pipe="BAR"),
        _pipe((2, 0.0009, 0), (2, 5, 0), pipe="STEM"),
        _pipe((2.0999, -0.004, 0), (7.0999, -0.004, 0), pipe="WISP"),
    ], vertical_axis="y")
    assert out == []
    assert {(issue.row, issue.code) for issue in issues} == {
        (1, "endpoints_near_miss"), (3, "endpoints_near_miss")}


def test_touch_plus_near_miss_refuses_without_splitting() -> None:
    out, issues, summary = rows_from_endpoints([
        _pipe((0, 0, 0), (10, 0, 0), pipe="BAR"),
        _pipe((5, 0, 0), (5, 0, 5), pipe="STEM"),
        _pipe((20, 0, 0), (20.05, 0, 0), pipe="P1"),
        _pipe((20.10, 0, 0), (20.15, 0, 0), pipe="P2"),
    ], vertical_axis="y")
    assert out == []
    assert {issue.code for issue in issues} == {"endpoints_near_miss"}
    assert summary.get("split_rows", []) == []


def test_near_miss_tie_goes_to_the_earliest_row() -> None:
    rows = [
        _pipe((0, 0, 0), (0, 0, 10), pipe="P1"),
        _pipe((0.05, 0, 0), (0.05, 0, 10), pipe="P2"),
        _pipe((-0.05, 0, 0), (-0.05, 0, 10), pipe="P3"),
    ]
    out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert out == []
    by_row = {issue.row: issue for issue in issues if issue.code == "endpoints_near_miss"}
    assert by_row[1].params["other_row"] == 2


def test_orientation_at_pins_start_and_end() -> None:
    rows = [
        _pipe((10, 0, 0), (0, 0, 0), pipe="A"),
        _pipe((10, 0, 0), (0, 5, 0), pipe="B"),
    ]
    _out, issues, _summary = rows_from_endpoints(rows, vertical_axis="y")
    assert _out == []
    assert [(issue.row, issue.params["at"]) for issue in issues
            if issue.code == "endpoints_chain_orientation"] == [(1, "start"), (2, "start")]
    _out, issues, _summary = rows_from_endpoints([
        _pipe((0, 0, 0), (10, 0, 0), pipe="P1"),
        _pipe((10, 0, 0), (5, 8, 0), pipe="P2"),
        _pipe((5, 8, 0), (0, 0, 0), pipe="P3"),
    ], vertical_axis="y")
    assert _out == []
    assert [(issue.row, issue.code) for issue in issues] == [(3, "endpoints_cycle")]
    assert all("at" not in issue.params for issue in issues)
