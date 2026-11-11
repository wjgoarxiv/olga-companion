import assert from 'node:assert/strict';
import test from 'node:test';

import { approvalCardRenderer } from './helpers/render-approval-card.mjs';

const render = await approvalCardRenderer();

const runRequest = (display) => ({
  name: 'run_execute',
  call_id: 'call_run',
  pending_id: 'pending_run',
  args: {},
  display,
});

const runDisplay = () => ({
  case: 'case.genkey',
  selection_id: 'selection_exact',
  runtime_id: 'olga-2022.1',
  executable: 'OLGA.exe',
  output_target: 'managed-run-sandbox',
  source_sha256: 'a'.repeat(64),
  timeout_s: 120,
});

test('L8: a run approval with server warnings shows them before approval', () => {
  const warning = 'Large pressure step: boundary and start pressures span 2 bar to 5 bar (a 2.5x step). Transients may leave the PVT table grid. 큰 압력 단계 경고';
  for (const locale of ['ko', 'en']) {
    const html = render(locale, runRequest({ ...runDisplay(), warnings: [warning] }));
    assert.ok(html.includes('Large pressure step'), `${locale} shows the warning`);
    const label = locale === 'ko' ? '승인하고 실행' : 'Approve and run';
    assert.ok(html.includes(`>${label}<`), `${locale} keeps the labeled approve button`);
  }
});

test('L8: a run approval without warnings shows no warning block', () => {
  for (const locale of ['ko', 'en']) {
    const html = render(locale, runRequest(runDisplay()));
    assert.doesNotMatch(html, /approval-warnings/);
  }
});

test('L8: malformed warnings never render as text', () => {
  const html = render('en', runRequest({ ...runDisplay(), warnings: ['good', 7, null, { text: 'bad' }] }));
  assert.ok(html.includes('good'));
  assert.doesNotMatch(html, />bad</);
});
