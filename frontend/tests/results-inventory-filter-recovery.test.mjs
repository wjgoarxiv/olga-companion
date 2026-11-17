import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('an empty Results filter exposes a one-click recovery action', async () => {
  const rail = await read('../src/ResultsInventoryRail.tsx');

  assert.match(rail, /results\.length > 0 && shownResults\.length === 0/);
  assert.match(
    rail,
    /<Button[^>]*className="rv-clear-filter"[^>]*onClick=\{\(\) => setExplorerFilter\(''\)\}[^>]*>\{t\('results\.clearFilter'\)\}<\/Button>/,
    'one click clears the single shared explorer filter',
  );
});
