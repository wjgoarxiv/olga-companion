import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { readoutLeft, readoutTop, clientToDataX } from '../src/trendGeometry.mjs';

/* Bug report 2026-11-15 (0.1.8): hovering a .tpl trend, the time/value readout did
 * not sit under the crosshair. It was moved by the viewBox x (0..640) in screen
 * pixels, which only matches a chart drawn exactly 640 px wide. */

test('the readout centre and the pointer agree on a wide chart', () => {
  const svg = { left: 100, width: 1280, height: 800 };
  const viewX = 76 + 254; // middle of the drawn plot (76..584)
  const left = readoutLeft(viewX, svg, { left: 100, width: 1280 }, 120);
  const centreClientX = 100 + left + 60;
  const dataAtCentre = clientToDataX(centreClientX, svg.left, svg.width, svg.height, 0, 100);
  assert.ok(Math.abs(dataAtCentre - 50) < 0.01, `centre maps to ${dataAtCentre}`);
});

test('the readout centre follows the letterbox of a short chart', () => {
  const svg = { left: 40, width: 1000, height: 400 }; // drawn 640 wide, 180 px each side
  const left = readoutLeft(76, svg, { left: 0, width: 1100 }, 100);
  assert.equal(left + 50, 40 + 180 + 76);
});

test('the readout stays inside the chart', () => {
  const svg = { left: 0, width: 640, height: 400 };
  assert.equal(readoutLeft(0, svg, { left: 0, width: 640 }, 200), 0);
  assert.equal(readoutLeft(640, svg, { left: 0, width: 640 }, 200), 440);
});

test('the chart positions the readout with the helper', async () => {
  const source = await readFile(new URL('../src/TrendChart.tsx', import.meta.url), 'utf8');
  assert.match(source, /readoutLeft\(/);
  assert.doesNotMatch(source, /Math\.min\(Math\.max\(readout\.x, 8\), 480\)/);
});

/* Owner report 2026-11-16 (0.1.9): the readout "under the x-axis" still felt unstable.
 * Live PVT: it sat in the layout flow, so hovering shrank the chart by 38 px
 * (532 -> 494) and leaving grew it back. It now floats over the chart. */
test('the readout floats over the chart, so hovering never resizes it', async () => {
  const css = await readFile(new URL('../src/styles/results.css', import.meta.url), 'utf8');
  const rule = css.match(/\.trend-readout\s*\{([^}]*)\}/);
  assert.ok(rule, 'no .trend-readout rule');
  assert.match(rule[1], /position:\s*absolute/);
  assert.match(rule[1], /pointer-events:\s*none/, 'the readout never steals the hover');
});

test('the readout sits on the x-axis line of the drawn plot', () => {
  // 640x400 viewBox drawn at scale 1 in a 640x500 svg: 50 px letterbox above and below.
  const svg = { top: 100, width: 640, height: 500 };
  const top = readoutTop(svg, { top: 80 }, 30);
  assert.equal(top, 100 - 80 + 50 + 376 - 30 - 4);
});

/* Live PVT 2026-11-16: with the data along the bottom, a readout on the x-axis line
 * covered the very point being inspected. A point in the lower half sends the
 * readout to the top of the plot (viewBox y 24) instead. */
test('the readout moves to the top of the plot when the point is in the lower half', () => {
  const svg = { top: 100, width: 640, height: 500 }; // letterbox 50 px, scale 1
  assert.equal(readoutTop(svg, { top: 80 }, 30, 24 + 300), 100 - 80 + 50 + 24 + 4);
  assert.equal(readoutTop(svg, { top: 80 }, 30, 24 + 50), 100 - 80 + 50 + 376 - 30 - 4);
});

test('the readout top never goes above the chart', () => {
  assert.equal(readoutTop({ top: 0, width: 64, height: 40 }, { top: 0 }, 60), 0);
});

/* Live PVT check 2026-11-15: when the readout text got wider (167 -> 217 px) the box
 * was placed with the old width, 25 px off. It must be measured after layout. */
test('the readout is placed after layout, with its current width', async () => {
  const source = await readFile(new URL('../src/TrendChart.tsx', import.meta.url), 'utf8');
  assert.match(source, /useLayoutEffect\(/);
  assert.doesNotMatch(source, /style=\{\{ transform: `translateX\(\$\{readoutOffset\(/);
});
