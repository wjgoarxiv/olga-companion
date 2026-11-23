// N6: the same variable from another run joins the chart only when its unit and time base match.
import assert from 'node:assert/strict';
import test from 'node:test';
import { overlayRefusal } from '../src/crossRunOverlay.mjs';

const conv = (output_unit, dimension, quantity_kind = 'point') => ({ status: 'identity', source_unit: output_unit, requested_unit: null, output_unit, dimension, quantity_kind, reason: null });
const series = ({ unit = 'bara', dim = 'pressure', time = 's', kind = 'point', samples = [0, 1, 2] } = {}) => ({
  variable: 'PT', unit, position: 'POS', time: samples, values: samples.map(() => 1), time_unit: time,
  view: { value_conversion: conv(unit, dim, kind), time_conversion: conv(time, 'time'), range: { mode: 'full' } },
});

test('a matching series from another run is allowed', () => {
  assert.equal(overlayRefusal(series(), series()), null);
});

test('a different unit, dimension, quantity kind or time unit is refused with both names', () => {
  assert.deepEqual(overlayRefusal(series(), series({ unit: 'barg' })), { key: 'overlay.refuse.unit', params: { a: 'bara', b: 'barg' } });
  assert.deepEqual(overlayRefusal(series(), series({ unit: 'C', dim: 'temperature' })), { key: 'overlay.refuse.dimension', params: { a: 'pressure', b: 'temperature' } });
  assert.equal(overlayRefusal(series(), series({ kind: 'delta' }))?.key, 'overlay.refuse.unit');
  assert.deepEqual(overlayRefusal(series(), series({ time: 'h' })), { key: 'overlay.refuse.time', params: { a: 's', b: 'h' } });
});

test('a unit the app cannot read on either side is refused rather than assumed', () => {
  assert.equal(overlayRefusal(series({ unit: '' }), series({ unit: '' }))?.key, 'overlay.refuse.unit');
  assert.equal(overlayRefusal(series({ time: '' }), series({ time: '' }))?.key, 'overlay.refuse.time');
});

test('an empty series from the other run is refused', () => {
  assert.deepEqual(overlayRefusal(series(), series({ samples: [] })), { key: 'overlay.refuse.empty', params: {} });
  assert.deepEqual(overlayRefusal(series(), null), { key: 'overlay.refuse.empty', params: {} });
});

import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';
import { translate } from '../src/i18n/index.ts';

const r = await reviewNotesRenderer();
const file = (id, name, source_name = null) => ({ id, name, rel: name, origin: 'run', size: 1, suffix: '.tpl', modified_ns: 1, source_name });

test('the picker lists the other runs and names the variable on screen', () => {
  const html = r.renderCrossRunPicker('en', [file('r2', 'run2.tpl', 'valve.edit1.genkey')], 'PT · POS_MAIN');
  assert.match(html, /<span>Add PT · POS_MAIN from another run<\/span>/);
  assert.match(html, /<option value="r2">valve\.edit1\.genkey · [^<]+<\/option>/);
  assert.match(r.renderCrossRunPicker('ko', [file('r2', 'run2.tpl')], 'PT · POS_MAIN'), /다른 실행의 PT · POS_MAIN 겹쳐 보기/);
});

test('no other run or no variable on screen renders nothing', () => {
  assert.equal(r.renderCrossRunPicker('en', [], 'PT · POS'), '');
  assert.equal(r.renderCrossRunPicker('en', [file('r2', 'run2.tpl')], null), '');
});

test('every refusal has English and Korean text that names both sides', () => {
  const params = { a: 'bara', b: 'barg', name: 'run2.tpl' };
  for (const key of ['overlay.refuse.empty', 'overlay.refuse.dimension', 'overlay.refuse.unit', 'overlay.refuse.time']) {
    for (const locale of ['en', 'ko']) {
      const text = translate(locale, key, params);
      assert.notEqual(text, key);
      assert.match(text, /run2\.tpl/);
      if (key !== 'overlay.refuse.empty') assert.match(text, /bara[\s\S]*barg/);
    }
  }
});

test('a second run far outside the first is drawn inside the chart (N6 review)', async () => {
  const { reviewNotesRenderer } = await import('./helpers/render-review-notes.mjs');
  const rr = await reviewNotesRenderer();
  const view = { value_conversion: { dimension: 'pressure', output_unit: 'bara' }, time_conversion: { output_unit: 's' } };
  const base = { variable: 'PT', position: 'P1', unit: 'bara', time_unit: 's', time: [0, 10], values: [8.4, 9], view };
  const other = { ...base, values: [20, 30] };
  const html = rr.renderTrendChart(base, [{ key: 'B', series: other, color: 'var(--s2)' }]);
  const d = [...html.matchAll(/<path[^>]*d="([^"]+)"[^>]*stroke="var\(--s2\)"|<path[^>]*stroke="var\(--s2\)"[^>]*d="([^"]+)"/g)].map((m) => m[1] ?? m[2])[0];
  assert.ok(d, 'the overlay is drawn');
  for (const [, y] of d.matchAll(/[ML][\d.]+,([\d.-]+)/g)) assert.ok(Number(y) >= 24 && Number(y) <= 376, `y ${y} inside the plot`);
});

test('runs of the same case read apart by their time, not as the same file name (N6 review)', async () => {
  const { runLabel } = await import('../src/crossRunLabel.mjs');
  const at = (iso) => Date.parse(iso) * 1_000_000;
  const a = { ...file('r1', 'case.tpl', 'valve_shut_in.genkey'), modified_ns: at('2026-11-18T09:00:00Z') };
  const b = { ...file('r2', 'case.tpl', 'valve_shut_in.genkey'), modified_ns: at('2026-11-18T10:30:00Z') };
  assert.notEqual(runLabel(a, 'en'), runLabel(b, 'en'));
  assert.match(runLabel(a, 'en'), /^valve_shut_in\.genkey · /);
  assert.match(runLabel({ ...a, source_name: null }, 'ko'), /^case\.tpl · /);
});

test('a run that cannot be read is refused in the screen language (N6 review)', () => {
  assert.equal(translate('ko', 'overlay.refuse.unreadable', { variable: 'PT', name: 'r' }), '추가하지 않았어요: r에서 PT를 읽지 못했어요.');
  assert.equal(translate('en', 'overlay.refuse.unreadable', { variable: 'PT', name: 'r' }), 'Not added: could not read PT from r.');
});

test('a chip from another run follows the UI language after a switch (N6 recheck)', async () => {
  const { chipSource } = await import('../src/crossRunLabel.mjs');
  const run = { ...file('r2', 'case.tpl', 'riser.genkey'), modified_ns: Date.parse('2026-11-17T01:37:00Z') * 1_000_000 };
  const chip = { source: 'riser.genkey · Nov 17, 2026, 10:37 AM', fileId: 'r2' };
  assert.match(chipSource(chip, [run], 'ko'), /^riser\.genkey · 2026\. 11\. 17\./);
  assert.equal(chipSource({ source: undefined, fileId: 'r1' }, [run], 'ko'), undefined);
});
