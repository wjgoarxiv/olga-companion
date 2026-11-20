import type { TabEnvelopeData } from './pvtCurves.ts';

/** One property of a .tab as a pressure x temperature matrix (POST /api/fluids/tab-grid). */
export interface TabGrid {
  path: string;
  label: string;
  phase: string;
  format: 'standard' | 'legacy';
  properties: string[];
  column: string | null;
  pressures: number[];
  temperatures: number[];
  values: (number | null)[][] | null;
  downsampled: boolean;
  shape: [number, number];
  /** Bubble/dew curves and critical point in Pa and °C; empty lists when the file has none. */
  envelope?: TabEnvelopeData;
  /** Legacy tables only: one list of values per pressure, and the original index of each column. */
  points?: (number | null)[][];
  pointIndexes?: number[];
  unit?: string;
}

export const HEAT_LEVELS = 5;

/** Tint level 0..HEAT_LEVELS-1 for each cell; null for a missing value. A flat column is all level 0. */
export function heatLevels(values: (number | null)[][]): (number | null)[][] {
  const finite = values.flat().filter((value): value is number => value !== null);
  if (finite.length === 0) return values.map((row) => row.map(() => null));
  const low = Math.min(...finite);
  const span = Math.max(...finite) - low;
  return values.map((row) => row.map((value) => {
    if (value === null) return null;
    if (span === 0) return 0;
    return Math.min(HEAT_LEVELS - 1, Math.floor(((value - low) / span) * HEAT_LEVELS));
  }));
}

/** Pressure in bar for the row header; the file stores Pa. */
export function formatBar(pa: number): string {
  return Number((pa / 1e5).toPrecision(4)).toString();
}

/** A compact cell value: plain for ordinary magnitudes, exponent form otherwise. */
export function formatCell(value: number | null): string {
  if (value === null) return '–';
  const size = Math.abs(value);
  if (size !== 0 && (size < 1e-3 || size >= 1e6)) return value.toExponential(3);
  return Number(value.toPrecision(5)).toString();
}
