"""Graded section lengths for one flowpath.

OLGA practice: every pipe has at least two sections and neighbouring sections stay
within a 0.5-2 length ratio, across pipe boundaries too. A short pipe next to a long
one therefore needs sections that grow gradually instead of a uniform split.

Sizes follow a field h(x) = min(target, seed + slope * distance-to-seed), where a seed
sits at every place that wants small sections (a short neighbouring pipe, a valve, a
refined flowpath end). Marching x -> x + h(x) keeps each step's ratio below the growth
factor, and a uniform rescale makes each pipe sum to its length exactly.

A valve inside a pipe is a hard breakpoint: the pipe is marched in spans between its
breakpoints, so a section edge sits exactly at the valve. A valve at the outlet of a pipe
that another pipe follows, or at a flowpath outlet into a junction, sits on that pipe's
last boundary. A valve at a flowpath's inlet, or its outlet into a boundary node, keeps
the nearest interior edge.

Refinement stops at a floor: half the flowpath's shortest pipe (or the refined size of a
maximum section, when that is smaller). OLGA's time step follows
the shortest section, so refining below that floor costs far more run time than it buys;
where the floor and the ratio rule disagree, the floor wins and the ratio is reported.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

MAX_RATIO = 2.0
# Growth per section inside a pipe, kept under MAX_RATIO so the final rescale and the
# pipe-boundary coupling still leave margin.
_GROWTH = 1.5
_MAX_COUPLING_PASSES = 200
# A guard against runaway marching; one case holds at most 10,000 sections in all.
_MAX_SECTIONS_PER_FLOWPATH = 10_000
# A valve closer than this to a pipe end counts as sitting on that end.
_EDGE_TOL_M = 1e-3


@dataclass(frozen=True)
class PipeRun:
    """One pipe of a flowpath, in flow order."""

    length_m: float
    # Fractions (0-1) along this pipe where a valve sits.
    valve_positions: tuple[float, ...] = ()


@dataclass(frozen=True)
class Segmentation:
    lengths_m: tuple[tuple[float, ...], ...]
    # One SECTIONBOUNDARY index (1-based) per valve, in the order given per pipe.
    valve_boundaries: tuple[tuple[int, ...], ...]
    worst_ratio: float
    warnings: tuple[str, ...] = field(default=())


def _march(
    length: float, target: float, seeds: Sequence[tuple[float, float]], floor: float, growth: float,
) -> list[float]:
    """Sections for one pipe from the size field; seeds are (position, size) pairs."""

    def size(x: float) -> float:
        best = target
        for position, seed_size in seeds:
            best = min(best, seed_size + (growth - 1.0) * abs(x - position))
        return max(best, floor, 1e-9)

    points = [0.0]
    while points[-1] < length:
        points.append(points[-1] + size(points[-1] + 0.5 * size(points[-1])))
    cells = [right - left for left, right in zip(points, points[1:])]
    overshoot = points[-1] - length
    if len(cells) > 1 and overshoot > 0.5 * cells[-1]:
        # Dropping the last cell stretches the rest; keep it when that would pass the target.
        stretched = length / math.fsum(cells[:-1])
        if max(cells[:-1]) * stretched <= target * (1 + 1e-12):
            cells.pop()
    scale = length / math.fsum(cells)
    return [cell * scale for cell in cells]


def _even(length: float, count: int) -> list[float]:
    return [length / count] * count


def _breakpoints(run: PipeRun) -> list[float]:
    """Valve distances (m) strictly inside the pipe, each a place a section edge must sit."""
    points: list[float] = []
    for distance in sorted(fraction * run.length_m for fraction in run.valve_positions):
        if _EDGE_TOL_M < distance < run.length_m - _EDGE_TOL_M and (
            not points or distance - points[-1] > _EDGE_TOL_M
        ):
            points.append(distance)
    return points


def _split_to(cells: list[float], count: int) -> list[float]:
    """Halve the largest section until there are `count`; every existing edge stays."""
    cells = list(cells)
    while len(cells) < count:
        index = cells.index(max(cells))
        cells[index:index + 1] = [cells[index] / 2] * 2
    return cells


def _smooth(cells: list[float], max_ratio: float) -> list[float]:
    """Halve the larger section of any neighbouring pair beyond `max_ratio` (every edge stays).

    Halving a pair settles only for a limit above sqrt(2), so the limit is `max_ratio`
    held between 1.5 and 2 (the mesh then does not change for a looser `max_ratio`); a
    tighter request keeps its jump, which the caller's worst-ratio warning reports.
    """
    limit = min(max(max_ratio, _GROWTH), MAX_RATIO) + 1e-9
    cells = list(cells)
    i = 0
    while i < len(cells) - 1 and len(cells) < _MAX_SECTIONS_PER_FLOWPATH:
        if _ratio(cells[i], cells[i + 1]) <= limit:
            i += 1
            continue
        j = i if cells[i] > cells[i + 1] else i + 1
        cells[j:j + 1] = [cells[j] / 2] * 2
        i = max(i - 1, 0)
    return cells


def _pipe_sections(
    run: PipeRun, target: float, start_seed: float | None, end_seed: float | None,
    valve_seed: float, min_sections: int, floor: float, growth: float, first_span_min: int = 1,
    max_ratio: float = MAX_RATIO,
) -> list[float]:
    seeds: list[tuple[float, float]] = []
    if start_seed is not None:
        seeds.append((0.0, start_seed))
    if end_seed is not None:
        seeds.append((run.length_m, end_seed))
    seeds.extend((fraction * run.length_m, valve_seed) for fraction in run.valve_positions)
    breakpoints = _breakpoints(run)
    if breakpoints:
        return _spanned_sections(run, breakpoints, seeds, target, min_sections, floor, growth, first_span_min, max_ratio)
    cells = _march(run.length_m, target, seeds, floor, growth) if seeds else _even(
        run.length_m, max(min_sections, math.ceil(run.length_m / target - 1e-9))
    )
    if len(cells) < min_sections:
        cells = _even(run.length_m, min_sections)
    if min(cells) < floor * (1 - 1e-9):
        # Fitting the graded cells to the pipe squeezed one under the floor; split evenly instead.
        cells = _even(run.length_m, max(min_sections, int(run.length_m / floor + 1e-9)))
    return cells


def _spanned_sections(
    run: PipeRun, breakpoints: Sequence[float], seeds: Sequence[tuple[float, float]], target: float,
    min_sections: int, floor: float, growth: float, first_span_min: int, max_ratio: float,
) -> list[float]:
    """March each span between valve breakpoints on its own, so every breakpoint stays an edge.

    Where two spans meet (or a span was split for the first boundary), the larger section
    is halved until the pair is within `max_ratio`; that can go below the floor, because a
    valve edge at its exact position outranks the floor (a span fitted to its length can
    also land a little under it).
    """
    edges = [0.0, *breakpoints, run.length_m]
    spans: list[list[float]] = []
    for left, right in zip(edges, edges[1:]):
        spans.append(_march(right - left, target, [(x - left, size) for x, size in seeds], floor, growth))
    if len(spans[0]) < first_span_min:
        spans[0] = _split_to(spans[0], first_span_min)
    cells = _smooth([cell for span in spans for cell in span], max_ratio)
    return _split_to(cells, min_sections) if len(cells) < min_sections else cells


def _ratio(left: float, right: float) -> float:
    return max(left, right) / min(left, right)


def segment_flowpath(
    pipes: Sequence[PipeRun],
    max_section_m: float,
    *,
    min_sections: int = 2,
    first_min_sections: int = 0,
    refine_start: bool = False,
    refine_end: bool = False,
    refine_factor: float = 0.5,
    max_ratio: float = MAX_RATIO,
    min_first_valve_boundary: int = 1,
    outlet_valve_on_end: bool = False,
) -> Segmentation:
    """Return graded section lengths for each pipe of one flowpath.

    `refine_start`/`refine_end` shrink the sections at a flowpath end that meets a
    junction; valves get a section boundary close to their position. Neighbouring
    sections stay within `max_ratio` (2.0 by default); a tighter ratio grades more
    finely where pipes of very different lengths meet. `first_min_sections` raises
    the minimum for the first pipe only (0 keeps `min_sections`); the importer
    asks for 3 on a valved first pipe after a junction, so the valve never sits
    on the pipe's end. A raised first-pipe target can fall below the flowpath
    floor, in which case that pipe falls back to an even split to hold its minimum.
    `min_first_valve_boundary` keeps a valve of the first pipe off its first
    boundaries (the importer passes 2 after a junction, where OLGA refuses a valve on
    the first one); a valve at a pipe's outlet is exempt.
    `outlet_valve_on_end` lets a valve at 1.0 of the last pipe take its last boundary;
    the importer passes it when the flowpath ends at a junction, which OLGA 2022 accepts.
    """
    if not pipes:
        raise ValueError("a flowpath needs at least one pipe")
    if not math.isfinite(max_section_m) or max_section_m <= 0 or min_sections < 1:
        raise ValueError("max_section_m must be a positive finite length and min_sections at least 1")
    if first_min_sections < 0:
        raise ValueError("first_min_sections cannot be negative")
    if min_first_valve_boundary < 1:
        raise ValueError("min_first_valve_boundary must be at least 1")
    if not math.isfinite(max_ratio) or max_ratio < 1.0:
        raise ValueError("max_ratio must be a finite length ratio of at least 1")
    if any(not math.isfinite(run.length_m) or run.length_m <= 0 for run in pipes):
        raise ValueError("every pipe length must be positive and finite")
    needs = [max(min_sections, first_min_sections) if index == 0 else min_sections
             for index in range(len(pipes))]
    if sum(max(need, run.length_m / max_section_m) for need, run in zip(needs, pipes)) > _MAX_SECTIONS_PER_FLOWPATH:
        raise ValueError("this flowpath would need more sections than a case can hold")
    targets = [min(max_section_m, run.length_m / need) for run, need in zip(pipes, needs)]
    floor = min(min(run.length_m for run in pipes) / min_sections, max_section_m * refine_factor)
    starts: list[float | None] = [None] * len(pipes)
    ends: list[float | None] = [None] * len(pipes)
    if refine_start:
        starts[0] = targets[0] * refine_factor
    if refine_end:
        ends[-1] = targets[-1] * refine_factor
    valve_seeds = [target * refine_factor for target in targets]
    # The growth factor is the ratio bound (at most the historical 1.5): it sets the
    # size-field slope inside a pipe and the neighbour-ratio target across pipes.
    # The default ratio keeps the historical factor, so default output is unchanged.
    growth = min(_GROWTH, max_ratio)

    floors = [floor] * len(pipes)

    def build(i: int) -> list[float]:
        return _pipe_sections(
            pipes[i], targets[i], starts[i], ends[i], valve_seeds[i], needs[i], floors[i], growth,
            min_first_valve_boundary if i == 0 else 1, max_ratio,
        )

    cells = [build(i) for i in range(len(pipes))]
    # Couple neighbouring pipes: the larger end section is seeded down to the smaller
    # one times the growth factor until every pipe boundary is within the ratio. Fitting
    # a pipe to its exact length can stretch its end section again, so a seed that is
    # already that small keeps shrinking until the boundary holds.

    def tightened(index: int, seed: float | None, wanted: float, small: float) -> float | None:
        # A valve edge can leave a section under the floor; its neighbour then follows it down.
        floors[index] = min(floors[index], small)
        if seed is not None and seed <= floors[index]:
            return None
        return max(floors[index], wanted if seed is None or seed > wanted else seed * 0.85)

    for _ in range(_MAX_COUPLING_PASSES):
        changed = False
        for i in range(len(pipes) - 1):
            last, first = cells[i][-1], cells[i + 1][0]
            if _ratio(last, first) <= growth:
                continue
            if last > first:
                seed = tightened(i, ends[i], first * growth, first)
                if seed is None:
                    continue
                ends[i] = seed
                cells[i] = build(i)
            else:
                seed = tightened(i + 1, starts[i + 1], last * growth, last)
                if seed is None:
                    continue
                starts[i + 1] = seed
                cells[i + 1] = build(i + 1)
            changed = True
        if not changed:
            break
    sequence = [cell for pipe_cells in cells for cell in pipe_cells]
    worst = max((_ratio(left, right) for left, right in zip(sequence, sequence[1:])), default=1.0)
    warnings = () if worst <= max_ratio + 1e-9 else (
        f"neighbouring sections differ by {worst:.2f}x after grading",
    )
    boundaries = tuple(
        tuple(
            _valve_boundary(pipe_cells, run, fraction,
                            last=index == len(pipes) - 1 and not outlet_valve_on_end,
                            first_min=min_first_valve_boundary if index == 0 else 1)
            for fraction in run.valve_positions
        )
        for index, (run, pipe_cells) in enumerate(zip(pipes, cells))
    )
    return Segmentation(tuple(tuple(item) for item in cells), boundaries, worst, warnings)


def _valve_boundary(cells: Sequence[float], run: PipeRun, fraction: float, last: bool, first_min: int) -> int:
    """SECTIONBOUNDARY of a valve: the pipe's last one for an outlet valve before another pipe,
    else the section edge nearest its position (exact for a valve inside the pipe)."""
    position = fraction * run.length_m
    if not last and position >= run.length_m - _EDGE_TOL_M:
        return len(cells)
    return max(_nearest_boundary(cells, position), min(first_min, len(cells) - 1))


def _nearest_boundary(cells: Sequence[float], position: float) -> int:
    """1-based SECTIONBOUNDARY index of the section edge closest to `position`."""
    edge, best, best_distance = 0.0, 1, math.inf
    for index, cell in enumerate(cells[:-1], start=1):
        edge += cell
        distance = abs(edge - position)
        if distance < best_distance:
            best, best_distance = index, distance
    return best


def junction_ratio_warnings(
    ends: Sequence[tuple[str, str, float]], max_ratio: float = MAX_RATIO
) -> list[str]:
    """Warn where the end sections meeting at one junction differ by more than the ratio.

    `ends` holds (junction, flowpath, end-section length) rows.
    """
    by_junction: dict[str, list[tuple[str, float]]] = {}
    for junction, flowpath, length in ends:
        by_junction.setdefault(junction, []).append((flowpath, length))
    warnings = []
    for junction, rows in sorted(by_junction.items()):
        lengths = [length for _, length in rows]
        ratio = max(lengths) / min(lengths)
        if ratio > max_ratio + 1e-9:
            warnings.append(f"sections meeting at {junction} differ by {ratio:.2f}x")
    return warnings
