import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import { rolldown } from 'rolldown';

import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';
import { presentPipeDraft } from '../src/pipeTableDraft.ts';
import { approvalCardRenderer } from './helpers/render-approval-card.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const cardPath = fileURLToPath(new URL('../src/PipeTableDraftCard.tsx', import.meta.url));
const i18nPath = fileURLToPath(new URL('../src/i18n/index.ts', import.meta.url));
const ENTRY = '\0draft-card-render-entry';
const entrySource = `
import React, { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import PipeTableDraftCard from ${JSON.stringify(cardPath)};
import { setLocale } from ${JSON.stringify(i18nPath)};
React.useSyncExternalStore = (_subscribe, getSnapshot) => getSnapshot();
export function renderDraft(locale, view) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(PipeTableDraftCard, { view }));
}
`;
const bundle = await rolldown({
  input: ENTRY,
  platform: 'node',
  plugins: [{
    name: 'draft-card-entry',
    resolveId: (id) => (id === ENTRY ? id : null),
    load: (id) => (id === ENTRY ? entrySource : null),
  }],
  resolve: { extensions: ['.tsx', '.ts', '.mjs', '.js'] },
  transform: { define: { 'process.env.NODE_ENV': '"production"' } },
});
const { output } = await bundle.generate({ format: 'esm' });
const dir = await mkdtemp(join(tmpdir(), 'draft-card-'));
await writeFile(join(dir, 'render.mjs'), output[0].code);
const { renderDraft } = await import(pathToFileURL(join(dir, 'render.mjs')).href);

const imported = {
  created: true,
  draft_id: 'a'.repeat(32),
  revision: 1,
  source_name: 'network.csv',
  counts: { flowpaths: 319, pipes: 900, junctions: 120, boundaries: 12, valves: 4, sections: 4210 },
  caps: {
    nodes: { value: 132, limit: 256 },
    flowpaths: { value: 319, limit: 512 },
    valves: { value: 4, limit: 20 },
    sections: { value: 4210, limit: 5000 },
  },
  section_stats: { shortest_section_m: 0.5, longest_section_m: 1, worst_ratio_in_flowpaths: 1.25 },
  junction_warning_count: 2,
  issue_count: 0,
  issues: [],
  initial_state: { pressure_pa: 600000, temperature_c: 20, stated: false },
  start_warning: { highest_pressure_pa: 1500000, lowest_pressure_pa: 600000 },
  pvt_missing: { reference: 'fluids/air_water.tab' },
  boundaries: [
    { name: 'SRC_001', node: 'WELL-A', kind: 'source' },
    { name: 'SNK_001', node: 'SEPARATOR', kind: 'sink' },
    { name: 'SRC_002', node: '', kind: 'source' },
    { name: 'CLS_001', node: 'DEAD-END', kind: 'closed' },
  ],
};

const afterDetails = (html) => html.slice(html.indexOf('<details class="pipe-draft-details"'));
const beforeDetails = (html) => html.slice(0, html.indexOf('<details class="pipe-draft-details"'));

test('the view lists source and sink names from the boundaries, table name first', () => {
  const view = presentPipeDraft('pipe_table_import', imported);
  assert.deepEqual(view.sources, ['WELL-A', 'SRC_002']);
  assert.deepEqual(view.sinks, ['SEPARATOR']);
  const bare = presentPipeDraft('case_draft_review', { ...imported, boundaries: undefined });
  assert.deepEqual([bare.sources, bare.sinks], [[], []]);
  const refused = presentPipeDraft('pipe_table_import', { created: false, issue_count: 1, issues: [{ row: 2, field: 'x', reason: 'bad' }] });
  assert.deepEqual([refused.sources, refused.sinks], [[], []]);
});

test('the first view is a short summary: counts, source and sink names, warnings', () => {
  const html = renderDraft('ko', presentPipeDraft('pipe_table_import', imported));
  const first = beforeDetails(html);
  assert.ok(first.includes('WELL-A, SRC_002'), 'source names read on the first view');
  assert.ok(first.includes('SEPARATOR'), 'sink names read on the first view');
  for (const label of ['플로패스', '파이프', '구간']) assert.ok(first.includes(`<dt>${label}</dt>`), `${label} count is summarised`);
  assert.ok(first.includes('fluids/air_water.tab'), 'the missing fluid table warning stays on the first view');
  assert.ok(first.includes(ko['pipeDraft.startWarning'].split('{')[0]), 'the start warning stays on the first view');
  assert.doesNotMatch(first, /pipe-draft-meter|pipe-draft-stats|evidence-diff-list/, 'dense sections are not on the first view');
});

test('the dense sections sit inside a collapsed details named 자세히 보기', () => {
  const html = renderDraft('ko', presentPipeDraft('pipe_table_import', {
    ...imported, applied: ['max section length 3 m'], page: 1, pages: 2,
    flowpaths: [{ label: 'FP_001', source_name: 'LINE-1', pipes: 3, sections: 40, from: 'J_001', to: 'J_002' }],
  }));
  const tag = html.match(/<details class="pipe-draft-details"[^>]*>/);
  assert.ok(tag, 'a details element carries the dense sections');
  assert.doesNotMatch(tag[0], /\sopen/, 'it starts collapsed');
  assert.match(html, /<summary[^>]*>자세히 보기<\/summary>/);
  const dense = afterDetails(html);
  for (const marker of ['pipe-draft-meter', 'pipe-draft-stats', 'pipe-draft-start', 'evidence-diff-list', 'evidence-table']) {
    assert.ok(dense.includes(marker), `${marker} moved into the details`);
  }
  assert.match(renderDraft('en', presentPipeDraft('pipe_table_import', imported)), /<summary[^>]*>Show details<\/summary>/);
});

test('a refusal keeps its issue list and shows no summary or details', () => {
  const html = renderDraft('ko', presentPipeDraft('pipe_table_import', {
    created: false, issue_count: 1, issues: [{ row: 2, field: 'length_m', reason: 'value is missing' }],
  }));
  assert.ok(html.includes('pipe-draft-issues'));
  assert.doesNotMatch(html, /pipe-draft-details|pipe-draft-summary/);
});

test('the card stays read-only and the network button stays on the first view', async () => {
  const card = await read('../src/PipeTableDraftCard.tsx');
  assert.doesNotMatch(card, /ApprovalCard|approvals\/execute|executeApproval|chat\.send|onDraft/);
  assert.doesNotMatch(card, /method:\s*'(POST|PUT|DELETE)'/);
  const html = renderDraft('en', presentPipeDraft('pipe_table_import', imported));
  const closed = html.slice(html.lastIndexOf('</details>'));
  assert.ok(closed.includes(en['pipeDraft.showNetwork']), 'the network button follows the details, not inside it');
  assert.ok(closed.includes(en['pipeDraft.nextStep']));
});

test('the summary wording exists in both languages with the same placeholders', () => {
  for (const key of ['pipeDraft.detailsSummary', 'pipeDraft.sources', 'pipeDraft.sinks', 'pipeDraft.namesMore']) {
    assert.ok(ko[key] && en[key], key);
    assert.match(ko[key], /[가-힣]/, `${key} is Korean`);
    assert.deepEqual([...ko[key].matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort(), [...en[key].matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort());
  }
  assert.equal(ko['pipeDraft.detailsSummary'], '자세히 보기');
  assert.doesNotMatch(ko['pipeDraft.sources'] + ko['pipeDraft.sinks'] + ko['pipeDraft.namesMore'], /워크스페이스|케이스/);
});

test('the details and summary use tokens, a 44px target and no literal colours', async () => {
  const css = await read('../src/styles/pipe-draft.css');
  assert.match(css, /\.pipe-draft-details > summary \{[^}]*min-height: var\(--tgt\)/);
  assert.match(css, /\.pipe-draft-summary/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/);
  assert.doesNotMatch(css, /border-radius: [1-9]/);
});

const renderApproval = await approvalCardRenderer();
const publish = {
  name: 'case_publish',
  call_id: 'call_publish',
  pending_id: 'pending_publish',
  args: {
    transaction_id: 'tx_1', compiled_hash: 'b'.repeat(64), destination_rel: 'cases/pipe/network.genkey', context_generation: 3,
  },
  display: { inputs: [] },
};

test('the save approval card opens with one plain sentence about what is saved where', () => {
  const ko_html = renderApproval('ko', publish);
  const sentence = '<p class="approval-plain">network.genkey을(를) cases/pipe에 새로 저장합니다.</p>';
  assert.ok(ko_html.includes(sentence), 'ko sentence');
  assert.ok(ko_html.indexOf(sentence) < ko_html.indexOf('<dl'), 'the sentence comes before the audit fields');
  assert.ok(ko_html.indexOf('approval-head') < ko_html.indexOf(sentence));
  assert.ok(ko_html.includes('컴파일 SHA-256'), 'the audit fields stay after it');
  assert.ok(ko_html.includes('cases/pipe/network.genkey'), 'the full destination stays as an audit field');
  const en_html = renderApproval('en', publish);
  assert.ok(en_html.includes('<p class="approval-plain">This saves network.genkey as a new case in cases/pipe.</p>'));
  assert.ok(renderApproval('ko', { ...publish, args: { ...publish.args, destination_rel: 'network.genkey' } })
    .includes('network.genkey을(를) 작업 공간에 새로 저장합니다.'), 'a file at the root names the workspace');
});

test('no sentence without a destination, and other cards are unchanged', () => {
  assert.doesNotMatch(renderApproval('ko', { ...publish, args: { ...publish.args, destination_rel: '' } }), /approval-plain/);
  assert.doesNotMatch(renderApproval('ko', { name: 'run_cancel', call_id: 'c', pending_id: 'p', args: {}, display: {} }), /approval-plain/);
});

test('the save button names its effect', () => {
  assert.ok(renderApproval('ko', publish).includes('>승인하고 사례 저장<'));
  assert.ok(renderApproval('en', publish).includes('>Approve and save the case<'));
});

test('the sentence has wording in both languages and styles with tokens', async () => {
  for (const key of ['approval.publishPlain', 'approval.publishPlainRoot']) {
    assert.ok(ko[key] && en[key], key);
    assert.match(ko[key], /[가-힣]/);
  }
  assert.match(ko['approval.publishPlain'], /\{file\}.*\{folder\}/);
  assert.match(en['approval.publishPlain'], /\{file\}.*\{folder\}/);
  const css = await read('../src/styles/chat-tools.css');
  assert.match(css, /\.approval-plain \{[^}]*font-size: var\(--fs-m\)/);
  assert.doesNotMatch(css.match(/\.approval-plain \{[^}]*\}/)[0], /#[0-9a-fA-F]{3,8}\b|border-radius: [1-9]/);
});
