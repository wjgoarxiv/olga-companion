// Hyper-real round 4 (2026-11-11): case_spec_validate returns the normalized spec but no
// compiled geometry, and the card read "형상 0 파이프 · 구간 정보 없음" for a valid
// four-pipe, 52-section line. The connection row already fell back to the plan.
import test from 'node:test';
import assert from 'node:assert/strict';
import { caseSpecEvidenceRenderer } from './helpers/render-casespec-evidence.mjs';

const pipe = (label, sections) => ({ label, centerline_m: [[0, 0, 0], [1, 0, 0]], diameter_m: 0.1, roughness_m: 0.000002, sections });
const validated = {
  valid: true,
  publishable: true,
  version: '2',
  normalized: {
    version: '2',
    nodes: [{ label: 'INLET', kind: 'closed' }, { label: 'OUTLET', kind: 'sink' }],
    flowpaths: [{ label: 'MAIN', from: 'INLET', to: 'OUTLET', pipes: [pipe('PIPE_1', 20), pipe('PIPE_2', 10), pipe('PIPE_3', 10), pipe('PIPE_4', 12)] }],
  },
  errors: [],
  warnings: [],
};

test('a validated spec shows its planned pipes and sections', async () => {
  const render = await caseSpecEvidenceRenderer();
  const html = render('ko', validated);
  assert.match(html, /4 파이프/);
  assert.match(html, /52/);
  assert.doesNotMatch(html, /0 파이프/);
  assert.match(html, /PIPE_4/);
});

// Round 8 (English UI): one flowpath of two pipes read "CONNECTIONS 2 nodes · 1 pipes"
// beside "GEOMETRY 2 pipes"; the connection row counts flowpaths.
test('the connection row counts flowpaths, not pipes', async () => {
  const render = await caseSpecEvidenceRenderer();
  assert.match(render('en', validated), /2 nodes · 1 flowpath/);
  assert.doesNotMatch(render('en', validated), /1 pipes/);
  assert.match(render('ko', validated), /2 노드 · 1 플로패스/);
});

test('compiled geometry still wins over the plan', async () => {
  const render = await caseSpecEvidenceRenderer();
  const html = render('en', {
    ...validated,
    geometry: [{ flowpath: 'MAIN', pipe: 'ONLY', diameter_m: 0.1, sections: 7 }],
    section_count: 7,
  });
  assert.match(html, /ONLY/);
  assert.doesNotMatch(html, /PIPE_4/);
});
