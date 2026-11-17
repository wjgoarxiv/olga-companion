import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';
import { caseNamesRenderer } from './helpers/render-case-names.mjs';

const {
  readCaseMeta, labelWithName, caseWithTitle, namesSummary, textUnits, setCaseMeta, getCaseMeta,
} = await import('../src/caseNames.ts');
const { deriveStepStates, deriveStatusLine } = await import('../src/shell/useStepState.ts');

const META = { title: '집유 배관망', display_names: { FP_001: '1번 유정 라인', N_001: '분리기' } };
const src = (name) => readFile(new URL(`../src/${name}`, import.meta.url), 'utf8');

test('a table name shows beside the OLGA label, and the label alone when there is none', () => {
  assert.equal(labelWithName('FP_001', META.display_names), '1번 유정 라인 (FP_001)');
  assert.equal(labelWithName('FP_002', META.display_names), 'FP_002');
  assert.equal(labelWithName('FP_001', undefined), 'FP_001');
  assert.equal(labelWithName('FP_001', { FP_001: 'FP_001' }), 'FP_001', 'a name that repeats the label adds nothing');
  assert.equal(caseWithTitle('net.genkey', META), '집유 배관망 (net.genkey)');
  assert.equal(caseWithTitle('net.genkey', null), 'net.genkey');
  assert.equal(namesSummary(META), '1번 유정 라인 (FP_001), 분리기 (N_001)');
  assert.equal(namesSummary(null), '');
  assert.equal(textUnits('분리기'), 6);
});

test('readCaseMeta drops what is not text and returns null for an old case', () => {
  assert.equal(readCaseMeta(undefined), null);
  assert.equal(readCaseMeta({}), null);
  assert.equal(readCaseMeta({ title: '  ', display_names: { A: 3 } }), null);
  assert.deepEqual(readCaseMeta({ title: ' 제목 ', display_names: { A: '이름', B: 3 } }), { title: '제목', display_names: { A: '이름' } });
});

const states = () => deriveStepStates({
  activeCaseName: 'net.genkey', tabCount: 1, hasRunOutputs: false, errorCount: 0, hasEvidence: true, preferredResultId: null,
});

test('the status line names the case by its title, and by the file name when there is none', () => {
  const named = deriveStatusLine({ states: states(), timeline: [], activeCaseName: 'net.genkey', caseMeta: META });
  assert.equal(named.key, 'stepbar.line.checked');
  assert.equal(named.params.case, '집유 배관망 (net.genkey)');
  const plain = deriveStatusLine({ states: states(), timeline: [], activeCaseName: 'net.genkey', caseMeta: null });
  assert.equal(plain.params.case, 'net.genkey');
  const old = deriveStatusLine({ states: states(), timeline: [], activeCaseName: 'old.genkey' });
  assert.equal(old.params.case, 'old.genkey', 'no meta anywhere: the OLGA name');
});

test('without an explicit meta the status line reads what the last topology load found', () => {
  setCaseMeta('net.genkey', readCaseMeta(META));
  try {
    assert.equal(deriveStatusLine({ states: states(), timeline: [], activeCaseName: 'net.genkey' }).params.case, '집유 배관망 (net.genkey)');
  } finally {
    setCaseMeta('net.genkey', null);
  }
  assert.equal(getCaseMeta('net.genkey'), null);
  assert.equal(deriveStatusLine({ states: states(), timeline: [], activeCaseName: 'net.genkey' }).params.case, 'net.genkey');
});

test('the step-state hook subscribes to the meta store so the line follows a new load', async () => {
  const hook = await src('shell/useStepState.ts');
  assert.match(hook, /subscribeCaseMeta/);
  assert.match(hook, /getCaseMeta\(/);
});

const RESULT = { id: 'run:abc/net.tpl', name: 'net.tpl', rel: 'abc/net.tpl', origin: 'run', size: 1, suffix: '.tpl', modified_ns: 1, run_id: 'abc', source_name: 'net.genkey', lineage_status: 'receipt_output', lineage: { kind: 'run_receipt' } };

test('the results header shows the case title and the table names, and the file name alone for an old case', async () => {
  const { renderReceipt } = await caseNamesRenderer();
  const named = renderReceipt('ko', { ...RESULT, case_meta: META });
  assert.match(named, /집유 배관망 \(net\.genkey\)/);
  assert.match(named, /1번 유정 라인 \(FP_001\)/);
  assert.match(named, /분리기 \(N_001\)/);
  const old = renderReceipt('ko', RESULT);
  assert.match(old, /net\.genkey/);
  assert.doesNotMatch(old, /집유 배관망|FP_001/);
  assert.equal(ko['results.metaNames'] === undefined, false);
  assert.equal(en['results.metaNames'] === undefined, false);
});

const NODES = [{ id: 'N_001', label: 'N_001', kind: 'SINK' }, { id: 'N_002', label: 'N_002', kind: 'SOURCE' }];
const EDGES = [{ source: 'N_002', target: 'N_001', label: 'FP_001', kind: 'FLOWPATH' }];

test('topology nodes and flowpaths show the table name with the OLGA name, and the OLGA name alone without one', async () => {
  const { renderTopology } = await caseNamesRenderer();
  const named = renderTopology('ko', { nodes: NODES, edges: EDGES, names: META.display_names });
  assert.match(named, /분리기 \(N_001\)/);
  assert.match(named, /1번 유정 라인 \(FP_001\)/);
  assert.match(named, /data-node-id="N_001"/, 'identity stays the OLGA label');
  const plain = renderTopology('ko', { nodes: NODES, edges: EDGES });
  assert.match(plain, /N_001/);
  assert.doesNotMatch(plain, /분리기/);
});

test('the workspace view hands the topology names to the map and the title to the header', async () => {
  const view = await src('WorkspaceView.tsx');
  assert.match(view, /names=\{topo\.meta\?\.display_names\}/);
  assert.match(view, /caseWithTitle\(/);
  assert.match(view, /setCaseMeta\(/);
  const api = await src('workspaceApi.ts');
  assert.match(api, /meta\?: CaseMeta/);
  const contracts = await src('resultContracts.ts');
  assert.match(contracts, /case_meta\?: CaseMeta/);
});

test('the profile branch picker names each branch by its table name, keeping the OLGA label as the value', async () => {
  const [panel, layout] = await Promise.all([src('ProfilePanel.tsx'), src('ResultsLayout.tsx')]);
  assert.match(panel, /value=\{name\}>\{labelWithName\(name, names\)\}<\/option>/);
  assert.match(layout, /names=\{selected\.case_meta\?\.display_names\}/);
});

test('ko and en carry the same new keys', () => {
  assert.equal(typeof ko['results.metaNames'], 'string');
  assert.equal(typeof en['results.metaNames'], 'string');
});
