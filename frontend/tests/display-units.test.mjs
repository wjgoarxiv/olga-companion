import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { displayFromText, toDisplay, toDisplayDelta, toRaw } from '../src/displayQuantity.mjs';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

/* 0.1.22 row 10: values OLGA writes in its own units are shown in bar and °C, with the OLGA value and
 * unit kept on hover/focus. Only what is shown changes; exported files keep the OLGA bytes. */

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('pressure in Pa shows in bar, and the OLGA value is kept', () => {
  assert.deepEqual(toDisplay(2500000, 'PA'), { value: 25, unit: 'bar', raw: '2500000 PA', converted: true });
  assert.deepEqual(toDisplay(250, 'kPa'), { value: 2.5, unit: 'bar', raw: '250 kPa', converted: true });
});

test('temperature in K or C shows in °C; a temperature change converts without the offset', () => {
  assert.deepEqual(toDisplay(300, 'K'), { value: 26.85, unit: '°C', raw: '300 K', converted: true });
  assert.deepEqual(toDisplay(40, 'C'), { value: 40, unit: '°C', raw: '40 C', converted: true });
  assert.deepEqual(toDisplayDelta(5, 'K'), { value: 5, unit: '°C', raw: '5 K', converted: true });
  assert.deepEqual(toDisplayDelta(-100000, 'PA'), { value: -1, unit: 'bar', raw: '-100000 PA', converted: true });
});

test('mass flow keeps its value in kg/s; an unknown unit is shown as it is', () => {
  assert.deepEqual(toDisplay(12.5, 'KG/S'), { value: 12.5, unit: 'kg/s', raw: '12.5 KG/S', converted: true });
  assert.deepEqual(toDisplay(0.4, '-'), { value: 0.4, unit: '-', raw: '0.4 -', converted: false });
  assert.deepEqual(toDisplay(3, 'M3/S'), { value: 3, unit: 'm3/s', raw: '3 M3/S', converted: true });
});

test('a "value unit" text from the case file is shown converted, and other text is kept', () => {
  assert.equal(displayFromText('2500000 PA'), '25 bar');
  assert.equal(displayFromText('40 C'), '40 °C');
  assert.equal(displayFromText('250 bara'), '250 bara');
  assert.equal(displayFromText('ON'), 'ON');
});

test('a shown value goes back to the same OLGA value', () => {
  for (const [value, unit] of [[2500000, 'PA'], [300, 'K'], [40, 'C'], [12.5, 'KG/S'], [101325, 'PA']]) {
    assert.equal(toRaw(toDisplay(value, unit).value, unit), value);
  }
});

test('the sweep table shows bar with the OLGA value on hover and focus, and never a bare PA', async () => {
  const { renderSweepSummary } = await reviewNotesRenderer();
  const html = renderSweepSummary('en', [
    { index: 0, state: 'completed', params: [], outputs: { PT: { value: 2500000, unit: 'PA', change: null }, TM: { value: 300, unit: 'K' } } },
    { index: 1, state: 'completed', params: [], outputs: { PT: { value: 2600000, unit: 'PA', change: 100000 }, TM: { value: 301, unit: 'K', change: 1 } } },
  ]);
  assert.match(html, /25 bar/);
  assert.match(html, /\+1 bar/);
  assert.match(html, /26\.85 °C/);
  // Review R9: the OLGA value is a tip shown on hover and on keyboard focus, not a mouse-only title.
  assert.match(html, /<span class="display-value-tip" role="tooltip"[^>]*>OLGA: 2500000 PA<\/span>/);
  assert.match(html, /tabindex="0" aria-describedby="/);
  const visible = html.replace(/<span class="display-value-tip"[^>]*>.*?<\/span>/g, '').replace(/<[^>]+>/g, ' ');
  assert.doesNotMatch(visible, /\bPA\b/, 'PA appears only in the hover text');
  assert.doesNotMatch(visible, /\d\s+K\b/, 'K appears only in the hover text');
});

test('PVT D6: the OLGA value opens under the number, so the table scroll box cannot cut it off', async () => {
  const css = await read('../src/styles/results.css');
  const rule = css.match(/\.display-value-tip \{[^}]*\}/)?.[0] ?? '';
  assert.match(rule, /position: static;/);
  assert.doesNotMatch(rule, /bottom:|white-space: nowrap/);
  // A number is never split across two lines: "10420 / 09" reads as two numbers.
  assert.doesNotMatch(rule, /overflow-wrap: anywhere|word-break: break-all/);
});

test('an approval card shows the shown value and the OLGA value side by side', async () => {
  const { renderDisplayValue } = await reviewNotesRenderer();
  const html = renderDisplayValue('ko', '2500000', 'Pa', true);
  assert.match(html, /25 bar/);
  assert.match(html, /2500000 Pa/);
  assert.equal(renderDisplayValue('ko', 'ON', '', true).replace(/<[^>]+>/g, ''), 'ON', 'text values pass through');
  // Review R3: a unit the app does not convert is shown on the card exactly as OLGA wrote it.
  assert.equal(renderDisplayValue('ko', '0.5', 'fraction', true).replace(/<[^>]+>/g, ''), '0.5 fraction');
  assert.equal(renderDisplayValue('ko', '14.7', 'PSI', true).replace(/<[^>]+>/g, ''), '14.7 PSI');
});

test('review R2: the results summary uses the unit the chart shows, including one the user picked', async () => {
  const analysis = await read('../src/ResultAnalysis.tsx');
  assert.doesNotMatch(analysis, /displayQuantity/, 'the summary is not converted away from the chart unit');
  assert.match(analysis, /formatUnit\(series\.unit \?\? ''\)/);
});

test('exports keep the OLGA bytes: the CSV path never goes through the display conversion', async () => {
  for (const file of ['../src/resultExports.ts', '../src/ResultAnalysis.tsx']) {
    const source = await read(file).catch(() => '');
    assert.doesNotMatch(source, /toDisplay[^(]*\([^)]*csv/i, `${file} does not convert export data`);
  }
  const card = await read('../src/ApprovalCard.tsx');
  assert.match(card, /<DisplayValue value=\{field\.value\} unit=\{field\.unit\} withRaw \/>/);
});
