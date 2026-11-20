// 0.1.20 row 10: every trend chart has a "Show as table" twin with the same samples.
import test from 'node:test';
import assert from 'node:assert/strict';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const series = (n) => ({
  path: 'a.tpl', variable: 'PT', position: 'OUTLET', unit: 'bara', time_unit: 's', description: '',
  time: Array.from({ length: n }, (_, i) => i * 10), values: Array.from({ length: n }, (_, i) => 50 + i),
});

test('the table has a caption, column and row headers, and one row per sample', () => {
  for (const locale of ['en', 'ko']) {
    const html = r.renderTrendTable(locale, series(7), 'bara');
    assert.match(html, /<caption[^>]*>[^<]*PT/, locale);
    assert.equal([...html.matchAll(/<th scope="col"/g)].length, 2, locale);
    assert.equal([...html.matchAll(/<th scope="row"/g)].length, 7, `${locale} same sample count as the chart`);
    assert.match(html, /<td class="ui-num">56<\/td>/, locale);
  }
});

test('a long series is capped with a note pointing to the CSV export', () => {
  const html = r.renderTrendTable('en', series(1203), 'bara');
  assert.equal([...html.matchAll(/<th scope="row"/g)].length, 1000);
  assert.match(html, /Showing the first 1000 of 1203 samples\. Export CSV for all of them\./);
  assert.match(r.renderTrendTable('ko', series(1203), 'bara'), /1203개 중 처음 1000개/);
});

test('the table region and the toggle can be reached with the keyboard', () => {
  const html = r.renderTrendTable('en', series(3), 'bara');
  assert.match(html, /<div[^>]*role="region"[^>]*tabindex="0"|<div[^>]*tabindex="0"[^>]*role="region"/);
  for (const [locale, label] of [['en', 'Show as table'], ['ko', '표로 보기']]) {
    const chart = r.renderTrendChartIn(locale, series(3));
    assert.match(chart, new RegExp(`<button[^>]*aria-expanded="false"[^>]*>(<[^>]+>)*${label}`), locale);
  }
});

test('a series with no position has a caption without a stray space before the colon', () => {
  const html = r.renderTrendTable('en', { ...series(12), position: null }, 'bara');
  assert.match(html, /<caption[^>]*>PT: 12 samples</);
  assert.match(r.renderTrendTable('en', series(1203), 'bara'), /<caption[^>]*>PT OUTLET: 1,203 samples</);
});

test('close values keep enough figures to read differently, as on the chart (0.1.20 review)', () => {
  const close = { ...series(3), values: [101325, 101331, 101340], time: [100000, 100001, 100002] };
  const html = r.renderTrendTable('en', close, 'Pa');
  const values = [...html.matchAll(/<td class="ui-num">([^<]+)<\/td>/g)].map((m) => m[1]);
  const times = [...html.matchAll(/<th scope="row">([^<]+)<\/th>/g)].map((m) => m[1]);
  assert.equal(new Set(values).size, 3, `values read differently: ${values}`);
  assert.equal(new Set(times).size, 3, `times read differently: ${times}`);
});

test('the value column is labelled in the unit the chart shows, not the raw file unit (0.1.20 PVT)', () => {
  // The chart converted Pa to bar: series.unit is bar, the variable's file unit is still Pa.
  const html = r.renderTrendTable('en', { ...series(3), unit: 'bar' }, 'Pa');
  assert.match(html, /PT \(bar\)/);
  assert.doesNotMatch(html, /PT \(Pa\)/);
});
