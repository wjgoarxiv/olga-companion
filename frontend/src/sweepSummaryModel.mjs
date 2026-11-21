/** Sweep summary order and change text (0.1.20 row 8). The change is the server's: end value minus
    the base case's end value, in the same unit; a missing change stays missing. */

import { toDisplayDelta } from './displayQuantity.mjs';

export const SUMMARY_VARIABLES = Object.freeze(['PT', 'TM', 'HOL', 'LIQC']);

/** 'case' keeps case order; a variable sorts by the size of its change, largest first, cases without one last. */
export function sortSummaryRows(rows, sortBy) {
  if (!SUMMARY_VARIABLES.includes(sortBy)) return [...rows];
  const change = (row) => row.outputs?.[sortBy]?.change;
  return [...rows].sort((a, b) => {
    const left = change(a);
    const right = change(b);
    if (typeof left !== 'number') return typeof right === 'number' ? 1 : a.index - b.index;
    if (typeof right !== 'number') return -1;
    return Math.abs(right) - Math.abs(left) || a.index - b.index;
  });
}

/** "+30 bara" / "−1 bar" in the unit the app shows (Pa → bar, K → °C); null for the base case itself or
    when there is no change. */
export function formatChange(cell, isBase) {
  if (isBase || !cell || typeof cell.change !== 'number') return null;
  const shown = toDisplayDelta(cell.change, cell.unit);
  const size = Number(Math.abs(shown.value).toPrecision(6));
  const sign = cell.change > 0 ? '+' : cell.change < 0 ? '−' : '±';
  return `${sign}${size}${shown.unit ? ` ${shown.unit}` : ''}`;
}
