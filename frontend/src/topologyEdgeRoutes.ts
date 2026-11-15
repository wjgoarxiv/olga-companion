type EdgePair = {
  readonly source: string;
  readonly target: string;
};

type EdgeRouteInput = {
  readonly x1: number;
  readonly y1: number;
  readonly x2: number;
  readonly y2: number;
  readonly offset: number;
};

type EdgeRoute = {
  readonly path: string;
  readonly labelX: number;
  readonly labelY: number;
  readonly offset: number;
};

type LabelBounds = {
  readonly x: number;
  readonly y: number;
  readonly width: number;
};

const PARALLEL_EDGE_SPACING = 24;
const LABEL_HORIZONTAL_GAP = 4;
const LABEL_VERTICAL_LANE = 20;
/** A cubic Bezier with both control points shifted by c peaks at 0.75 * c, so scale to make the drawn curve reach the offset. */
const CONTROL_SCALE = 4 / 3;
const LABEL_ABOVE_CLEARANCE = 8;
const LABEL_BELOW_CLEARANCE = 20;
const LABEL_SINGLE_LIFT = 4;

export function parallelEdgeOffsets(edges: readonly EdgePair[]): readonly number[] {
  const totals = new Map<string, number>();
  for (const edge of edges) {
    const key = `${edge.source}\u0000${edge.target}`;
    totals.set(key, (totals.get(key) ?? 0) + 1);
  }
  const seen = new Map<string, number>();
  return edges.map((edge) => {
    const key = `${edge.source}\u0000${edge.target}`;
    const ordinal = seen.get(key) ?? 0;
    seen.set(key, ordinal + 1);
    const total = totals.get(key) ?? 1;
    return (ordinal - (total - 1) / 2) * PARALLEL_EDGE_SPACING;
  });
}

export function routeParallelEdge(input: EdgeRouteInput): EdgeRoute {
  const middleX = (input.x1 + input.x2) / 2;
  const controlY1 = input.y1 + input.offset * CONTROL_SCALE;
  const controlY2 = input.y2 + input.offset * CONTROL_SCALE;
  const apexY = (input.y1 + input.y2) / 2 + input.offset;
  // The upper curve of a parallel pair labels itself above, the lower one below,
  // so each name sits beside its own stroke instead of between the two.
  const labelY = input.offset < 0
    ? apexY - LABEL_ABOVE_CLEARANCE
    : input.offset > 0 ? apexY + LABEL_BELOW_CLEARANCE : apexY - LABEL_SINGLE_LIFT;
  return {
    path: `M${input.x1},${input.y1} C${middleX},${controlY1} ${middleX},${controlY2} ${input.x2},${input.y2}`,
    labelX: middleX,
    labelY,
    offset: input.offset,
  };
}

export function resolveLabelCollisions(labels: readonly LabelBounds[]): readonly LabelBounds[] {
  const placed: LabelBounds[] = [];
  for (const label of labels) {
    let candidate = label;
    for (let step = 0; step <= placed.length; step += 1) {
      const lane = step === 0 ? 0 : Math.ceil(step / 2) * (step % 2 ? -1 : 1);
      candidate = { ...label, y: label.y + lane * LABEL_VERTICAL_LANE };
      const overlaps = placed.some((other) => (
        Math.abs(candidate.x - other.x) < (candidate.width + other.width) / 2 + LABEL_HORIZONTAL_GAP
        && Math.abs(candidate.y - other.y) < LABEL_VERTICAL_LANE
      ));
      if (!overlaps) break;
    }
    placed.push(candidate);
  }
  return placed;
}
