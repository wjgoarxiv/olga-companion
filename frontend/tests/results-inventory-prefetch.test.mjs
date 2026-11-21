import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('result inventory prefetch shares concurrent scans and keeps roots isolated', async () => {
  const cache = await import('../src/resultInventoryCache.ts');
  let calls = 0;
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const loader = async () => {
    calls += 1;
    await pending;
    return { root: '/workspace/prefetch', results: [{ id: 'run:prefetch/case.tpl' }] };
  };

  const first = cache.prefetchResultInventory('/workspace/prefetch', loader);
  const second = cache.fetchResultInventorySingleflight('/workspace/prefetch', loader);
  assert.equal(calls, 1, 'concurrent prefetch and Results entry must share one filesystem scan');
  release();
  assert.deepEqual(await first, await second);
  assert.equal(cache.readResultInventoryCache('/workspace/other'), null);

  await cache.fetchResultInventorySingleflight('/workspace/prefetch', async () => {
    calls += 1;
    return { root: '/workspace/prefetch', results: [] };
  });
  assert.equal(calls, 2, 'a completed scan must not suppress a later explicit refresh');
});

test('App warms Results after runtime recovery and ResultsView joins that request', async () => {
  const [app, view] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/ResultsView.tsx'),
  ]);

  assert.match(app, /runtime\.state !== 'online' \|\| !workspaceRoot/);
  assert.match(app, /prefetchResultInventory\(workspaceRoot, session\.fetchResults\)/);
  assert.match(view, /fetchResultInventorySingleflight\(wsRoot, session\.fetchResults\)/);
});

test('a fresh scan never joins an older one, and later joiners get the fresh list', async () => {
  // A run that finished while an older scan was in flight was missing from the list it got back.
  const cache = await import('../src/resultInventoryCache.ts');
  let release;
  const older = cache.fetchResultInventorySingleflight('/workspace/fresh', () => new Promise((resolve) => {
    release = () => resolve({ root: '/workspace/fresh', results: [] });
  }));
  const fresh = cache.rescanResultInventory('/workspace/fresh', async () => (
    { root: '/workspace/fresh', results: [{ id: 'run:new/case.tpl' }] }));
  const joined = cache.fetchResultInventorySingleflight('/workspace/fresh', async () => ({ root: '/workspace/fresh', results: [] }));
  assert.deepEqual((await fresh).results.map((item) => item.id), ['run:new/case.tpl']);
  assert.deepEqual((await joined).results.map((item) => item.id), ['run:new/case.tpl']);
  release();
  await older;
  assert.deepEqual(cache.readResultInventoryCache('/workspace/fresh').results.map((item) => item.id), ['run:new/case.tpl'],
    'the older scan finishing later does not overwrite the fresh list');
});

test('a finished run reads a fresh list in the opener and in an open Results view', async () => {
  const [view, opener] = await Promise.all([read('../src/ResultsView.tsx'), read('../src/useRunCompletionOpener.ts')]);
  assert.match(view, /if \(preferredResultId\) void refreshResults\(true\);/);
  assert.match(view, /rescanResultInventory\(wsRoot, session\.fetchResults\)/);
  assert.match(opener, /rescanResultInventory\(workspaceRoot, fetchResults\)/);
});
