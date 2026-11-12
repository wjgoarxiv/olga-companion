"""Endpoints pre-pass: per-pipe start/end x/y/z to flowpath rows.

Each input row gives one pipe with its start and end coordinates. Endpoints
within 1 mm join into one node; chains become one flowpath; degree 1 ends
become END_nnn. Axes are reordered to Y-up before handing over. Mapping Z-up
(x, y, z) to Y-up (x, z, y) mirrors handedness; lengths and topology are unchanged.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from .pipe_table_import import ImportIssue

_NODE_TOL_M = 0.001
_NEAR_MISS_M = 0.1
_MAX_METRES = 10_000_000.0
_EPS = 1e-9
_CELL_M = 0.1
_CELL_1MM_M = 0.001
_NEIGHBOURS = tuple(
    (dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
)
_SCAN_CELL_M = 0.005
_SCAN_CUTOFF = 256
_SPLIT_FINE_M = 0.005
_SPLIT_FINE_STEP_M = 0.0025
_SPLIT_COARSE_M = 1.0
_SPLIT_COARSE_STEP_M = 0.5
_SPLIT_SHORT_M = 2.0
_SPLIT_MAX_SAMPLES = 4096
_SPLIT_MAX_TOTAL_SAMPLES = 1_500_000
_SPLIT_MAX_PROJECTIONS = 10_000_000
_SPLIT_MAX_EXACT = 2_000_000
_SPLIT_LONG_M = 8000.0
_MAX_SPLIT_DEPTH = 10
_MAX_ENDS = 100
_MAX_MERGED = 50
_MAX_MERGED_ROWS = 200

# Stable codes for every issue the pre-pass can raise. The chat renders
# `pipeDraft.reason.<code>` with `params` and keeps the English `reason`.
ENDPOINT_ISSUE_CODES: tuple[str, ...] = (
    "endpoints_start_missing",
    "endpoints_end_missing",
    "endpoints_start_not_finite",
    "endpoints_end_not_finite",
    "endpoints_length_not_number",
    "endpoints_length_mismatch",
    "endpoints_rise_not_number",
    "endpoints_rise_mismatch",
    "endpoints_ambiguous_node",
    "endpoints_near_miss",
    "endpoints_parallel_pipes",
    "endpoints_self_loop",
    "endpoints_cycle",
    "endpoints_chain_orientation",
    "endpoints_junction_degree",
    "endpoints_columns_given",
    "endpoints_valve_at_split",
    "endpoints_split_recursion",
)


def _is_num(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) <= _MAX_METRES
    return (
        isinstance(value, float)
        and math.isfinite(value)
        and abs(value) <= _MAX_METRES
    )


def _reorder(point: tuple[float, float, float], vertical_axis: str) -> tuple[float, float, float]:
    x, y, z = point
    if vertical_axis == "z":
        return (x, z, y)
    return (x, y, z)


def _cell_key(point: tuple[float, float, float], size: float = _CELL_M) -> tuple[int, int, int]:
    return (
        math.floor(point[0] / size),
        math.floor(point[1] / size),
        math.floor(point[2] / size),
    )


def _cluster_points(
    points: Sequence[tuple[float, float, float]], _brute: bool = False,
) -> list[list[int]]:
    """Greedy clique clustering in first-seen order over a 1 mm hash grid."""
    grid: dict[tuple[int, int, int], list[int]] = {}
    clusters: list[list[int]] = []
    assignment = [-1] * len(points)
    for pid, point in enumerate(points):
        if _brute:
            candidates: object = range(len(clusters))
        else:
            key = _cell_key(point, _CELL_1MM_M)
            found: set[int] = set()
            for dx, dy, dz in _NEIGHBOURS:
                for oid in grid.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                    found.add(assignment[oid])
            candidates = sorted(found)
        placed = False
        for cid in candidates:  # type: ignore[union-attr]
            if all(math.dist(point, points[mid]) <= _NODE_TOL_M + 1e-12
                   for mid in clusters[cid]):
                clusters[cid].append(pid)
                assignment[pid] = cid
                placed = True
                break
        if not placed:
            assignment[pid] = len(clusters)
            clusters.append([pid])
        if not _brute:
            grid.setdefault(key, []).append(pid)
    return clusters


_Point = tuple[float, float, float]
_Cells = dict[tuple[int, int, int], list[int]]
_Touch = dict[tuple[int, int], tuple[float, float, float, float, float]]
_SplitPlan = dict[int, list[tuple[float, float, float, float]]]
_Result = tuple[list[dict[str, object]], tuple[ImportIssue, ...], dict[str, object]]


@dataclass
class _Parsed:
    """Rows with their source lines and the start/end points that parsed."""

    rows: Sequence[Mapping[str, object]]
    line_of: list[int | None]
    starts: list[_Point | None]
    ends: list[_Point | None]
    passthrough: list[bool]


@dataclass
class _Graph:
    """Endpoint points, their 1 mm clusters and each pipe's two cluster ids."""

    points: list[_Point]
    point_row: list[int]
    point_is_start: list[bool]
    uniq_points: list[_Point]
    uid_pids: list[list[int]]
    uid_rows: list[list[int]]
    clusters: list[list[int]]
    point_cluster: list[int]
    pipe_cluster_start: list[int]
    pipe_cluster_end: list[int]
    pipe_index: list[int]


def _checked_roughness(vertical_axis: str, roughness_m: float | None) -> float | None:
    if vertical_axis not in ("y", "z"):
        raise ValueError("vertical_axis must be 'y' or 'z'")
    if roughness_m is not None:
        if (
            isinstance(roughness_m, bool)
            or not isinstance(roughness_m, (int, float))
            or not math.isfinite(float(roughness_m))
            or float(roughness_m) < 0
        ):
            raise ValueError("roughness_m must be a finite length of zero or more")
        roughness_m = float(roughness_m)
    return roughness_m


def _parse_rows(
    rows: Sequence[Mapping[str, object]],
    line_of: list[int | None],
    vertical_axis: str,
    issues: list[ImportIssue],
) -> _Parsed:
    """Read each row's start/end points and refuse the rows that cannot be read."""
    count = len(rows)
    starts: list[_Point | None] = [None] * count
    ends: list[_Point | None] = [None] * count
    passthrough: list[bool] = [False] * count
    for index, row in enumerate(rows):
        line = line_of[index]
        node = row.get("node")
        if isinstance(node, str) and node.strip() and all(
            row.get(key) is None for key in (
                "x_start_m", "y_start_m", "z_start_m", "x_m", "y_m", "z_m")
        ):
            passthrough[index] = True
            continue
        given = [
            key for key in ("flowpath", "from_node", "to_node")
            if isinstance(row.get(key), str) and row.get(key).strip()  # type: ignore[union-attr]
        ]
        if given:
            for hit in given:
                issues.append(ImportIssue(
                    line, hit,
                    f"the {hit} column is not used in endpoints mode: remove the "
                    "column or map it away with column_map",
                    "endpoints_columns_given", {"column": hit}))
            continue
        sval = [row.get(key) for key in ("x_start_m", "y_start_m", "z_start_m")]
        eval_ = [row.get(key) for key in ("x_m", "y_m", "z_m")]
        if any(value is None for value in sval):
            issues.append(ImportIssue(
                line, "x_start_m",
                "give x_start_m, y_start_m and z_start_m together as numbers",
                "endpoints_start_missing", {}))
            continue
        if any(value is None for value in eval_):
            issues.append(ImportIssue(
                line, "x_m", "give x_m, y_m and z_m together as numbers",
                "endpoints_end_missing", {}))
            continue
        if not all(_is_num(value) for value in sval):
            issues.append(ImportIssue(
                line, "x_start_m", "value is not a finite length up to 10,000 km",
                "endpoints_start_not_finite", {}))
            continue
        if not all(_is_num(value) for value in eval_):
            issues.append(ImportIssue(
                line, "x_m", "value is not a finite length up to 10,000 km",
                "endpoints_end_not_finite", {}))
            continue
        s = (float(sval[0]), float(sval[1]), float(sval[2]))  # type: ignore[arg-type]
        e = (float(eval_[0]), float(eval_[1]), float(eval_[2]))  # type: ignore[arg-type]
        starts[index], ends[index] = s, e
        coord_length = math.dist(s, e)
        rise = (e[2] - s[2]) if vertical_axis == "z" else (e[1] - s[1])
        stated_length = row.get("length_m")
        if stated_length is not None:
            if not _is_num(stated_length):
                issues.append(ImportIssue(
                    line, "length_m", "length_m is not a number",
                    "endpoints_length_not_number", {}))
                continue
            if abs(coord_length - float(stated_length)) > max(
                0.01, 0.01 * abs(float(stated_length))
            ) + _EPS:
                issues.append(ImportIssue(
                    line, "length_m",
                    "the stated length disagrees with the coordinates by more "
                    "than the larger of 1% and 0.01 m",
                    "endpoints_length_mismatch",
                    {"stated_m": round(float(stated_length), 4),
                     "actual_m": round(coord_length, 4)}))
                continue
        stated_rise = row.get("elevation_m")
        if stated_rise is not None:
            if not _is_num(stated_rise):
                issues.append(ImportIssue(
                    line, "elevation_m", "elevation_m is not a number",
                    "endpoints_rise_not_number", {}))
                continue
            if abs(rise - float(stated_rise)) > max(
                0.01, 0.01 * abs(float(stated_rise))
            ) + _EPS:
                issues.append(ImportIssue(
                    line, "elevation_m",
                    "the stated rise disagrees with the coordinates by more "
                    "than the larger of 1% and 0.01 m",
                    "endpoints_rise_mismatch",
                    {"stated_m": round(float(stated_rise), 4),
                     "actual_m": round(rise, 4)}))
                continue
    return _Parsed(rows, line_of, starts, ends, passthrough)


def _rasterize(
    parsed: _Parsed,
) -> tuple[list[_Point], list[_Point], _Cells, _Cells, bool]:
    """Sample every segment into a fine (short) or coarse (long) cell grid.

    Samples sit at most half a step from any segment point, well under one
    cell, so a point within the touch tolerance always shares a cell
    neighbourhood with a sample of the segment it touches. Sampling is capped
    per segment (absurd lengths fall back to wider spacing) and in total; the
    last value is True when the total budget tripped.
    """
    seg_starts: list[_Point] = []
    seg_ends: list[_Point] = []
    fine: _Cells = {}
    coarse: _Cells = {}
    samples = 0
    skipped = False
    for index in range(len(parsed.rows)):
        if skipped:
            break
        if parsed.passthrough[index] or parsed.starts[index] is None or parsed.ends[index] is None:
            seg_starts.append((0.0, 0.0, 0.0))
            seg_ends.append((0.0, 0.0, 0.0))
            continue
        a = parsed.starts[index]
        b = parsed.ends[index]
        assert a is not None and b is not None
        seg_starts.append(a)
        seg_ends.append(b)
        length = math.dist(a, b)
        if length <= _SPLIT_SHORT_M:
            cell, step = _SPLIT_FINE_M, _SPLIT_FINE_STEP_M
            grid = fine
        else:
            cell, step = _SPLIT_COARSE_M, _SPLIT_COARSE_STEP_M
            grid = coarse
        steps = min(max(1, math.ceil(length / step)), _SPLIT_MAX_SAMPLES)
        for part in range(steps + 1):
            samples += 1
            if samples > _SPLIT_MAX_TOTAL_SAMPLES:
                skipped = True
                break
            frac = part / steps
            key = _cell_key(
                (a[0] + (b[0] - a[0]) * frac,
                 a[1] + (b[1] - a[1]) * frac,
                 a[2] + (b[2] - a[2]) * frac),
                cell,
            )
            grid.setdefault(key, []).append(index)
    return seg_starts, seg_ends, fine, coarse, skipped


def _candidate_segments(point: _Point, fine: _Cells, coarse: _Cells) -> Iterator[int]:
    """Segments sampled in a cell next to `point`, each once, fine grid first."""
    tried: set[int] = set()
    for cell, cells in ((_SPLIT_FINE_M, fine), (_SPLIT_COARSE_M, coarse)):
        key = _cell_key(point, cell)
        for dx, dy, dz in _NEIGHBOURS:
            for other in cells.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                if other in tried:
                    continue
                tried.add(other)
                yield other


def _note_touch(
    touch: _Touch, slot: tuple[int, int], point: _Point, start: _Point, end: _Point,
) -> None:
    """Keep the closest interior touch of `point` on segment start-end for `slot`.

    Only a true interior touch splits; a touch at an end is a plain endpoint
    join handled by clustering.
    """
    ax, ay, az = start
    bx, by, bz = end
    abx, aby, abz = bx - ax, by - ay, bz - az
    denom = abx * abx + aby * aby + abz * abz
    if denom == 0.0:
        return
    along_x = (point[0] - ax) * abx
    along_y = (point[1] - ay) * aby
    along_z = (point[2] - az) * abz
    ratio = (along_x + along_y + along_z) / denom
    limited = 0.0 if ratio < 0.0 else (1.0 if ratio > 1.0 else ratio)
    qx, qy, qz = ax + limited * abx, ay + limited * aby, az + limited * abz
    ex, ey, ez = point[0] - qx, point[1] - qy, point[2] - qz
    if ex * ex + ey * ey + ez * ez > (_NODE_TOL_M + 1e-12) ** 2:
        return
    if math.dist((qx, qy, qz), (ax, ay, az)) <= _NODE_TOL_M:
        return
    if math.dist((qx, qy, qz), (bx, by, bz)) <= _NODE_TOL_M:
        return
    along = math.dist((qx, qy, qz), (ax, ay, az))
    dist2 = ex * ex + ey * ey + ez * ez
    prev = touch.get(slot)
    if prev is None or dist2 < prev[4]:
        touch[slot] = (along, qx, qy, qz, dist2)


def _project_touches(
    parsed: _Parsed,
    seg_starts: Sequence[_Point],
    seg_ends: Sequence[_Point],
    fine: _Cells,
    coarse: _Cells,
) -> tuple[dict[_Point, int], _Touch, bool]:
    """Project every unique endpoint on the segments sampled next to it.

    Returns the unique endpoints (first row each), the touches found, and True
    when the projection budget tripped; the search then abandons everything.
    """
    touch: _Touch = {}
    seen: dict[_Point, int] = {}
    projections = 0
    for index in range(len(parsed.rows)):
        if parsed.passthrough[index] or parsed.starts[index] is None or parsed.ends[index] is None:
            continue
        for point in (parsed.starts[index], parsed.ends[index]):
            assert point is not None
            if point in seen:
                continue
            seen[point] = index
            for other in _candidate_segments(point, fine, coarse):
                projections += 1
                if projections > _SPLIT_MAX_PROJECTIONS:
                    touch.clear()
                    return seen, touch, True
                _note_touch(touch, (other, index), point, seg_starts[other], seg_ends[other])
    return seen, touch, False


def _long_segment_touches(
    seg_starts: Sequence[_Point],
    seg_ends: Sequence[_Point],
    seen: Mapping[_Point, int],
    touch: _Touch,
) -> bool:
    """Check each long segment exactly against every unique endpoint.

    Long segments sample too sparsely to catch every touch. Few long rows make
    this cheap; too many returns True (the skip) and drops the pass, like the
    projection budget.
    """
    longs = [
        index for index in range(len(seg_starts))
        if math.dist(seg_starts[index], seg_ends[index]) > _SPLIT_LONG_M
    ]
    if len(longs) * len(seen) > _SPLIT_MAX_EXACT:
        touch.clear()
        return True
    for other in longs:
        for point in seen:
            _note_touch(touch, (other, seen[point]), point, seg_starts[other], seg_ends[other])
    return False


def _plan_splits(touch: _Touch) -> _SplitPlan:
    """One split point per along-segment neighbourhood, per target segment.

    Touches within a millimetre of each other name the same junction.
    """
    by_target: dict[int, list[tuple[float, float, float, float]]] = {}
    for (target, _), (along, qx, qy, qz, _dist2) in touch.items():
        by_target.setdefault(target, []).append((along, qx, qy, qz))
    split_plan: _SplitPlan = {}
    for target in sorted(by_target):
        kept: list[tuple[float, float, float, float]] = []
        for item in sorted(by_target[target]):
            if kept and item[0] - kept[-1][0] < _NODE_TOL_M:
                continue
            kept.append(item)
        if kept:
            split_plan[target] = kept
    return split_plan


def _find_splits(parsed: _Parsed) -> tuple[list[_Point], list[_Point], _SplitPlan, bool]:
    """Where other pipes touch a pipe mid-segment, and whether the search was skipped.

    Any skip reports split_skipped, so pathological inputs keep legacy endpoint
    behaviour instead of hanging. The plan applies later, and only when the
    untouched geometry is clean: an end-to-end near miss keeps its own refusal
    instead of being reworked into a junction first.
    """
    if not parsed.rows:
        return [], [], {}, False
    seg_starts, seg_ends, fine, coarse, skipped = _rasterize(parsed)
    touch: _Touch = {}
    if not skipped:
        seen, touch, skipped = _project_touches(parsed, seg_starts, seg_ends, fine, coarse)
        if not skipped:
            skipped = _long_segment_touches(seg_starts, seg_ends, seen, touch)
    return seg_starts, seg_ends, _plan_splits(touch), skipped


def _build_graph(parsed: _Parsed, brute: bool) -> _Graph:
    count = len(parsed.rows)
    points: list[_Point] = []
    point_row: list[int] = []
    point_is_start: list[bool] = []
    for index in range(count):
        if parsed.passthrough[index] or parsed.starts[index] is None:
            continue
        assert parsed.starts[index] is not None and parsed.ends[index] is not None
        points.append(parsed.starts[index])  # type: ignore[arg-type]
        point_row.append(index)
        point_is_start.append(True)
        points.append(parsed.ends[index])  # type: ignore[arg-type]
        point_row.append(index)
        point_is_start.append(False)

    unique: dict[_Point, int] = {}
    uniq_points: list[_Point] = []
    uid_pids: list[list[int]] = []
    for pid, point in enumerate(points):
        uid = unique.get(point)
        if uid is None:
            uid = len(uniq_points)
            unique[point] = uid
            uniq_points.append(point)
            uid_pids.append([])
        uid_pids[uid].append(pid)
    uid_rows: list[list[int]] = [
        [point_row[pid] for pid in pids] for pids in uid_pids
    ]

    clusters: list[list[int]] = []
    point_cluster = [-1] * len(points)
    for members in _cluster_points(uniq_points, _brute=brute):
        group: list[int] = []
        for uid in members:
            group.extend(uid_pids[uid])
        for pid in group:
            point_cluster[pid] = len(clusters)
        clusters.append(group)

    pipe_cluster_start = [-1] * count
    pipe_cluster_end = [-1] * count
    for pid, row_index in enumerate(point_row):
        if point_is_start[pid]:
            pipe_cluster_start[row_index] = point_cluster[pid]
        else:
            pipe_cluster_end[row_index] = point_cluster[pid]
    pipe_index = [index for index in range(count) if not parsed.passthrough[index]]
    return _Graph(
        points, point_row, point_is_start, uniq_points, uid_pids, uid_rows, clusters,
        point_cluster, pipe_cluster_start, pipe_cluster_end, pipe_index,
    )


def _component_ids(graph: _Graph, parsed: _Parsed) -> tuple[list[int], list[int]]:
    """Cluster ids joined by pipes no longer than a near miss, per cluster and per point."""
    component = list(range(len(graph.clusters)))

    def link(node: int) -> int:
        while component[node] != node:
            component[node] = component[component[node]]
            node = component[node]
        return node

    for index in graph.pipe_index:
        first, last = graph.pipe_cluster_start[index], graph.pipe_cluster_end[index]
        if math.dist(parsed.starts[index], parsed.ends[index]) > _NEAR_MISS_M + 1e-12:  # type: ignore[arg-type]
            continue
        first, last = link(first), link(last)
        if first != last:
            component[first] = last
    comp_id = [link(cid) for cid in range(len(graph.clusters))]
    cluster_comp = [
        comp_id[graph.point_cluster[graph.uid_pids[uid][0]]]
        for uid in range(len(graph.uniq_points))
    ]
    return comp_id, cluster_comp


def _nearest_foreign(
    uid: int,
    graph: _Graph,
    comp_id: Sequence[int],
    cluster_comp: Sequence[int],
    grids: tuple[_Cells, _Cells],
    brute: bool,
) -> tuple[float, int]:
    """Distance and id of the closest point outside this point's cluster and component."""
    coarse, scan = grids
    uniq_points = graph.uniq_points
    point = uniq_points[uid]
    own_cluster = graph.point_cluster[graph.uid_pids[uid][0]]
    own_comp = comp_id[own_cluster]
    best: tuple[float, int] = (math.inf, -1)

    def consider(oids: Sequence[int], best: tuple[float, int]) -> tuple[float, int]:
        for oid in oids:
            if graph.point_cluster[graph.uid_pids[oid][0]] == own_cluster:
                continue
            if cluster_comp[oid] == own_comp:
                continue
            distance = math.dist(point, uniq_points[oid])
            if (distance, oid) < best:
                best = (distance, oid)
        return best

    if brute:
        return consider([other for other in range(len(uniq_points)) if other != uid], best)
    key = _cell_key(point)
    oids: list[int] = []
    for dx, dy, dz in _NEIGHBOURS:
        for oid in coarse.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
            if oid != uid:
                oids.append(oid)
    if len(oids) <= _SCAN_CUTOFF:
        return consider(oids, best)
    # Dense neighbourhood: ring expansion over the finer sub-grid evaluates
    # only nearby rings. After ring K every unevaluated point is at least K
    # cells away, so a best closer than that can never be tied or beaten and
    # the search stops. The (distance, oid) minimum is order-free, so the
    # result is exactly what the full scan finds.
    centre = _cell_key(point, _SCAN_CELL_M)
    ring = 0
    while True:
        ring_oids = []
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                for dz in range(-ring, ring + 1):
                    if max(abs(dx), abs(dy), abs(dz)) != ring:
                        continue
                    for oid in scan.get(
                        (centre[0] + dx, centre[1] + dy, centre[2] + dz),
                        (),
                    ):
                        if oid != uid:
                            ring_oids.append(oid)
        best = consider(ring_oids, best)
        if best[0] < ring * _SCAN_CELL_M:
            break
        ring += 1
        if (ring - 1) * _SCAN_CELL_M > _NEAR_MISS_M + 1e-12:
            break
    return best


def _near_miss_issues(graph: _Graph, parsed: _Parsed, brute: bool) -> list[ImportIssue]:
    """Refuse ends within 1 mm of another node, and near misses up to 0.1 m."""
    comp_id, cluster_comp = _component_ids(graph, parsed)
    coarse: _Cells = {}
    scan: _Cells = {}
    if not brute:
        for uid, point in enumerate(graph.uniq_points):
            coarse.setdefault(_cell_key(point), []).append(uid)
            scan.setdefault(_cell_key(point, _SCAN_CELL_M), []).append(uid)
    found: list[ImportIssue] = []
    for uid in range(len(graph.uniq_points)):
        distance, nearest = _nearest_foreign(
            uid, graph, comp_id, cluster_comp, (coarse, scan), brute)
        first = graph.uid_pids[uid][0]
        at_row = parsed.line_of[graph.point_row[first]]
        field = "x_start_m" if graph.point_is_start[first] else "x_m"
        other_line = parsed.line_of[graph.uid_rows[nearest][0]] if nearest >= 0 else None
        if distance <= _NODE_TOL_M + 1e-12:
            found.append(ImportIssue(
                at_row, field,
                f"this end is within 1 mm of row {other_line} yet joins another node; "
                "endpoints within 1 mm must coincide",
                "endpoints_ambiguous_node", {"other_row": other_line}))
        elif distance <= _NEAR_MISS_M + 1e-12:
            found.append(ImportIssue(
                at_row, field,
                f"this end is {distance * 1000.0:.2f} mm from row {other_line}; "
                "a near miss of 1 mm to 0.1 m is refused",
                "endpoints_near_miss",
                {"other_row": other_line, "distance_mm": round(distance * 1000.0, 3)}))
    return found


def _plan_valves(
    split_plan: _SplitPlan,
    work: Sequence[Mapping[str, object]],
    seg_starts: Sequence[_Point],
    seg_ends: Sequence[_Point],
    line_of: Sequence[int | None],
    issues: list[ImportIssue],
) -> tuple[dict[int, int], dict[int, float]]:
    """Which piece of each split row keeps its valve, and the valve's position on it.

    A split row's valve fields stay on exactly one piece: the piece
    containing the valve position (rescaled to that piece's span). A valve
    exactly on a split point cannot be placed, so the split is refused instead.
    """
    valve_keep: dict[int, int] = {}
    valve_rescaled: dict[int, float] = {}
    for target in sorted(split_plan):
        name = work[target].get("valve")
        if not (isinstance(name, str) and name.strip()):
            continue
        seg_length = math.dist(seg_starts[target], seg_ends[target])
        given = work[target].get("valve_position")
        position: float | None
        if given is None or (isinstance(given, str) and not given.strip()):
            position = 0.5
        else:
            try:
                position = float(given)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                position = None
        cuts_d = [0.0] + [item[0] for item in split_plan[target]] + [seg_length]
        if position is None:
            # Unreadable here; the importer names the bad value downstream.
            valve_keep[target] = 0
            continue
        at = position * seg_length
        if any(abs(at - cut) <= 1e-9 * max(seg_length, 1.0) for cut in cuts_d[1:-1]):
            issues.append(ImportIssue(
                line_of[target], "valve_position",
                "the valve sits exactly where another pipe joins; "
                "move valve_position off the split point",
                "endpoints_valve_at_split", {"position": round(position, 6)}))
            continue
        if at <= 0.0:
            keep = 0
        elif at >= seg_length:
            keep = len(cuts_d) - 2
        else:
            keep = len(cuts_d) - 2
            for piece in range(len(cuts_d) - 1):
                if cuts_d[piece] <= at <= cuts_d[piece + 1]:
                    keep = piece
                    break
        valve_keep[target] = keep
        piece_len = cuts_d[keep + 1] - cuts_d[keep]
        valve_rescaled[target] = (at - cuts_d[keep]) / piece_len if piece_len > 0 else position
    return valve_keep, valve_rescaled


def _apply_splits(
    split_plan: _SplitPlan,
    work: list[Mapping[str, object]],
    line_of: list[int | None],
    seg_starts: Sequence[_Point],
    seg_ends: Sequence[_Point],
    valves: tuple[dict[int, int], dict[int, float]],
) -> list[dict[str, object]]:
    """Cut each touched row into pieces, in `work` and `line_of`; return the cut points."""
    valve_keep, valve_rescaled = valves
    split_rows: list[dict[str, object]] = []
    for target in sorted(split_plan):
        kept = split_plan[target]
        base = dict(work[target])
        base.pop("length_m", None)
        base.pop("elevation_m", None)
        ax, ay, az = seg_starts[target]
        cuts = [(ax, ay, az)]
        cuts.extend((item[1], item[2], item[3]) for item in kept)
        cuts.append(seg_ends[target])
        keep = valve_keep.get(target)
        for piece in range(len(cuts) - 1):
            # Every piece starts from a pristine snapshot: popping
            # valve keys on piece 0 must not strip later pieces.
            part = dict(base)
            part["x_start_m"], part["y_start_m"], part["z_start_m"] = cuts[piece]
            part["x_m"], part["y_m"], part["z_m"] = cuts[piece + 1]
            if keep is not None:
                if piece != keep:
                    for key in ("valve", "valve_schedule", "valve_position",
                                "valve_diameter_m"):
                        part.pop(key, None)
                elif target in valve_rescaled:
                    part["valve_position"] = valve_rescaled[target]
            if piece:
                line_of.append(line_of[target])
                work.append(part)
            else:
                work[target] = part
        for _, qx, qy, qz in kept:
            split_rows.append({"line": line_of[target], "at": [qx, qy, qz]})
    return split_rows


def _parallel_and_loop_issues(graph: _Graph, line_of: Sequence[int | None]) -> list[ImportIssue]:
    found: list[ImportIssue] = []
    pair_rows: dict[tuple[int, int], list[int]] = {}
    for index in graph.pipe_index:
        key = tuple(sorted((graph.pipe_cluster_start[index], graph.pipe_cluster_end[index])))
        pair_rows.setdefault(key, []).append(index)  # type: ignore[arg-type]
    for key, members in pair_rows.items():
        if key[0] != key[1] and len(members) > 1:
            first = line_of[members[0]]
            for other in members[1:]:
                found.append(ImportIssue(
                    line_of[other], "x_m",
                    f"two pipes share both ends with row {first}; parallel pipes are refused",
                    "endpoints_parallel_pipes", {"other_row": first}))
    for index in graph.pipe_index:
        if graph.pipe_cluster_start[index] == graph.pipe_cluster_end[index]:
            found.append(ImportIssue(
                line_of[index], "x_m",
                "a pipe ends where it starts (x_m, y_m, z_m); loops are refused",
                "endpoints_self_loop", {}))
    return found


def _cycle_issues(graph: _Graph, line_of: Sequence[int | None]) -> list[ImportIssue]:
    found: list[ImportIssue] = []
    parent = list(range(len(graph.clusters)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for index in graph.pipe_index:
        node_a = graph.pipe_cluster_start[index]
        node_b = graph.pipe_cluster_end[index]
        root_a, root_b = find(node_a), find(node_b)
        if root_a == root_b:
            found.append(ImportIssue(
                line_of[index], "x_m",
                "this pipe closes a loop; loops are refused",
                "endpoints_cycle", {}))
        else:
            parent[root_a] = root_b
    return found


def _degree_issues(
    graph: _Graph, line_of: Sequence[int | None], issues: list[ImportIssue],
) -> tuple[dict[int, list[int]], dict[int, list[int]], dict[int, int]]:
    """Pipes in and out of each node, node degrees, and issues for bad chain nodes or junctions."""
    clusters = graph.clusters
    incoming: dict[int, list[int]] = {cid: [] for cid in range(len(clusters))}
    outgoing: dict[int, list[int]] = {cid: [] for cid in range(len(clusters))}
    for index in graph.pipe_index:
        outgoing[graph.pipe_cluster_start[index]].append(index)
        incoming[graph.pipe_cluster_end[index]].append(index)
    degree = {
        cid: len(incoming[cid]) + len(outgoing[cid]) for cid in range(len(clusters))
    }
    for cid in range(len(clusters)):
        total = degree[cid]
        if total == 0:
            continue
        ins, outs = len(incoming[cid]), len(outgoing[cid])
        if total == 1:
            continue
        if total == 2:
            if (ins, outs) != (1, 1):
                for index in incoming[cid] + outgoing[cid]:
                    at = "start" if graph.pipe_cluster_start[index] == cid else "end"
                    issues.append(ImportIssue(
                        line_of[index], "x_m",
                        "a chain node needs one pipe in and one out; "
                        f"it has {ins} in and {outs} out",
                        "endpoints_chain_orientation",
                        {"incoming": ins, "outgoing": outs, "at": at}))
        else:
            if min(ins, outs) != 1 or total > 7:
                for index in incoming[cid] + outgoing[cid]:
                    issues.append(ImportIssue(
                        line_of[index], "from_node",
                        "a junction needs exactly one flowpath on one side and 2-7 in all; "
                        f"it has {ins} in and {outs} out",
                        "endpoints_junction_degree",
                        {"incoming": ins, "outgoing": outs}))
    return incoming, outgoing, degree


def _build_chains(
    graph: _Graph,
    incoming: Mapping[int, list[int]],
    outgoing: Mapping[int, list[int]],
    degree: Mapping[int, int],
) -> list[list[int]]:
    """Pipes joined through two-pipe chain nodes, in the order of their first input row."""
    incoming_one: dict[int, int] = {}
    outgoing_one: dict[int, int] = {}
    for cid in range(len(graph.clusters)):
        if degree.get(cid) == 2 and len(incoming[cid]) == 1 and len(outgoing[cid]) == 1:
            incoming_one[cid] = incoming[cid][0]
            outgoing_one[cid] = outgoing[cid][0]
    visited: set[int] = set()
    chains: list[list[int]] = []
    for index in graph.pipe_index:
        if index in visited:
            continue
        chain = [index]
        visited.add(index)
        start_cid = graph.pipe_cluster_start[index]
        while start_cid in incoming_one:
            prev = incoming_one[start_cid]
            if prev in visited:
                break
            chain.append(prev)
            visited.add(prev)
            start_cid = graph.pipe_cluster_start[prev]
        chain.reverse()
        end_cid = graph.pipe_cluster_end[chain[-1]]
        while end_cid in outgoing_one:
            nxt = outgoing_one[end_cid]
            if nxt in visited:
                break
            chain.append(nxt)
            visited.add(nxt)
            end_cid = graph.pipe_cluster_end[nxt]
        chains.append(chain)
    rank = {index: position for position, index in enumerate(graph.pipe_index)}
    chains.sort(key=lambda chain: min(rank[i] for i in chain))
    return chains


def _assemble_rows(
    parsed: _Parsed,
    graph: _Graph,
    chains: Sequence[Sequence[int]],
    degree: Mapping[int, int],
    vertical_axis: str,
    roughness_m: float | None,
) -> tuple[list[dict[str, object]], list[int | None], list[dict[str, object]], dict[int, str]]:
    """Flowpath rows with END/J node names; also row lines, merged chains and END names."""
    rows, line_of = parsed.rows, parsed.line_of
    end_name: dict[int, str] = {}
    junction_name: dict[int, str] = {}
    for chain in chains:
        for cid in (graph.pipe_cluster_start[chain[0]], graph.pipe_cluster_end[chain[-1]]):
            if degree[cid] == 1 and cid not in end_name:
                end_name[cid] = f"END_{len(end_name) + 1:03d}"
            elif degree[cid] >= 3 and cid not in junction_name:
                junction_name[cid] = f"J_{len(junction_name) + 1:03d}"

    def node_name(cid: int) -> str:
        if cid in end_name:
            return end_name[cid]
        return junction_name[cid]

    out: list[dict[str, object]] = []
    out_lines: list[int | None] = []
    merged_rows: list[dict[str, object]] = []
    for number, chain in enumerate(chains, start=1):
        flowpath = f"FP_{number:03d}"
        start_cid = graph.pipe_cluster_start[chain[0]]
        end_cid = graph.pipe_cluster_end[chain[-1]]
        from_node, to_node = node_name(start_cid), node_name(end_cid)
        if len(chain) > 1:
            merged_rows.append({
                "flowpath": flowpath,
                "rows": [line_of[i] for i in chain[:_MAX_MERGED_ROWS]],
                "total": len(chain),
            })
        for position, index in enumerate(chain):
            row = dict(rows[index])
            for key in ("flowpath", "from_node", "to_node", "x_m", "y_m", "z_m",
                        "x_start_m", "y_start_m", "z_start_m", "length_m", "elevation_m"):
                row.pop(key, None)
            if "roughness_m" not in row or row["roughness_m"] is None:
                if roughness_m is not None:
                    row["roughness_m"] = roughness_m
            start_out = _reorder(parsed.starts[index], vertical_axis)  # type: ignore[arg-type]
            end_out = _reorder(parsed.ends[index], vertical_axis)  # type: ignore[arg-type]
            row["flowpath"] = flowpath
            row["from_node"] = from_node
            row["to_node"] = to_node
            if not row.get("pipe"):
                row["pipe"] = f"P_{line_of[index]:03d}"
            row["x_m"], row["y_m"], row["z_m"] = end_out
            if position == 0:
                row["x_start_m"], row["y_start_m"], row["z_start_m"] = start_out
            out.append(row)
            out_lines.append(line_of[index])
    for index in range(len(rows)):
        if parsed.passthrough[index]:
            out.append(dict(rows[index]))
            out_lines.append(line_of[index])
    return out, out_lines, merged_rows, end_name


def _summary(
    parsed: _Parsed,
    graph: _Graph,
    chains: Sequence[Sequence[int]],
    degree: Mapping[int, int],
    assembled: tuple[list[int | None], list[dict[str, object]], dict[int, str]],
    vertical_axis: str,
    total_in: int,
    skipped: bool,
) -> dict[str, object]:
    out_lines, merged_rows, end_name = assembled
    ends_list: list[dict[str, object]] = []
    for cid in sorted(end_name, key=lambda cid: int(end_name[cid].split("_")[1])):
        pid = graph.clusters[cid][0]
        coords = graph.points[pid]
        ends_list.append(
            {"name": end_name[cid], "x_m": coords[0], "y_m": coords[1], "z_m": coords[2]})
    junctions = sum(1 for cid in degree if degree[cid] >= 3)
    return {
        "vertical_axis": vertical_axis,
        "pipes": len(graph.pipe_index),
        "input_rows": total_in,
        "nodes": len(graph.clusters),
        "junctions": junctions,
        "ends": ends_list[:_MAX_ENDS],
        "ends_total": len(ends_list),
        "flowpaths": len(chains),
        "merged_pipes": len(graph.pipe_index) - len(chains),
        "merged_rows": merged_rows[:_MAX_MERGED],
        "merged_rows_total": len(merged_rows),
        "split_rows": [],
        "split_skipped": skipped,
        "row_lines": out_lines,
    }


def rows_from_endpoints(
    rows: Sequence[Mapping[str, object]],
    *,
    vertical_axis: str,
    roughness_m: float | None = None,
    lines: Sequence[int | None] | None = None,
    _brute: bool = False,
    _depth: int = 0,
    _input_rows: int | None = None,
) -> _Result:
    """Turn endpoint rows into coordinate rows for ``build_case_spec``."""
    roughness_m = _checked_roughness(vertical_axis, roughness_m)
    count = len(rows)
    total_in = count if _input_rows is None else _input_rows
    if lines is None:
        line_of = [index + 1 for index in range(count)]
    else:
        if len(lines) != count:
            raise ValueError("lines must match rows")
        line_of = list(lines)

    issues: list[ImportIssue] = []
    skipped = False

    def refuse(extra: Mapping[str, object]) -> _Result:
        summary: dict[str, object] = {"vertical_axis": vertical_axis, "pipes": count}
        summary.update(extra)
        summary.setdefault("split_skipped", skipped)
        return [], tuple(issues), summary

    parsed = _parse_rows(rows, line_of, vertical_axis, issues)
    if issues:
        return refuse(
            {"nodes": 0, "junctions": 0, "flowpaths": 0, "merged_pipes": 0})

    work = list(rows)
    seg_starts, seg_ends, split_plan, skipped = _find_splits(parsed)
    graph = _build_graph(parsed, _brute)
    nodes = len(graph.clusters)
    refused = {"nodes": nodes, "junctions": 0, "flowpaths": 0, "merged_pipes": 0}

    issues.extend(_near_miss_issues(graph, parsed, _brute))
    if issues:
        return refuse(refused)

    valves = _plan_valves(split_plan, work, seg_starts, seg_ends, line_of, issues)
    if issues:
        return refuse(refused)

    if split_plan and _depth >= _MAX_SPLIT_DEPTH:
        first = line_of[sorted(split_plan)[0]]
        issues.append(ImportIssue(
            first, "x_m",
            "splitting needs more rounds than allowed; simplify the table",
            "endpoints_split_recursion", {}))
        return refuse(refused)

    if split_plan:
        split_rows = _apply_splits(split_plan, work, line_of, seg_starts, seg_ends, valves)
        sub_out, sub_issues, sub_summary = rows_from_endpoints(
            work,
            vertical_axis=vertical_axis,
            roughness_m=roughness_m,
            lines=line_of,
            _brute=_brute,
            _depth=_depth + 1,
            _input_rows=total_in,
        )
        sub_summary["split_rows"] = split_rows + list(sub_summary.get("split_rows", []))
        if skipped:
            sub_summary["split_skipped"] = True
        return sub_out, sub_issues, sub_summary

    issues.extend(_parallel_and_loop_issues(graph, line_of))
    if issues:
        return refuse(refused)
    issues.extend(_cycle_issues(graph, line_of))
    if issues:
        return refuse(refused)

    incoming, outgoing, degree = _degree_issues(graph, line_of, issues)
    if issues:
        return refuse({
            "nodes": nodes, "junctions": sum(1 for cid in degree if degree[cid] >= 3),
            "flowpaths": 0, "merged_pipes": 0})

    chains = _build_chains(graph, incoming, outgoing, degree)
    out, out_lines, merged_rows, end_name = _assemble_rows(
        parsed, graph, chains, degree, vertical_axis, roughness_m)
    summary = _summary(
        parsed, graph, chains, degree, (out_lines, merged_rows, end_name),
        vertical_axis, total_in, skipped)
    return out, (), summary
