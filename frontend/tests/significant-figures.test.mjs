import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import * as resultPresentation from '../src/resultPresentation.ts';
import {
  DEFAULT_SIGNIFICANT_FIGURES,
  SIGNIFICANT_FIGURES_KEY,
  loadSignificantFigures,
  saveSignificantFigures,
} from '../src/significantFigures.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem(key) { return data.has(key) ? data.get(key) : null; },
    setItem(key, value) { data.set(key, String(value)); },
  };
}

test('numeric display rounds finite engineering values to the selected significant figures', () => {
  // Given: values spanning the real OLGA pressure, temperature, zero, and trace ranges.
  const values = [606_694, 225.0297, 19.99999, 0, 0.0000123456];

  // When: the operator chooses four significant figures.
  const displayed = values.map((value) => resultPresentation.metric(value, 4));

  // Then: presentation is rounded without changing source values.
  assert.deepEqual(displayed, ['606,700', '225', '20', '0', '1.235e-5']);
  assert.equal(values[0], 606_694);
  assert.equal(resultPresentation.metric(Number.NaN, 4), 'unavailable');
});

test('significant-figure preference persists only approved display choices', () => {
  // Given: empty local display storage.
  const storage = memoryStorage();

  // When: the default is loaded and a supported precision is saved.
  assert.equal(loadSignificantFigures(storage), DEFAULT_SIGNIFICANT_FIGURES);
  assert.equal(saveSignificantFigures(4, storage), true);

  // Then: the approved choice is restored while malformed values reset safely.
  assert.equal(loadSignificantFigures(storage), 4);
  storage.setItem(SIGNIFICANT_FIGURES_KEY, JSON.stringify({ version: 1, significantFigures: 99 }));
  assert.equal(loadSignificantFigures(storage), DEFAULT_SIGNIFICANT_FIGURES);
});

test('settings and numeric result surfaces share the significant-figure preference', async () => {
  // Given: every user-visible numeric result surface.
  const [settings, markdown, table, chart, analysis, ko] = await Promise.all([
    read('../src/SettingsView.tsx'),
    read('../src/Markdown.tsx'),
    read('../src/SeriesTable.tsx'),
    read('../src/TrendChart.tsx'),
    read('../src/ResultAnalysis.tsx'),
    read('../src/i18n/ko.ts'),
  ]);

  // When/Then: one shared preference controls settings, structured tables, chat tables, charts, and summaries.
  assert.match(settings, /t\('settings\.significantFigures'\)/);
  assert.match(ko, /'settings\.significantFigures': '유효 숫자'/);
  assert.match(settings, /useSignificantFigures/);
  assert.match(markdown, /formatSignificant/);
  assert.match(table, /useSignificantFigures/);
  assert.match(chart, /useSignificantFigures/);
  assert.match(analysis, /useSignificantFigures/);
});
