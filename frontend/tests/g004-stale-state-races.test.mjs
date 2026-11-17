import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readRunSource } from './run-source.mjs';
import { readResultsSource } from './results-source.mjs';
import { readSessionSource } from './session-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test('a new run clears restored evidence before execute and the first status poll', async () => {
  const run = await readRunSource();
  const start = run.indexOf('async function doRun()');
  const end = run.indexOf('async function doCancel()', start);
  const launch = run.slice(start, end);
  const execute = launch.indexOf('await session.runExecute');
  const runIdClear = launch.indexOf('setRunId(null)');
  const statusClear = launch.indexOf('setStatus(null)');

  assert.ok(start >= 0 && end > start && execute > 0);
  assert.ok(runIdClear >= 0 && runIdClear < execute, 'the restored run identity is cleared before launch');
  assert.ok(statusClear >= 0 && statusClear < execute, 'the restored terminal receipt is cleared before launch');
});

test('workspace topology waits for the selected case activation to finish', async () => {
  const { loadWorkspaceCase } = await import('../src/workspaceCaseOpen.mjs');
  const activation = deferred();
  const events = [];
  const selectedCase = { name: 'B.genkey', rel: 'B.genkey', suffix: '.genkey', size: 10 };

  const pending = loadWorkspaceCase(selectedCase, { activate: true }, {
    activate: async (rel) => {
      events.push(`activate:${rel}`);
      await activation.promise;
      events.push(`activated:${rel}`);
    },
    fetchTopology: async (rel) => {
      events.push(`topology:${rel}`);
      return { path: rel, nodes: [], edges: [], counts: { nodes: 0, flowpaths: 0, edges: 0 }, truncated: false };
    },
  });

  await Promise.resolve();
  assert.deepEqual(events, ['activate:B.genkey'], 'topology cannot race ahead of backend activation');
  activation.resolve();
  await pending;
  assert.deepEqual(events, ['activate:B.genkey', 'activated:B.genkey', 'topology:B.genkey']);
});

test('chat approval resolves only after the exact execution succeeds', async () => {
  const controller = await read('../src/useApprovalContinuation.ts');
  const start = controller.indexOf('async function approve(request: ApprovalRequest)');
  const end = controller.indexOf('async function reject(request: ApprovalRequest)', start);
  const approve = controller.slice(start, end);
  const execution = approve.indexOf('await args.executeApproval');

  assert.ok(start >= 0 && end > start && execution > 0);
  assert.doesNotMatch(approve.slice(0, execution), /finishApproval\(/, 'an undispatched request cannot claim a receipt');
  assert.match(approve.slice(execution), /classifyApprovalReceipt\(execution\)[\s\S]*finishApproval\(request, state, execution\.result\)/);
});

test('same-id result refresh invalidates chart and exports when file revision changes', async () => {
  const results = await readResultsSource(import.meta.url);

  assert.match(results, /function resultRevisionKey\(result: session\.ResultFile\): string/);
  assert.match(results, /selectedRevisionRef/);
  assert.match(
    results,
    /else if \(retained && resultRevisionKey\(retained\) !== selectedRevisionRef\.current\) \{\s*await openFile\(retained\);\s*\}/,
  );
});

test('protected evidence images use an authenticated Blob URL and revoke it on cleanup', async () => {
  const [evidence, api] = await Promise.all([
    read('../src/EvidenceBlock.tsx'),
    readSessionSource(import.meta.url),
  ]);

  assert.match(evidence, /AuthenticatedResultImage/);
  assert.match(evidence, /URL\.createObjectURL/);
  assert.match(evidence, /URL\.revokeObjectURL/);
  assert.match(evidence, /controller\.abort\(\)/);
  assert.doesNotMatch(evidence, /<img[^>]+src=\{`\/api\/results\/download/);
  assert.match(api, /fetchResultImage\(path: string, signal\?: AbortSignal\): Promise<Blob>/);
  assert.match(api, /apiFetch\(resultDownloadUrl\(path\), \{ signal \}\)/);
});
