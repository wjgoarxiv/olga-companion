import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { presentInspectionEvidence } from '../src/inspectionPresentation.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('GENKEY review presents the decision before bounded technical provenance', () => {
  const presentation = presentInspectionEvidence('genkey_review', {
    path: 'path-sha256:abc123',
    valid: true,
    validation: {
      script: 'genkey_validator.py',
      exit_code: 0,
      stdout: 'Validation Report: case.genkey\nErrors: 0\nWarnings: 0',
    },
    topology: {
      script: 'topology_visualizer.py',
      exit_code: 0,
      stdout: 'Network Topology\nnode A -> node B',
    },
  });

  assert.deepEqual(presentation, {
    kind: 'genkey',
    good: true,
    title: '사례 검증 통과',
    detail: '검증과 배관망 검사를 마쳤고, 진행을 막는 문제는 없었어요.',
    source: 'path-sha256:abc123',
    checks: [
      {
        label: '사례 규칙',
        state: '통과',
        detail: 'GENKEY 검증이 끝났어요.',
        report: 'Validation Report: case.genkey\nErrors: 0\nWarnings: 0',
      },
      {
        label: '배관망 구조',
        state: '읽음',
        detail: '배관망 연결을 읽었어요.',
        report: 'Network Topology\nnode A -> node B',
      },
    ],
  });
});

test('PVT summary becomes a composition ledger and engineering metric set', () => {
  const presentation = presentInspectionEvidence('fluids_inspect_tab', {
    valid: true,
    summary_text: [
      'PVT Table Summary: demo_water_air_evap.tab',
      '  Label:          demo_water_air_evap',
      '  Phase:          THREE',
      '  Formulation:    (none)',
      '',
      '  Components:  H2O (50.0 mol%), N2 (39.5 mol%), O2 (10.5 mol%)',
      '  Mol Weights: H2O=18.0152, N2=28.0135, O2=31.9988',
      '',
      '  Pressure:    0.01325 - 14.0132 bar (50 points)',
      '  Temperature: -236.035 - -143.968 C (bubble range)',
      '  Mesh Type:   STANDARD',
      '',
      '  File Size:   421.4 KB',
    ].join('\n'),
    validation_errors: [],
    validation_warnings: ['review temperature range'],
  });

  assert.equal(presentation?.kind, 'pvt');
  assert.equal(presentation?.title, 'demo_water_air_evap.tab');
  assert.equal(presentation?.label, 'demo_water_air_evap');
  assert.equal(presentation?.phase, 'THREE');
  assert.equal(presentation?.formulation, 'None');
  assert.deepEqual(presentation?.components, [
    { name: 'H2O', fraction: '50.0 mol%', molarMass: '18.0152' },
    { name: 'N2', fraction: '39.5 mol%', molarMass: '28.0135' },
    { name: 'O2', fraction: '10.5 mol%', molarMass: '31.9988' },
  ]);
  assert.deepEqual(presentation?.metrics, [
    { label: 'Pressure envelope', value: '0.01325–14.0132', unit: 'bar', note: '50 points' },
    { label: 'Temperature envelope', value: '−236.035–−143.968', unit: '°C', note: 'bubble range' },
    { label: 'Mesh', value: 'Standard' },
    { label: 'File size', value: '421.4', unit: 'KB' },
  ]);
  assert.equal(presentation?.warningCount, 1);
});

test('GENKEY review copy resolves through t() keys in both locales', async () => {
  const { translate } = await import('../src/i18n/index.ts');
  const input = {
    path: 'case.genkey',
    valid: true,
    validation: { script: 'genkey_validator.py', exit_code: 0, stdout: 'Errors: 0' },
    topology: { script: 'topology_visualizer.py', exit_code: 0, stdout: 'node A -> node B' },
  };
  const ko = presentInspectionEvidence('genkey_review', input, (key, vars) => translate('ko', key, vars));
  assert.equal(ko.title, '사례 검증 통과');
  assert.equal(ko.checks[0].label, '사례 규칙');
  const seen = [];
  const recording = (key, vars) => {
    seen.push(key);
    return translate('en', key, vars);
  };
  const en = presentInspectionEvidence('genkey_review', input, recording);
  assert.equal(en.title, 'Case validation passed');
  assert.equal(en.detail, 'Validation and network checks are done with no blocking issues.');
  assert.equal(en.checks[0].label, 'Case rules');
  assert.equal(en.checks[1].state, 'Read');
  assert.ok(seen.includes('inspect.genkey.passTitle'), 'title key requested');
  assert.ok(seen.includes('inspect.check.rules'), 'check label key requested');
  assert.doesNotMatch(en.title, /[가-힣]/, 'en copy carries no Hangul');
});

test('inspection evidence and creator credit have semantic UI contracts', async () => {
  const [evidence, inspection, presenter, sidebar, fixture] = await Promise.all([
    read('../src/EvidenceBlock.tsx'),
    read('../src/InspectionEvidence.tsx'),
    read('../src/inspectionPresentation.ts'),
    read('../src/Sidebar.tsx'),
    read('./lifecycle-visual-fixture.tsx'),
  ]);

  assert.match(evidence, /presentInspectionEvidence/);
  assert.match(evidence, /<InspectionEvidence presentation=\{inspection\}/);
  assert.match(inspection, /t\('inspect\.techEvidence'\)/);
  assert.match(inspection, /t\('inspect\.pvtComposition'\)/);
  assert.match(presenter, /Pressure envelope/);
  assert.match(sidebar, /href="https:\/\/github\.com\/wjgoarxiv"/);
  assert.match(sidebar, /aria-label=\{t\('sidebar\.githubAria'\)\}/);
  assert.match(sidebar, /target="_blank"/);
  assert.match(sidebar, /rel="noreferrer"/);
  assert.match(fixture, /name="genkey_review"/);
  assert.match(fixture, /name="fluids_inspect_tab"/);
});

test('evidence cards use token radii (square in the neo-brutal theme) without decorative status rails', async () => {
  const [base, tools, controls, lifecycle, caseSpec, fixture] = await Promise.all([
    read('../src/styles/base.css'),
    read('../src/styles/chat-tools.css'),
    read('../src/styles/controls.css'),
    read('../src/LifecycleEvidence.tsx'),
    read('../src/CaseSpecEvidence.tsx'),
    read('./lifecycle-visual-fixture.css'),
  ]);

  assert.match(base, /--r-surface:\s*0\b/);
  assert.doesNotMatch(tools, /border-left:\s*[2-9]\d*px\s+solid/);
  assert.doesNotMatch(lifecycle, /evidence-outcome-mark/);
  assert.doesNotMatch(caseSpec, /evidence-outcome-mark/);
  assert.match(tools, /\.tool-unit\s*\{[^}]*border-radius:\s*var\(--r-surface\)/s);
  assert.match(tools, /\.inspection-head\s*\{[^}]*border-radius:\s*var\(--r-surface\)/s);
  assert.match(tools, /\.approval-card\s*\{[^}]*border-radius:\s*var\(--r-surface\)/s);
  assert.match(tools, /\.evidence-table-viewport\s*\{[^}]*border-radius:\s*var\(--r-surface\)/s);
  assert.match(controls, /\.receipt\s*\{[^}]*border-radius:\s*var\(--r-surface\)/s);
  assert.match(fixture, /\.qa-card\s*\{[^}]*border-radius:\s*var\(--r-surface\)/s);
});
