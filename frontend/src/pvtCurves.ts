import { niceTicks, ticksWithin } from './trendGeometry.mjs';

/** Pure geometry for the .tab curve views: one property against temperature, one line per pressure,
 *  and the bubble/dew envelope in pressure-temperature. No React, no DOM. */

export const CURVE_VIEW = { width: 640, height: 360, left: 64, right: 16, top: 16, bottom: 48 } as const;
export const MAX_CURVE_LINES = 7;
/** Lines after the first four also get a dash, so colour is never the only channel. */
const DASHES = ['', '', '', '', '7 3', '2 3', '8 3 2 3'] as const;

export interface Tick { value: number; label: string; pos: number }
export interface CurveLine {
  pressureIndex: number;
  pressurePa: number;
  /** CSS custom property that holds the stroke colour, e.g. `--pipe-3`. */
  colorVar: string;
  dash: string;
  d: string;
  /** Number of finite points; zero means the line has nothing to draw. */
  points: number;
}
export interface CurveChart {
  lines: CurveLine[];
  xTicks: Tick[];
  yTicks: Tick[];
  plot: { left: number; right: number; top: number; bottom: number };
}

/** Evenly spaced row indices, at most `limit`, always keeping the first and last row. */
export function pickRows(count: number, limit = MAX_CURVE_LINES): number[] {
  if (count <= 0) return [];
  if (count <= limit) return Array.from({ length: count }, (_, i) => i);
  const step = (count - 1) / (limit - 1);
  return [...new Set(Array.from({ length: limit }, (_, i) => Math.round(i * step)))].sort((a, b) => a - b);
}

export function lineStyle(order: number): { colorVar: string; dash: string } {
  return { colorVar: `--pipe-${(order % 7) + 1}`, dash: DASHES[order % 7] };
}

const num = (value: number): number => Number(value.toFixed(2));
const finite = (value: number | null | undefined): value is number => typeof value === 'number' && Number.isFinite(value);

function domain(values: number[]): [number, number] {
  if (values.length === 0) return [0, 1];
  const low = Math.min(...values);
  const high = Math.max(...values);
  if (low !== high) return [low, high];
  const pad = Math.abs(low) * 0.05 || 1;
  return [low - pad, high + pad];
}

function axis(low: number, high: number, from: number, to: number, label: (v: number) => string, ticks = 5): Tick[] {
  const span = high - low;
  return ticksWithin(niceTicks(low, high, ticks), low, high)
    .map((value) => ({ value, label: label(value), pos: num(from + ((value - low) / span) * (to - from)) }));
}

const tickLabel = (value: number): string => Number(value.toPrecision(4)).toString();

/** The chosen property against temperature, one polyline per sampled pressure. A missing value breaks the line. */
export function buildCurveChart(
  pressures: readonly number[],
  temperatures: readonly number[],
  values: readonly (readonly (number | null)[])[],
  maxLines = MAX_CURVE_LINES,
): CurveChart {
  const { width, height, left, right, top, bottom } = CURVE_VIEW;
  const plot = { left, right: width - right, top, bottom: height - bottom };
  const rows = pickRows(Math.min(pressures.length, values.length), maxLines);
  const [x0, x1] = domain(temperatures.filter(finite));
  const [y0, y1] = domain(rows.flatMap((row) => values[row].filter(finite)));
  const sx = (t: number) => num(plot.left + ((t - x0) / (x1 - x0)) * (plot.right - plot.left));
  const sy = (v: number) => num(plot.bottom - ((v - y0) / (y1 - y0)) * (plot.bottom - plot.top));
  const lines = rows.map((row, order): CurveLine => {
    let d = '';
    let points = 0;
    let pen = false;
    values[row].forEach((value, col) => {
      const t = temperatures[col];
      if (!finite(value) || !finite(t)) { pen = false; return; }
      d += `${pen ? 'L' : 'M'}${sx(t)} ${sy(value)}`;
      pen = true;
      points += 1;
    });
    return { pressureIndex: row, pressurePa: pressures[row], ...lineStyle(order), d, points };
  });
  return {
    lines,
    xTicks: axis(x0, x1, plot.left, plot.right, tickLabel),
    yTicks: axis(y0, y1, plot.bottom, plot.top, tickLabel),
    plot,
  };
}

export type EnvelopePoint = [number | null, number | null];
export interface TabEnvelopeData {
  bubble: EnvelopePoint[];
  dew: EnvelopePoint[];
  critical: { p_pa: number; t_c: number } | null;
}
export interface EnvelopeChart {
  bubble: string;
  dew: string;
  critical: { x: number; y: number } | null;
  xTicks: Tick[];
  yTicks: Tick[];
  plot: CurveChart['plot'];
}

export function hasEnvelope(envelope: TabEnvelopeData | null | undefined): envelope is TabEnvelopeData {
  if (!envelope) return false;
  const usable = (curve: EnvelopePoint[]) => curve.filter(([p, t]) => finite(p) && finite(t)).length >= 2;
  return usable(envelope.bubble) || usable(envelope.dew) || envelope.critical !== null;
}

/** Bubble and dew curves and the critical point in P (bar, vertical) against T (°C, horizontal). */
export function buildEnvelopeChart(envelope: TabEnvelopeData): EnvelopeChart {
  const { width, height, left, right, top, bottom } = CURVE_VIEW;
  const plot = { left, right: width - right, top, bottom: height - bottom };
  const all: [number, number][] = [...envelope.bubble, ...envelope.dew]
    .filter((point): point is [number, number] => finite(point[0]) && finite(point[1]))
    .map(([p, t]) => [p / 1e5, t]);
  if (envelope.critical) all.push([envelope.critical.p_pa / 1e5, envelope.critical.t_c]);
  const [x0, x1] = domain(all.map(([, t]) => t));
  const [y0, y1] = domain(all.map(([p]) => p));
  const sx = (t: number) => num(plot.left + ((t - x0) / (x1 - x0)) * (plot.right - plot.left));
  const sy = (p: number) => num(plot.bottom - ((p - y0) / (y1 - y0)) * (plot.bottom - plot.top));
  const path = (curve: EnvelopePoint[]) => {
    let d = '';
    let pen = false;
    for (const [p, t] of curve) {
      if (!finite(p) || !finite(t)) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${sx(t)} ${sy(p / 1e5)}`;
      pen = true;
    }
    return d;
  };
  return {
    bubble: path(envelope.bubble),
    dew: path(envelope.dew),
    critical: envelope.critical ? { x: sx(envelope.critical.t_c), y: sy(envelope.critical.p_pa / 1e5) } : null,
    xTicks: axis(x0, x1, plot.left, plot.right, tickLabel),
    yTicks: axis(y0, y1, plot.bottom, plot.top, tickLabel),
    plot,
  };
}
