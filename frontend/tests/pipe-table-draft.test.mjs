import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import test from 'node:test';

import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';
import { expandDraftNetwork, presentPipeDraft } from '../src/pipeTableDraft.ts';
import { buildFlowpathProjection } from '../src/flowpathGeometry.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const counts = { flowpaths: 319, pipes: 900, junctions: 120, boundaries: 12, valves: 4, sections: 4210 };
const caps = {
  nodes: { value: 132, limit: 256 },
  flowpaths: { value: 319, limit: 512 },
  valves: { value: 4, limit: 20 },
  sections: { value: 4210, limit: 5000 },
};
const imported = {
  created: true,
  draft_id: 'a'.repeat(32),
  revision: 1,
  source_name: 'network.csv',
  counts,
  caps,
  section_stats: { shortest_section_m: 0.5, longest_section_m: 1, worst_ratio_in_flowpaths: 1.25 },
  junction_warning_count: 2,
  issue_count: 0,
  issues: [],
};
const refused = {
  created: false,
  issue_count: 31,
  issues: [{ row: 5, field: 'length_m', reason: 'value is missing' }, { row: null, field: 'topology', reason: 'not connected' }],
  note: 'No draft was made. The table needs these fixes first.',
};

test('an import becomes a ready draft view with counts, caps and section statistics', () => {
  const view = presentPipeDraft('pipe_table_import', imported);
  assert.equal(view.ready, true);
  assert.equal(view.draftId, imported.draft_id);
  assert.deepEqual(view.counts, counts);
  assert.deepEqual(view.caps.map((cap) => cap.key), ['nodes', 'flowpaths', 'valves', 'sections']);
  assert.equal(view.caps.find((cap) => cap.key === 'sections').near, false);
  assert.equal(view.shortest, 0.5);
  assert.equal(view.longest, 1);
  assert.equal(view.worstRatio, 1.25);
  assert.equal(view.junctionWarnings, 2);
});

test('a cap at ninety percent or more reads as near its limit', () => {
  const view = presentPipeDraft('pipe_table_import', {
    ...imported, caps: { ...caps, sections: { value: 4600, limit: 5000 } },
  });
  assert.equal(view.caps.find((cap) => cap.key === 'sections').near, true);
});

test('an import with issues shows the issue list and no ready state', () => {
  const view = presentPipeDraft('pipe_table_import', refused);
  assert.equal(view.ready, false);
  assert.equal(view.counts, null);
  assert.equal(view.draftId, '');
  assert.equal(view.issueCount, 31);
  assert.deepEqual(view.issues[0], { row: 5, field: 'length_m', reason: 'value is missing', code: '', params: {} });
  const coded = presentPipeDraft('pipe_table_import', {
    created: false,
    issue_count: 1,
    issues: [{ row: 4, field: 'diameter_m', reason: 'value is missing', code: 'value_missing', params: { field: 'diameter_m' } }],
  });
  assert.deepEqual(coded.issues[0], { row: 4, field: 'diameter_m', reason: 'value is missing', code: 'value_missing', params: { field: 'diameter_m' } });
  assert.equal(view.issues[1].row, null);
});

test('a draft that carries issues is never ready', () => {
  const view = presentPipeDraft('case_draft_edit', { ...imported, issues: refused.issues, issue_count: 2 });
  assert.equal(view.ready, false);
});

test('review pages and edit receipts keep their extra fields', () => {
  const review = presentPipeDraft('case_draft_review', {
    ...imported,
    page: 2,
    pages: 7,
    flowpaths: [{ label: 'FP_051', source_name: 'LINE-51', pipes: 3, sections: 40, from: 'J_001', to: 'J_002' }],
  });
  assert.deepEqual(review.page, {
    page: 2,
    pages: 7,
    rows: [{ label: 'FP_051', sourceName: 'LINE-51', from: 'J_001', to: 'J_002', pipes: 3, sections: 40 }],
  });
  const edit = presentPipeDraft('case_draft_edit', { ...imported, revision: 2, applied: ['max section length 3 m'] });
  assert.equal(edit.revision, 2);
  assert.deepEqual(edit.applied, ['max section length 3 m']);
});

test('other tools and malformed payloads do not become a draft card', () => {
  assert.equal(presentPipeDraft('genkey_review', imported), null);
  assert.equal(presentPipeDraft('pipe_table_import', { draft_id: 'x' }), null);
  assert.equal(presentPipeDraft('pipe_table_import', { ...imported, counts: { flowpaths: 'many' } }), null);
  assert.equal(presentPipeDraft('pipe_table_import', { created: false, issues: [] }), null);
});

test('the compact draft topology expands into the map nodes and edges', () => {
  const network = expandDraftNetwork({
    kinds: ['source', 'junction', 'sink'],
    nodes: [['SRC_001', 0], ['J_001', 1], ['SNK_001', 2]],
    edges: [[0, 1, 'FP_001'], [1, 2, 'FP_002']],
  });
  assert.deepEqual(network.nodes.map((node) => node.kind), ['SOURCE', 'NODE', 'SINK']);
  assert.deepEqual(network.edges[1], { source: 'J_001', target: 'SNK_001', label: 'FP_002', kind: 'FLOWPATH' });
  assert.deepEqual(network.counts, { nodes: 3, flowpaths: 2, edges: 2 });
  assert.equal(expandDraftNetwork({ kinds: [], nodes: [], edges: [[0, 1, 'x']] }), null);
  assert.equal(expandDraftNetwork(null), null);
});

test('the card is chosen by the evidence block for the three draft tools', async () => {
  const [evidence, card] = await Promise.all([read('../src/EvidenceBlock.tsx'), read('../src/PipeTableDraftCard.tsx')]);
  assert.match(evidence, /import PipeTableDraftCard/);
  assert.match(evidence, /presentPipeDraft\(name, result\)/, 'the card is picked from the tool name and result shape');
  assert.match(evidence, /<PipeTableDraftCard/);
  assert.match(card, /presentPipeDraft|PipeDraftView/);
  for (const tool of ['pipe_table_import', 'case_draft_review', 'case_draft_edit']) {
    assert.match(await read('../src/pipeTableDraft.ts'), new RegExp(tool));
  }
});

test('the card shows counts, the cap check, section statistics, issues and no ready state for a refusal', async () => {
  const card = await read('../src/PipeTableDraftCard.tsx');
  for (const key of ['pipeDraft.readyTitle', 'pipeDraft.countsAria', 'pipeDraft.capsTitle', 'pipeDraft.capsOk', 'pipeDraft.capsNear',
    'pipeDraft.statsTitle', 'pipeDraft.stat.shortest', 'pipeDraft.stat.longest', 'pipeDraft.stat.ratio', 'pipeDraft.issuesTitle',
    'pipeDraft.issuesAria', 'pipeDraft.junctionWarnings', 'pipeDraft.appliedTitle', 'pipeDraft.pageSummary']) {
    assert.ok(card.includes(`'${key}'`), `the card uses ${key}`);
  }
  assert.match(card, /view\.ready/, 'the ready state is gated on the view');
  assert.match(card, /view\.ready \? t\('pipeDraft\.readyTitle'\) : t\('pipeDraft\.issuesTitle'\)/, 'a refusal never reads as ready');
  assert.match(card, /view\.ready && view\.counts/, 'counts, caps and statistics need a ready draft');
  assert.match(card, /view\.issues\.map/, 'the issue list renders');
});

test('Show network opens the existing topology map from the draft graph route', async () => {
  const card = await read('../src/PipeTableDraftCard.tsx');
  assert.match(card, /import TopologyMap/);
  assert.match(card, /\/api\/case-draft\/\$\{encodeURIComponent\(view\.draftId\)\}\/topology/);
  assert.match(card, /apiFetch\(/);
  assert.match(card, /expandDraftNetwork\(/);
  assert.match(card, /aria-expanded=\{open\}/);
  assert.match(card, /t\('pipeDraft\.showNetwork'\)/);
  assert.match(card, /t\('pipeDraft\.hideNetwork'\)/);
  assert.match(card, /response\.status === 404 \|\| response\.status === 409/, 'an expired or foreign draft says so');
  assert.match(card, /pipeDraft\.networkGone/);
  assert.match(card, /pipeDraft\.networkRetry/);
  assert.match(card, /<TopologyMap/);
  assert.match(card, /AbortController/, 'closing or leaving cancels the request');
});

test('the card adds no approval card and never sends or approves anything', async () => {
  const card = await read('../src/PipeTableDraftCard.tsx');
  assert.doesNotMatch(card, /ApprovalCard|approvals\/execute|executeApproval|chat\.send|onDraft/);
  assert.doesNotMatch(card, /method:\s*'(POST|PUT|DELETE)'/, 'the preview only reads');
});

test('every key the card and the profile mode use exists in both languages with real text', async () => {
  const sources = await Promise.all([
    read('../src/PipeTableDraftCard.tsx'), read('../src/FlowpathGeometryViewer.tsx'),
  ]);
  const used = new Set();
  for (const source of sources) {
    for (const match of source.matchAll(/t\('((?:pipeDraft|flowpath\.profile)[\w.]*)'/g)) used.add(match[1]);
  }
  assert.ok(used.size >= 30, `the card and viewer use many keys (${used.size})`);
  for (const key of used) {
    assert.ok(key in ko, `ko has ${key}`);
    assert.ok(key in en, `en has ${key}`);
    assert.notEqual(ko[key], key);
    assert.notEqual(en[key], key);
  }
  const mine = (dictionary) => Object.keys(dictionary).filter((key) => key.startsWith('pipeDraft.') || key.startsWith('flowpath.profile')).sort();
  assert.deepEqual(mine(ko), mine(en), 'ko and en carry the same pipe-draft keys');
  for (const key of mine(ko)) {
    const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
    assert.deepEqual(placeholders(ko[key]), placeholders(en[key]), `${key} keeps the same placeholders`);
    assert.match(ko[key], /[가-힣]/, `${key} is Korean in ko`);
  }
});

test('the profile mode draws only the elevation profile for length-and-elevation data', async () => {
  const [viewer, panel, api] = await Promise.all([
    read('../src/FlowpathGeometryViewer.tsx'), read('../src/FlowpathDetailPanel.tsx'), read('../src/workspaceApi.ts'),
  ]);
  assert.match(api, /source\?: 'length_elevation'/, 'the details type knows the source');
  assert.match(panel, /geometry\.source === 'length_elevation'/);
  assert.match(panel, /profileOnly=/);
  assert.match(viewer, /profileOnly/);
  assert.match(viewer, /flowpath\.profileBadge/);
  assert.match(viewer, /flowpath\.profileNote/);
  assert.match(viewer, /flowpath\.profileCaption/);
  assert.match(viewer, /profileOnly \? /, 'the plan and isometric switch is replaced by the profile label');
});

test('a length-and-elevation section list projects to a profile of length against height', () => {
  const sections = [0, 1, 2, 3].map((index) => ({
    section_index: index,
    pipe_section_index: index + 1,
    pipe_label: 'P1',
    length_m: 10,
    diameter_m: 0.1,
    chainage_start_m: index * 10,
    chainage_end_m: (index + 1) * 10,
    start: { x_m: index * 9, y_m: index * 4, z_m: 0 },
    center: { x_m: index * 9 + 4.5, y_m: index * 4 + 2, z_m: 0 },
    end: { x_m: (index + 1) * 9, y_m: (index + 1) * 4, z_m: 0 },
  }));
  const projection = buildFlowpathProjection(sections, { view: 'elevation', width: 960, height: 560, padding: 56, elevationExaggeration: 1 });
  const first = projection.segments[0];
  const last = projection.segments[3];
  assert.ok(last.end.x > first.start.x, 'distance along the pipe runs left to right');
  assert.ok(last.end.y < first.start.y, 'a rising pipe climbs up the screen');
  const run = projection.segments.map((segment) => segment.end.x - segment.start.x);
  assert.ok(run.every((value) => Math.abs(value - run[0]) < 1e-6), 'equal lengths make equal steps along x');
});

test('the shell, App.tsx and the copy stay inside their rules', async () => {
  const app = await read('../src/App.tsx');
  const codeLines = app.split('\n').filter((line) => line.trim() && !line.trim().startsWith('//')).length;
  assert.ok(codeLines <= 250, `App.tsx stays under its line cap (${codeLines})`);
  assert.doesNotMatch(app, /PipeTableDraft/, 'App.tsx is untouched by the draft card');
  const files = [];
  const walk = async (directory) => {
    for (const entry of await readdir(new URL(directory, import.meta.url), { withFileTypes: true })) {
      if (entry.isDirectory()) await walk(`${directory}${entry.name}/`);
      else if (/\.(tsx?|mjs|css)$/.test(entry.name)) files.push(`${directory}${entry.name}`);
    }
  };
  await walk('../src/');
  for (const file of files) {
    assert.doesNotMatch(await read(file), /migrat|provenance/i, `${file} avoids the banned words`);
  }
});

test('the draft styles use tokens only and cover the meter, issues and the map', async () => {
  const css = await read('../src/styles/pipe-draft.css');
  assert.match(await read('../src/styles.css'), /@import '\.\/styles\/pipe-draft\.css';/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/, 'no literal colours');
  for (const selector of ['.pipe-draft', '.pipe-draft-meter', '.pipe-draft-issues', '.pipe-draft-map']) {
    assert.ok(css.includes(selector), `${selector} is styled`);
  }
  assert.match(css, /prefers-reduced-motion/);
});

test('the start state reads in bar and a guessed start on a large drop carries its warning', () => {
  const guessed = presentPipeDraft('pipe_table_import', {
    ...imported,
    initial_state: { pressure_pa: 600000, temperature_c: 20, stated: false },
    start_warning: { highest_pressure_pa: 1500000, lowest_pressure_pa: 600000 },
  });
  assert.deepEqual(guessed.start, { pressureBar: 6, temperatureC: 20, stated: false });
  assert.deepEqual(guessed.startWarning, { highestBar: 15, lowestBar: 6 });

  const stated = presentPipeDraft('pipe_table_import', {
    ...imported, initial_state: { pressure_pa: 1000000, temperature_c: 30, stated: true }, start_warning: null,
  });
  assert.equal(stated.start.stated, true);
  assert.equal(stated.startWarning, null);
  assert.equal(presentPipeDraft('pipe_table_import', imported).start, null);
});

test('the start state has wording in both languages', () => {
  for (const key of ['pipeDraft.startTitle', 'pipeDraft.start.pressure', 'pipeDraft.start.temperature',
    'pipeDraft.startStated', 'pipeDraft.startGuessed', 'pipeDraft.startWarning']) {
    assert.ok(en[key], key);
    assert.ok(ko[key], key);
  }
});

test('the start-state labels keep the unit in lower case', async () => {
  // Metric labels are set in capitals, which printed the unit as BAR.
  const card = await read('../src/PipeTableDraftCard.tsx');
  const css = await read('../src/styles/pipe-draft.css');
  assert.match(card, /className="evidence-metrics pipe-draft-stats pipe-draft-start"/);
  assert.match(css, /\.pipe-draft-start dt \{[^}]*text-transform: none/);
});

test('the Korean draft card names the workspace as the shell does', () => {
  const draft = Object.entries(ko).filter(([key]) => key.startsWith('pipeDraft.'));
  assert.deepEqual(draft.filter(([, value]) => value.includes('워크스페이스')).map(([key]) => key), []);
});
