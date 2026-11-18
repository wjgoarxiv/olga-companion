import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { formatBar, formatCell, heatLevels, HEAT_LEVELS } from '../src/pvtGrid.ts';

// Owner report 2026-11-16: clicking a .tab said the table was readable but showed only
// the header summary text, never a single value.
test('heat levels span the column from lowest to highest and keep gaps empty', () => {
  assert.deepEqual(heatLevels([[1, 0.9], [100, 95]]), [[0, 0], [HEAT_LEVELS - 1, HEAT_LEVELS - 1]]);
  assert.deepEqual(heatLevels([[5, null], [5, 5]]), [[0, null], [0, 0]]);
  assert.deepEqual(heatLevels([[null]]), [[null]]);
});

test('row headers are bar and cells stay compact', () => {
  assert.equal(formatBar(100000), '1');
  assert.equal(formatBar(10000000), '100');
  assert.equal(formatCell(999), '999');
  assert.equal(formatCell(0.0007), '7.000e-4');
  assert.equal(formatCell(-20000), '-20000');
  assert.equal(formatCell(null), '–');
});

test('the workspace preview shows the value grid and folds the summary text away', async () => {
  const view = await readFile(new URL('../src/WorkspaceView.tsx', import.meta.url), 'utf8');
  assert.match(view, /<PvtGridPreview /);
  assert.match(view, /<details className="ws-tab-details">[\s\S]*ws-tab-summary[\s\S]*<\/details>/);
  const grid = await readFile(new URL('../src/PvtGridPreview.tsx', import.meta.url), 'utf8');
  assert.match(grid, /fetchTabGrid\(path, column\)/);
  assert.match(grid, /className="pvt-grid-viewport" tabIndex=\{0\}/);
  assert.match(grid, /<th scope="row">/);
});

test('the preview and its grid are bounded scrollers with sticky axes', async () => {
  const css = (await readFile(new URL('../src/styles/workspace.css', import.meta.url), 'utf8')).replace(/\s+/g, ' ');
  assert.match(css.match(/\.ws-tab-preview \{([^}]*)\}/)?.[1] ?? '', /min-height: 0; flex: 1 1 auto; overflow: auto/);
  assert.match(css.match(/\.pvt-grid-viewport \{([^}]*)\}/)?.[1] ?? '', /max-height: [^;]+; overflow: auto/);
  assert.match(css, /\.pvt-grid-table thead th \{ position: sticky; top: 0/);
  assert.match(css, /\.pvt-grid-table tbody th \{ position: sticky; left: 0/);
});

// Review 2026-11-16: the curve SVG scales with its viewBox, so a pane narrower than the 640-unit
// viewBox shrank the 12px axis text below 12px. The svg keeps the viewBox width as a minimum and
// the figure scrolls sideways, so one user unit is never smaller than one pixel.
test('curve text never renders below 12px in a narrow pane', async () => {
  const { CURVE_VIEW } = await import('../src/pvtCurves.ts');
  const css = (await readFile(new URL('../src/styles/workspace.css', import.meta.url), 'utf8')).replace(/\s+/g, ' ');
  const figure = css.match(/\.pvt-curve-figure \{([^}]*)\}/)?.[1] ?? '';
  const svg = css.match(/\.pvt-curve-figure > svg \{([^}]*)\}/)?.[1] ?? '';
  const minWidth = Number(svg.match(/min-width: (\d+)px/)?.[1]);
  assert.ok(minWidth >= CURVE_VIEW.width, `svg min-width ${minWidth}px must be at least the ${CURVE_VIEW.width}-unit viewBox`);
  assert.match(figure, /overflow-x: auto/);
  assert.match(figure, /min-width: 0/);
  assert.match(css.match(/\.pvt-curve-label \{([^}]*)\}/)?.[1] ?? '', /font-size: var\(--fs-xs\)/);
  assert.match(css.match(/\.pvt-curve-title \{([^}]*)\}/)?.[1] ?? '', /font-size: var\(--fs-xs\)/);
});
