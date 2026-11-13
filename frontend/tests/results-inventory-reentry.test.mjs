import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('result inventory cache is root-scoped and returns defensive result arrays', async () => {
  const cache = await import('../src/resultInventoryCache.ts');
  const item = { id: 'run:one/case.tpl', name: 'case.tpl' };

  cache.writeResultInventoryCache({ root: '/workspace/a', results: [item] });
  const first = cache.readResultInventoryCache('/workspace/a');
  assert.deepEqual(first, { root: '/workspace/a', results: [item] });
  first.results.length = 0;
  assert.deepEqual(cache.readResultInventoryCache('/workspace/a'), { root: '/workspace/a', results: [item] });
  assert.equal(cache.readResultInventoryCache('/workspace/b'), null);
});

test('Results reentry paints cached inventory immediately while truthfully refreshing it', async () => {
  const [view, rail] = await Promise.all([
    read('../src/ResultsView.tsx'),
    read('../src/ResultsInventoryRail.tsx'),
  ]);

  assert.match(view, /const cachedInventory = readResultInventoryCache\(wsRoot\)/);
  assert.match(view, /useState<session\.ResultFile\[\]>\(cachedInventory\?\.results \?\? \[\]\)/);
  assert.match(view, /useEffect\(\(\) => \{\s*void refreshResults\(\);\s*\}, \[\]\)/);
  assert.match(view, /fetchResultInventorySingleflight\(wsRoot, session\.fetchResults\)/);
  assert.match(rail, /inventoryLoading[\s\S]*results\.length > 0[\s\S]*t\('results\.refreshing'\)/);
});
