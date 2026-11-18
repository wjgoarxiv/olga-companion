import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* Fix-up: the plot tab fits the available panel height with dock and bottom
 * panel open — the svg keeps exact aspect and caps its width against the
 * centre-panel height (container query), pointer mapping tolerates letterbox.
 * Table/verdict tabs keep the default scrolling main column. */

test('plot tab caps the chart against the visible centre height', async () => {
  const [layout, shell, css] = await Promise.all([
    read('../src/ResultsLayout.tsx'),
    read('../src/styles/workbench.css'),
    read('../src/styles/results.css'),
  ]);
  assert.match(layout, /rv-main-tab-plot/, 'the plot tab marks the main column');
  assert.match(shell, /\.wb-centre-tabs > \.ui-tabs\s*\{[^}]*display:\s*flex/, 'the centre tabs flex so the panel height is definite');
  assert.match(shell, /\.wb-centre-tabs > \.ui-tabs > \.ui-tabpanel\s*\{[^}]*container-type:\s*size/, 'only the outer centre panel is a size container');
  assert.match(css, /\.rv-main-tab-plot\s*\{[^}]*--rv-plot-chrome:/, 'the plot tab reserves its chrome');
  assert.match(css, /\.rv-main-tab-plot \.rv-chart-wrap\s*\{[^}]*height:\s*calc\(100cqh - var\(--rv-plot-chrome\)\)/, 'the wrap takes a formula height from the panel');
});

test('trend svg fills its wrap, profile follows without pointer maths', async () => {
  const [chart, profile, css] = await Promise.all([
    read('../src/TrendChart.tsx'),
    read('../src/ProfileChart.tsx'),
    read('../src/styles/results.css'),
  ]);
  assert.match(css, /\.rv-main-tab-plot \.trend-viewport\s*\{[^}]*flex:\s*1/, 'the viewport takes the wrap after the readout');
  assert.match(css, /\.rv-main-tab-plot \.trend-svg\s*\{[^}]*width:\s*100%/, 'the svg takes the column width');
  assert.match(css, /\.rv-main-tab-plot \.trend-svg\s*\{[^}]*height:\s*auto/, 'exact aspect keeps pointer math exact');
  assert.match(css, /\.rv-main-tab-plot \.trend-svg\s*\{[^}]*max-height:\s*100%/, 'a tall column letterboxes instead of spilling');
  assert.match(css, /@container rv-main \(max-width: 720px\)[\s\S]*?\.rv-plot \{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/, 'narrow columns stack instead of squeezing');
  assert.match(css, /@container rv-main \(max-width: 720px\)[\s\S]*?\.rv-chart \{[^}]*order:\s*-1/, 'the chart renders first in narrow columns');
  assert.match(chart, /clientToDataX|fitViewBox/, 'pointer mapping tolerates letterboxing');
  assert.match(css, /\.rv-main-tab-plot \.profile-chart\s*\{[^}]*height:\s*calc\(100cqh/, 'the profile figure takes the same formula height');
  assert.doesNotMatch(profile, /onMouseMove|onMouseDown/, 'the static profile needs no pointer mapping');
  assert.match(css, /\.rv-main-tab-plot \.rv-plot-side\s*\{[^}]*max-height:\s*calc\(100cqh/, 'the picker side caps itself with an internal scroll');
  assert.match(css, /max-height:\s*850px[\s\S]*?\.rv-picker \.rv-vars\s*\{[^}]*max-height:\s*180px/, 'short viewports compact the picker list');
});

test('single explorer filter drives both the tree and the results rail', async () => {
  const [store, explorer, rail] = await Promise.all([
    read('../src/explorerFilter.ts'),
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/ResultsInventoryRail.tsx'),
  ]);
  assert.match(store, /useSyncExternalStore/, 'one shared filter store, no prop drilling');
  assert.match(store, /getExplorerFilter|subscribeExplorerFilter/, 'explorer and rail read the same source');
  assert.match(explorer, /useExplorerFilter/, 'the tree filters from the shared store');
  assert.match(rail, /useExplorerFilter/, 'the rail filters from the shared store');
  assert.doesNotMatch(rail, /rv-inventory-filter/, 'the duplicate rail filter is gone');
  assert.match(rail, /clearFilter/, 'clearing resets the shared filter');
  assert.match(rail, /caseOnly|refreshResults/, 'case toggle and refresh keep working');
});

test('profile exports reuse the existing endpoints with branch and timestep', async () => {
  const [api, exportsState, analysis, ko, en] = await Promise.all([
    read('../src/resultApi.ts'),
    read('../src/useResultExports.ts'),
    read('../src/ResultAnalysis.tsx'),
    read('../src/i18n/ko.ts'),
    read('../src/i18n/en.ts'),
  ]);
  assert.match(api, /exportProfileCsv/, 'profile CSV posts branch/timestep without a position');
  assert.match(api, /exportProfilePlot/, 'profile figure posts branch without a position');
  assert.match(exportsState, /exportProfileCsv/, 'the results exports wire profile CSV export');
  assert.match(exportsState, /exportProfilePlot/, 'the results exports wire profile figure export');
  assert.match(analysis, /series\b[^:]*\|\s*null|series:\s*Series\s*\|\s*null/, 'analysis renders without trend stats for profiles');
  assert.match(analysis, /publication\.publication\s*\?/, 'figure receipts tolerate a stats-free publication');
});
