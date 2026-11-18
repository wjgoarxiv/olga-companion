// Lays out an example's drawing model (from the backend) as a small flow diagram:
// flow runs left to right, sources at the left, sinks at the right, and a pipe's own
// rise and fall bends its line so a riser goes up and a hilly line goes up and down.

export const DIAGRAM_WIDTH = 320;
const PAD_X = 22;
const ROW_H = 40;
const RISE_PX = 30;
const PAD_TOP = RISE_PX + 16;
const PAD_BOTTOM = 26;

function depths(model) {
  const incoming = new Map(model.nodes.map((n) => [n.id, []]));
  for (const e of model.edges) incoming.get(e.to)?.push(e.from);
  const memo = new Map();
  const visit = (id, seen) => {
    if (memo.has(id)) return memo.get(id);
    if (seen.has(id)) return 0;
    seen.add(id);
    const prev = incoming.get(id) ?? [];
    const d = prev.length ? Math.max(...prev.map((p) => visit(p, seen) + 1)) : 0;
    memo.set(id, d);
    return d;
  };
  for (const n of model.nodes) visit(n.id, new Set());
  // A source sits one column before the node it feeds, so a well that joins late starts late.
  for (const n of model.nodes) {
    if ((incoming.get(n.id) ?? []).length) continue;
    const next = model.edges.filter((e) => e.from === n.id).map((e) => memo.get(e.to) ?? 1);
    if (next.length) memo.set(n.id, Math.max(0, Math.min(...next) - 1));
  }
  return memo;
}

function profile(edge) {
  let total = 0;
  let rise = 0;
  const points = [{ t: 0, rise: 0 }];
  const ends = new Map();
  const length = edge.segments.reduce((sum, s) => sum + Math.max(0, s.length_m), 0);
  for (const s of edge.segments) {
    total += Math.max(0, s.length_m);
    rise += s.rise_m;
    const t = length > 0 ? total / length : 1;
    points.push({ t, rise });
    ends.set(s.id, t);
  }
  if (points.length === 1) points.push({ t: 1, rise: 0 });
  return { points, ends };
}

export function layoutDiagram(model) {
  const depth = depths(model);
  const maxDepth = Math.max(1, ...depth.values());
  const columns = new Map();
  for (const n of model.nodes) {
    const d = depth.get(n.id) ?? 0;
    columns.set(d, [...(columns.get(d) ?? []), n.id]);
  }
  const rows = Math.max(1, ...[...columns.values()].map((c) => c.length));
  const height = PAD_TOP + rows * ROW_H + PAD_BOTTOM - ROW_H / 2;
  const at = new Map();
  for (const [d, ids] of columns) {
    ids.forEach((id, i) => {
      const x = PAD_X + (d / maxDepth) * (DIAGRAM_WIDTH - 2 * PAD_X);
      const y = PAD_TOP + ((rows - ids.length) / 2 + i) * ROW_H;
      at.set(id, { x, y });
    });
  }

  const profiles = model.edges.map(profile);
  const maxRise = Math.max(0, ...profiles.flatMap((p) => p.points.map((q) => Math.abs(q.rise))));
  const scale = maxRise >= 5 ? RISE_PX / maxRise : 0;

  // A sink fed by one line sits where that line ends, so a riser really ends up high.
  const fedBy = new Map();
  for (const e of model.edges) fedBy.set(e.to, [...(fedBy.get(e.to) ?? []), e]);
  const kind = new Map(model.nodes.map((n) => [n.id, n.kind]));
  model.edges.forEach((e, i) => {
    if (kind.get(e.to) === 'sink' && fedBy.get(e.to).length === 1) {
      const last = profiles[i].points.at(-1);
      const from = at.get(e.from);
      at.set(e.to, { x: at.get(e.to).x, y: from.y - last.rise * scale });
    }
  });

  // Lines that join the same two nodes are drawn apart so each one stays visible.
  const pairs = new Map();
  model.edges.forEach((e, i) => pairs.set(`${e.from}>${e.to}`, [...(pairs.get(`${e.from}>${e.to}`) ?? []), i]));
  const paths = model.edges.map((e, i) => {
    const a = at.get(e.from);
    const b = at.get(e.to);
    const { points, ends } = profiles[i];
    const endRise = points.at(-1).rise * scale;
    const drift = b.y - a.y;
    const twins = pairs.get(`${e.from}>${e.to}`);
    const spread = twins.length > 1 ? (twins.indexOf(i) - (twins.length - 1) / 2) * 12 : 0;
    const inner = spread && points.length === 2 ? [points[0], { t: 0.12, rise: 0 }, { t: 0.88, rise: 0 }, points[1]] : points;
    const xy = inner.map((p, k) => [
      a.x + p.t * (b.x - a.x),
      // Bend by the pipe's own profile; whatever the profile does not explain is a straight drift.
      a.y - p.rise * scale + p.t * (drift + endRise) + (k > 0 && k < inner.length - 1 ? spread : 0),
    ]);
    const valves = e.valves.map((v) => {
      const t = ends.has(v.pipe) ? ends.get(v.pipe) : 0.5;
      const k = Math.min(xy.length - 1, Math.max(1, inner.findIndex((p) => p.t >= t)));
      return { x: xy[k][0], y: xy[k][1], scheduled: v.scheduled };
    });
    return { id: e.id, points: xy, valves };
  });

  // A label goes below its node when a line leaves the node upward, otherwise above it.
  const rising = new Set();
  paths.forEach((p, i) => {
    const e = model.edges[i];
    if (p.points[1][1] < p.points[0][1] - 1) rising.add(e.from);
    if (p.points.at(-2)[1] < p.points.at(-1)[1] - 1) rising.add(e.to);
  });
  const nodes = model.nodes.map((n) => ({ id: n.id, kind: n.kind, labelBelow: rising.has(n.id), ...at.get(n.id) }));
  const lowest = Math.max(...nodes.map((n) => n.y), ...paths.flatMap((p) => p.points.map((q) => q[1])));
  const highest = Math.min(...nodes.map((n) => n.y), ...paths.flatMap((p) => p.points.map((q) => q[1])));
  // Room above the highest point for the node labels, which sit above their node.
  const shift = highest < 34 ? 34 - highest : 0;
  const shifted = (y) => y + shift;
  return {
    width: DIAGRAM_WIDTH,
    height: Math.max(height, lowest + shift + PAD_BOTTOM),
    nodes: nodes.map((n) => ({ ...n, y: shifted(n.y) })),
    paths: paths.map((p) => ({
      ...p,
      points: p.points.map(([x, y]) => [x, shifted(y)]),
      valves: p.valves.map((v) => ({ ...v, y: shifted(v.y) })),
    })),
    ground: model.thermal ? shifted(lowest) + 12 : null,
  };
}
