import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';
import { translate } from '../src/i18n/index.ts';
import { modifiedLabel, pickAutoSelectResult, plainVariableName } from '../src/resultPresentation.ts';
import { nodeLabelFontSize, pickCountKey } from '../src/topologyText.ts';
import { formatRunReason, formatRunReasonParts, runStateLabel } from '../src/runReason.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function tKo(key, vars) {
  return translate('ko', key, vars);
}

function tEn(key, vars) {
  return translate('en', key, vars);
}

// ── 4. Workspace: full file names (no mid-truncation; wrap 2 lines + tooltip) ──

test('explorer and results rows render the full stem, not a mid-truncation', async () => {
  const [explorer, rail] = await Promise.all([
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/ResultsInventoryRail.tsx'),
  ]);
  for (const [label, source] of [['ExplorerPanel', explorer], ['ResultsInventoryRail', rail]]) {
    assert.doesNotMatch(source, /displayStem/, `${label} must not mid-truncate the stem`);
  }
  assert.match(explorer, /className="wb-explorer-name"/, 'the tree keeps the stem element');
  assert.match(explorer, /className="wb-explorer-ext"/, 'the tree keeps the extension pinned');
  assert.match(rail, /className="case-name-stem"/, 'results keep the stem element');
  assert.match(rail, /className="case-name-extension"/, 'results keep the extension pinned');
  assert.match(explorer, /title=\{item\.name\}/, 'tree rows keep the full-name tooltip');
  assert.match(rail, /title=\{`?\$\{f\.name\}/, 'results rows keep the full-name tooltip');
});

test('workspace file rows wrap to two lines with meta on a secondary line', async () => {
  const css = await read('../src/styles/workspace.css');
  assert.match(css, /\.ws-file-name\s*\{[^}]*white-space:\s*normal/s, 'name wraps instead of single-line ellipsis');
  assert.match(css, /-webkit-line-clamp:\s*2/, 'name wraps to at most two lines');
  assert.match(css, /\.ws-file\s*\{[^}]*flex-direction:\s*column/s, 'type/size meta drops to a secondary line');
});

// ── 4. Workspace: graph label scale + counts ─────────────────────────────────

test('graph node font scales with the canvas inside a clamped range', () => {
  const tiny = nodeLabelFontSize(452, 1000);
  const normal = nodeLabelFontSize(1000, 1000);
  assert.ok(tiny < normal, `small content on a wide canvas shrinks the label (got ${tiny} vs ${normal})`);
  assert.ok(tiny >= 12 && tiny <= 18, `clamped small size (got ${tiny})`);
  assert.ok(normal >= 12 && normal <= 18, `clamped normal size (got ${normal})`);
  assert.equal(nodeLabelFontSize(1000, 0), 13, 'degenerate canvas width falls back to the base size');
  assert.equal(nodeLabelFontSize(40, 1000), 12, 'extreme zoom-out clamps at the 12 px floor');
  assert.equal(nodeLabelFontSize(4000, 500), 18, 'extreme zoom-in clamps at the maximum');
});

test('topology map applies the scaled label size', async () => {
  const [map, css] = await Promise.all([
    read('../src/TopologyMap.tsx'),
    read('../src/styles/chat-responsive.css'),
  ]);
  assert.match(map, /nodeLabelFontSize/, 'map computes the scaled label size');
  assert.match(map, /--topo-node-fs/, 'map exposes the size as a CSS variable');
  assert.match(css, /var\(--topo-node-fs/, 'node labels read the scaled size');
});

test('graph counts use t() with correct singular/plural in en', () => {
  assert.equal(tEn('workspace.node_one', { count: 1 }), '1 node');
  assert.equal(tEn('workspace.node_other', { count: 2 }), '2 nodes');
  assert.equal(tEn('workspace.flowpath_one', { count: 1 }), '1 flowpath');
  assert.equal(tEn('workspace.flowpath_other', { count: 2 }), '2 flowpaths');
  assert.ok(String(tKo('workspace.node_other', { count: 2 })).includes('2'), 'ko node count interpolates');
  assert.ok(String(tKo('workspace.flowpath_one', { count: 1 })).includes('1'), 'ko flowpath count interpolates');
  assert.equal(pickCountKey('workspace.node', 1), 'workspace.node_one');
  assert.equal(pickCountKey('workspace.node', 2), 'workspace.node_other');
  assert.equal(pickCountKey('workspace.flowpath', 1), 'workspace.flowpath_one');
});

test('topology footer counts and hint come from the dictionary, shown once', async () => {
  const [workspace, map] = await Promise.all([
    read('../src/WorkspaceView.tsx'),
    read('../src/TopologyMap.tsx'),
  ]);
  assert.match(map, /t\(pickCountKey\('workspace\.node'/, 'footer node count uses t()');
  assert.match(map, /t\(pickCountKey\('workspace\.flowpath'/, 'footer flowpath count uses t()');
  assert.doesNotMatch(workspace, /ws-canvas-meta/, 'counts are not repeated in the canvas head');
  assert.doesNotMatch(workspace, /flowpaths<\/span>/, 'header no longer hardcodes the plural');
  assert.match(map, /t\('workspace\.graphHint'\)/, 'footer hint uses t()');
  assert.match(map, /t\('workspace\.graphTruncated'\)/, 'subset note uses t()');
  assert.match(map, /t\('workspace\.graphEmpty'\)/, 'empty-graph note uses t()');
  assert.doesNotMatch(map, /drag to rearrange/, 'footer hint is not hardcoded English');
});

// ── 5. Results: auto-select newest output of the active case ─────────────────

function resultFile(overrides) {
  return {
    id: 'x',
    name: 'case.tpl',
    rel: 'case.tpl',
    origin: 'run',
    size: 10,
    suffix: '.tpl',
    modified_ns: 1,
    source_name: 'case.genkey',
    ...overrides,
  };
}

test('auto-select picks the newest output of the active case only', () => {
  const old = resultFile({ id: 'old', modified_ns: 100 });
  const newest = resultFile({ id: 'new', modified_ns: 300 });
  const other = resultFile({ id: 'other', modified_ns: 500, source_name: 'other.genkey' });
  const pool = [old, other, newest];
  assert.equal(pickAutoSelectResult(pool, 'case.genkey', {}).id, 'new', 'newest output of the active case');
  assert.equal(
    pickAutoSelectResult(pool, 'case.genkey', { selectedId: 'old' }),
    null,
    'never overrides an existing selection',
  );
  assert.equal(
    pickAutoSelectResult(pool, 'case.genkey', { preferredId: 'other' }),
    null,
    'a preferred (deep-linked) result wins over auto-select',
  );
  assert.equal(pickAutoSelectResult(pool, null, {}), null, 'no active case means no auto-select');
  assert.equal(pickAutoSelectResult(pool, 'missing.genkey', {}), null, 'no outputs for the case means no auto-select');
  assert.equal(pickAutoSelectResult([], 'case.genkey', {}), null, 'empty inventory means no auto-select');
});

test('results view auto-selects on open without overriding a choice', async () => {
  const view = await read('../src/ResultsView.tsx');
  assert.match(view, /pickAutoSelectResult/, 'inventory load considers the active case newest output');
});

test('results rail, header, prompts and receipt meta read from the dictionary', async () => {
  const [rail, layout, prompts, meta] = await Promise.all([
    read('../src/ResultsInventoryRail.tsx'),
    read('../src/ResultsLayout.tsx'),
    read('../src/ResultsPrompts.tsx'),
    read('../src/ResultReceiptMeta.tsx'),
  ]);
  assert.match(rail, /t\('results\./, 'rail uses t()');
  assert.doesNotMatch(rail, /Filter by file or run/, 'rail filter placeholder is not hardcoded');
  assert.doesNotMatch(rail, /of \$\{results\.length\} outputs/, 'rail count is not hardcoded');
  assert.doesNotMatch(rail, /No outputs match/, 'rail empty-filter copy is not hardcoded');
  assert.match(layout, /t\('results\./, 'header uses t()');
  assert.doesNotMatch(layout, /Filter variables/, 'variable filter label is not hardcoded');
  assert.doesNotMatch(layout, /Overlay up to five variables/, 'overlay hint is not hardcoded');
  assert.match(prompts, /t\('results\./, 'prompts use t()');
  assert.match(meta, /t\('results\./, 'receipt meta uses t()');
});

// ── 5. Run: reason by code, no contradiction, labels through t() ─────────────

function detect(overrides) {
  return {
    detected: true,
    source: 'install',
    exe: '/opt/olga/bin/olga',
    kind: 'engine',
    searched: [],
    version: '2022.1.0',
    candidate_id: 'c1',
    runtime_id: 'r1',
    selection_status: 'selected',
    rationale: 'No run record exists for this case; selected the newest installed direct OLGA engine (2022.1.0).',
    required_version: null,
    candidates: [],
    alternatives: [],
    evidence: [],
    case_source: 'case.genkey',
    ...overrides,
  };
}

test('run environment reason renders by code with fallback to the legacy text', () => {
  const legacy = detect({ reason_code: undefined });
  assert.equal(formatRunReason(legacy, tEn), legacy.rationale, 'no code falls back to the backend text');
  const coded = detect({ reason_code: 'some_future_code', reason_params: {} });
  const generic = formatRunReason(coded, tEn);
  assert.ok(generic.includes('some_future_code'), 'generic translated line carries the code');
  assert.doesNotMatch(generic, /No run record exists/, 'generic line does not repeat the legacy claim');
  const genericKo = formatRunReason(coded, tKo);
  assert.ok(genericKo.includes('some_future_code'), 'ko generic line carries the code');
});

test('run environment line never claims no record exists above a recovered record', () => {
  const legacy = detect({ reason_code: undefined });
  const line = formatRunReason(legacy, tEn, { hasRecoveredRecord: true });
  assert.doesNotMatch(line, /No run record exists/, 'no contradiction with the recovered record');
  assert.ok(line.includes('2022.1.0'), 'line still names the selected engine');
  const codedNoRecord = detect({ reason_code: 'no_run_record_fallback' });
  const line2 = formatRunReason(codedNoRecord, tKo, { hasRecoveredRecord: true });
  assert.ok(!line2.includes('No run record exists'), 'coded no-record claim is suppressed too');
});

test('real error codes still display their own reason above a recovered record', () => {
  for (const [code, params, [koBit, enBit]] of [
    ['override_not_found', {}, ['가리키지 않습니다', 'does not point to a real file']],
    ['missing_required_version', { required_version: '2022.1.0' }, ['설치되어 있지 않습니다', 'is not installed']],
  ]) {
    const koLine = formatRunReason(detect({ reason_code: code, reason_params: params }), tKo, { hasRecoveredRecord: true });
    assert.ok(koLine.includes(koBit), `${code} keeps its ko reason (${koLine})`);
    assert.doesNotMatch(koLine, / · /, `${code} is not hidden behind the engine line`);
    const enLine = formatRunReason(detect({ reason_code: code, reason_params: params }), tEn, { hasRecoveredRecord: true });
    assert.ok(enLine.includes(enBit), `${code} keeps its en reason (${enLine})`);
    assert.doesNotMatch(enLine, / · /, `${code} is not hidden behind the engine line`);
  }
});

test('every backend reason code renders in both locales with params', () => {
  const cases = [
    ['no_candidate_found', {}, ['설치된', 'No installed']],
    ['conflicting_evidence', { versions: ['2019.1.0', '2022.1.0'] }, ['2019.1.0, 2022.1.0', 'multiple versions']],
    ['override_not_found', {}, ['OLGA_EXE_PATH', 'OLGA_EXE_PATH']],
    ['override_version_mismatch', { override_version: '2021.1.0', required_version: '2022.1.0' }, ['2021.1.0', '2022.1.0']],
    ['missing_required_version', { required_version: '2022.1.0' }, ['2022.1.0', '2022.1.0']],
    ['selected_override', {}, ['지정한', 'pinned']],
    ['selected_required_version', { version: '2022.1.0' }, ['2022.1.0', '2022.1.0']],
    ['no_run_record_available', {}, ['판독', 'could not be read']],
    ['no_run_record_newest_direct', { version: '2022.1.0' }, ['2022.1.0', 'newest installed direct']],
    ['no_run_record_newest_available', { version: '2022.1.0' }, ['2022.1.0', 'newest available']],
  ];
  for (const [code, params, [koBit, enBit]] of cases) {
    const line = formatRunReason(detect({ reason_code: code, reason_params: params }), tKo);
    assert.ok(line.includes(koBit), `${code} renders ko (${line})`);
    const enLine = formatRunReason(detect({ reason_code: code, reason_params: params }), tEn);
    assert.ok(enLine.includes(enBit), `${code} renders en (${enLine})`);
  }
});

test('stale codes under selected_candidate render reference-only', () => {
  const stale = detect({ reason_code: 'selected_required_version', reason_params: { version: '2022.1.0' }, selection_status: 'selected_candidate' });
  const line = formatRunReason(stale, tEn);
  assert.ok(line.includes('selected_required_version'), 'code stays as a reference');
  assert.doesNotMatch(line, /with strong evidence/, 'no possibly-stale specific claim');
  const fresh = detect({ reason_code: 'selected_required_version', reason_params: { version: '2022.1.0' }, selection_status: 'selected' });
  assert.ok(formatRunReason(fresh, tEn).includes('strong evidence'), 'fresh codes keep the specific line');
});

test('detection block shows a human sentence with the code in details only', () => {
  const stale = detect({ reason_code: 'selected_required_version', reason_params: { version: '2022.1.0' }, selection_status: 'selected_candidate' });
  const koParts = formatRunReasonParts(stale, tKo);
  assert.ok(koParts.text.includes('실행 환경'), 'ko shows the human sentence');
  assert.doesNotMatch(koParts.text, /selected_required_version/, 'the sentence carries no raw code');
  assert.equal(koParts.code, 'selected_required_version', 'the code stays available for details');
  const enParts = formatRunReasonParts(stale, tEn);
  assert.ok(enParts.text.includes('run environment'), 'en shows the human sentence');
  assert.doesNotMatch(enParts.text, /selected_required_version/, 'en sentence carries no raw code');
  const fresh = detect({ reason_code: 'selected_required_version', reason_params: { version: '2022.1.0' }, selection_status: 'selected' });
  const freshParts = formatRunReasonParts(fresh, tEn);
  assert.ok(freshParts.text.includes('strong evidence'), 'fresh codes keep the specific line');
  assert.equal(freshParts.code, null, 'fresh specific lines need no code details');
  const unknown = detect({ reason_code: 'some_future_code', reason_params: {}, selection_status: 'selected' });
  const unknownParts = formatRunReasonParts(unknown, tKo);
  assert.doesNotMatch(unknownParts.text, /some_future_code/, 'unknown codes never leak into the sentence');
  assert.equal(unknownParts.code, 'some_future_code', 'unknown codes stay available for details');
});

test('detection block renders the sentence with the code in a details element', async () => {
  const overview = await read('../src/RunViewOverview.tsx');
  assert.match(overview, /formatRunReasonParts/, 'the block splits sentence from code');
  assert.match(overview, /<details/, 'the code lives in a details disclosure');
  assert.match(overview, /t\('run\.reason\.codeLabel'\)/, 'the disclosure has a dictionary label');
});

test('run state words come from the dictionary', () => {
  assert.equal(runStateLabel('completed', tEn), tEn('run.state.completed'));
  assert.equal(runStateLabel('ready', tKo), tKo('run.state.ready'));
  assert.equal(runStateLabel('mystery_state', tEn), 'mystery_state', 'unknown states pass through');
});

test('run views read labels from the dictionary', async () => {
  const [view, overview, single, sweep, sweepStatus, failure, progress] = await Promise.all([
    read('../src/RunView.tsx'),
    read('../src/RunViewOverview.tsx'),
    read('../src/RunSingleCasePanel.tsx'),
    read('../src/RunSweepPanel.tsx'),
    read('../src/RunSweepStatus.tsx'),
    read('../src/RunFailurePanel.tsx'),
    read('../src/RunProgress.tsx'),
  ]);
  assert.match(view, /t\('run\.singleCase'\)/, 'mode tab uses t()');
  assert.doesNotMatch(view, />Single case</, 'mode tab is not hardcoded');
  assert.match(overview, /formatRunReason/, 'environment line renders by code');
  assert.doesNotMatch(overview, /\{detect\.rationale/, 'raw rationale is not rendered directly');
  assert.match(single, /t\('run\./, 'single-case panel uses t()');
  assert.match(sweep, /t\('run\./, 'sweep panel uses t()');
  assert.match(sweepStatus, /t\('run\./, 'sweep status uses t()');
  assert.match(failure, /t\('run\.receipt'\)/, 'receipt title uses t()');
  assert.doesNotMatch(failure, /title="Run receipt"/, 'receipt title is not hardcoded');
  assert.match(progress, /t\('run\./, 'progress labels use t()');
});

test('dates follow the selected locale in Results/Run', () => {
  const ns = Date.UTC(2026, 9, 23, 10, 40) * 1_000_000;
  const koLine = modifiedLabel(ns, 'ko');
  assert.match(koLine, /2026\. 10\. 23\./, `ko date uses the ko-KR shape (${koLine})`);
  const enLine = modifiedLabel(ns, 'en');
  assert.match(enLine, /Oct 23, 2026/, `en date uses the en-US shape (${enLine})`);
  assert.match(enLine, /AM|PM/, 'en date uses the English day period');
  assert.notEqual(koLine, enLine, 'locale changes the rendering');
  assert.equal(modifiedLabel(Number.NaN, 'ko'), tKo('results.timeUnavailable'));
  assert.equal(modifiedLabel(Number.NaN, 'en'), tEn('results.timeUnavailable'));
});

test('variable meanings follow the selected locale', () => {
  assert.equal(plainVariableName('PT'), '압력', 'ko stays the default');
  assert.equal(plainVariableName('QLT', 'en'), 'total liquid volumetric flow rate');
  assert.equal(plainVariableName('HOL', 'en'), 'liquid holdup');
  assert.equal(plainVariableName('PT', 'en'), 'pressure');
  assert.equal(plainVariableName('TM', 'en'), 'temperature');
  assert.equal(plainVariableName('HOLWT', 'en'), null, 'unknown mnemonics are never guessed');
});

test('findings kinds and fields resolve in both locales', async () => {
  const keys = [
    'findings.kind.pressure_drop', 'findings.kind.liqc', 'findings.kind.slugging', 'findings.kind.wax_hydrate',
    'findings.field.inlet', 'findings.field.outlet', 'findings.field.maxDrop', 'findings.field.unit',
    'findings.field.branch', 'findings.field.maxCount', 'findings.field.hydrateTemp', 'findings.field.waxTemp',
    'findings.field.pipe', 'findings.field.maxLitres',
  ];
  for (const key of keys) {
    assert.notEqual(tKo(key), key, `${key} resolves in ko`);
    assert.notEqual(tEn(key), key, `${key} resolves in en`);
  }
  assert.ok(tKo('findings.kind.pressure_drop').includes('압력'), 'ko kind keeps the Korean wording');
  assert.ok(tEn('findings.field.inlet').includes('Inlet'), 'en field reads naturally');
  const fields = await read('../src/FindingsCriterionFields.tsx');
  assert.match(fields, /KIND_LABEL_KEYS/, 'kind labels come from dictionary keys');
  assert.match(fields, /t\('findings\.field\.inlet'\)/, 'field labels use t()');
  assert.doesNotMatch(fields, /label="입구 위치"/, 'no hardcoded field label remains');
});

test('recovered run line translates the engine kind and drops the repeated heading', () => {
  const recovered = detect({ reason_code: undefined, kind: 'engine', version: '2022.1.0' });
  const koLine = formatRunReason(recovered, tKo, { hasRecoveredRecord: true });
  assert.ok(koLine.includes('직접 엔진'), `ko kind is translated (${koLine})`);
  assert.doesNotMatch(koLine, /선택한 실행 환경:/, 'heading prefix is not repeated');
  const enLine = formatRunReason(recovered, tEn, { hasRecoveredRecord: true });
  assert.ok(enLine.includes('direct engine'), `en kind stays English (${enLine})`);
  assert.doesNotMatch(enLine, /Selected run environment:/, 'heading prefix is not repeated');
});

test('new dictionary blocks stay inside commented sections', async () => {
  const [koSource, enSource] = await Promise.all([
    read('../src/i18n/ko.ts'),
    read('../src/i18n/en.ts'),
  ]);
  for (const [label, source] of [['ko', koSource], ['en', enSource]]) {
    for (const block of ['// workspace', '// results', '// run']) {
      assert.ok(source.includes(block), `${label} keeps the ${block} block`);
    }
  }
  assert.deepEqual(Object.keys(en).sort(), Object.keys(ko).sort(), 'en still covers every ko key');
});
