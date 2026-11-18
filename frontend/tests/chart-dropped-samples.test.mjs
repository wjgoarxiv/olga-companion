// R3: the chart says how many NaN or empty samples were left out.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (p) => readFile(new URL(p, import.meta.url), 'utf8');

test('the unit bar shows the dropped sample count only when samples were dropped', async () => {
  const bar = await read('../src/ChartUnitBar.tsx');
  assert.match(bar, /series\.view\.dropped_non_finite \?\? 0/);
  assert.match(bar, /dropped > 0 && <p className="chart-unit-note" role="note">\{t\('chartUnits\.droppedNonFinite', \{ count: dropped \}\)\}/);
});

test('the dropped sample note has English and Korean text with the count', async () => {
  const en = await read('../src/i18n/en.ts');
  const ko = await read('../src/i18n/ko.ts');
  assert.match(en, /'chartUnits\.droppedNonFinite': '\{count\} samples [^']+'/);
  assert.match(ko, /'chartUnits\.droppedNonFinite': '[^']*\{count\}개[^']*'/);
});
