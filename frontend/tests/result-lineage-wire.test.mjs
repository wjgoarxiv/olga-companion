import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { normalizeResultFile } from '../src/lineageNormalization.ts';
import { receiptBacked, resultContextLabel } from '../src/resultPresentation.ts';

const run = (extra) => ({
  id: 'run:abc/case.tpl', name: 'case.tpl', rel: 'abc/case.tpl', origin: 'run', run_id: 'abc', ...extra,
});

test('the status the sidecar sends survives normalization, so receipt-backed results are recognised', () => {
  const backed = normalizeResultFile(run({ lineage_status: 'receipt_output' }));
  const changed = normalizeResultFile(run({ lineage_status: 'receipt_changed' }));
  const legacy = normalizeResultFile(run({ lineage_status: null }));

  assert.equal(backed.lineage_status, 'receipt_output');
  assert.equal(receiptBacked(backed), true);
  assert.equal(receiptBacked(changed), false, 'a replaced file is never presented as verified');
  assert.equal(receiptBacked(legacy), false);
});

test('labels tell receipt-backed, replaced, legacy and external results apart', () => {
  assert.match(resultContextLabel(run({ lineage_status: 'receipt_changed' })), /changed after the run · not verified/);
  assert.match(resultContextLabel(run({ lineage_status: null })), /Historical · Run abc/);
  assert.match(resultContextLabel({ ...run({}), origin: 'workspace', rel: 'out/case.tpl' }), /Workspace package result · out\/case\.tpl/);
});

test('the sidecar and the frontend name the lineage field identically', async () => {
  const backend = await readFile(new URL('../../src/olga_companion/result_inventory.py', import.meta.url), 'utf8');
  const frontend = await readFile(new URL('../src/lineageNormalization.ts', import.meta.url), 'utf8');

  assert.match(backend, /"lineage_status": lineage_status/);
  assert.match(frontend, /LINEAGE_STATUS_WIRE_FIELD = 'lineage_status'/);
});

test('beginner-facing names exist only for mnemonics whose meaning is certain', async () => {
  const { plainVariableName } = await import('../src/resultPresentation.ts');

  assert.equal(plainVariableName('PT'), '압력');
  assert.equal(plainVariableName(' tm '), '온도');
  assert.equal(plainVariableName('HOLWT'), null, 'an unknown mnemonic is shown as OLGA wrote it, never guessed');
  assert.equal(plainVariableName(''), null);
});

test('every selection change invalidates both the export receipt and its in-flight request', async () => {
  const [view, exportsState] = await Promise.all([
    readFile(new URL('../src/ResultsView.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/useResultExports.ts', import.meta.url), 'utf8'),
  ]);
  const body = (name) => view.slice(view.indexOf(name), view.indexOf('\n  }\n', view.indexOf(name)));

  for (const handler of ['async function pickVar', 'function activateSeries', 'async function changeView', 'async function changeBranch', 'async function changeTimestep']) {
    assert.match(body(handler), /clearExports\(\)/, `${handler} must call clearExports`);
  }
  const clear = exportsState.slice(exportsState.indexOf('function clearExports'), exportsState.indexOf('\n  }\n', exportsState.indexOf('function clearExports')));
  assert.match(clear, /figureExportRequestRef\.current\.invalidate\(\)/, 'export state lives in the extracted hook');
  assert.match(clear, /csvExportRequestRef\.current\.invalidate\(\)/);
  assert.match(view, /activateSeries=\{activateSeries\}/, 'the legend uses the invalidating handler, not the raw overlay one');
});

test('a selection change resets the busy flags of the export it supersedes', async () => {
  const exportsState = await readFile(new URL('../src/useResultExports.ts', import.meta.url), 'utf8');
  const clear = exportsState.slice(exportsState.indexOf('function clearExports'), exportsState.indexOf('\n  }\n', exportsState.indexOf('function clearExports')));

  assert.match(clear, /setFigureExportLoading\(false\)/);
  assert.match(clear, /setCsvExportLoading\(false\)/);
});

test('a queued message is delivered only to the chat it was queued in', async () => {
  const controller = await readFile(new URL('../src/useChatController.ts', import.meta.url), 'utf8');
  const queue = await readFile(new URL('../src/useActiveWorkQueue.ts', import.meta.url), 'utf8');

  assert.match(controller, /activeQueue\.enqueue\(input, policy, sessions\.currentId\(\)\)/);
  assert.match(controller, /queued\.sessionId === sessions\.currentId\(\)/);
  assert.match(queue, /sessionId = ''/);
});
