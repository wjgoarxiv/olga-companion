import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { readoutLeft, clientToDataX } from '../src/trendGeometry.mjs';

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

/* Live PVT check 2026-11-15: in the plot tab the wrapper is a flex column, which
 * stretched the readout to the full chart width, so it could not move at all
 * (translateX 0, centre 239 px away from the crosshair). */
test('the readout keeps its own width inside a flex-column wrapper', async () => {
  const css = await readFile(new URL('../src/styles/results.css', import.meta.url), 'utf8');
  const rule = css.match(/\.trend-readout\s*\{([^}]*)\}/);
  assert.ok(rule, 'no .trend-readout rule');
  assert.match(rule[1], /align-self:\s*flex-start/);
});

/* Live PVT check 2026-11-15: when the readout text got wider (167 -> 217 px) the box
 * was placed with the old width, 25 px off. It must be measured after layout. */
test('the readout is placed after layout, with its current width', async () => {
  const source = await readFile(new URL('../src/TrendChart.tsx', import.meta.url), 'utf8');
  assert.match(source, /useLayoutEffect\(/);
  assert.doesNotMatch(source, /style=\{\{ transform: `translateX\(\$\{readoutOffset\(/);
});
