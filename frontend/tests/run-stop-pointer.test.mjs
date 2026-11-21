// N3: a failed run shows the OLGA line its cause was read from and, only when OLGA named one
// clearly, the place in the case to look at.
import assert from 'node:assert/strict';
import test from 'node:test';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const table = (pointer) => ({
  code: 'pressure_below_table', stopped_at_s: 985.6, pressure_bara: 0.48789, temperature_c: 24.734,
  where: 'FLOWPATH=MAIN, PIPE=DOWNSTREAM, SECTION=9', exit_code: 65, exit_message: 'pressure below',
  evidence: 'PRESSURE BELOW TABLE VALUES (P = 0.48789 bara, T = 24.734 C)', pointer, last_lines: [],
});

test('a pipe stop shows the OLGA line and the pipe section, in English and Korean', () => {
  const pointer = { kind: 'pipe', flowpath: 'MAIN', label: 'DOWNSTREAM', section: 9 };
  const en = r.renderFailedRun('en', table(pointer));
  assert.match(en, /<small>OLGA wrote<\/small><code>PRESSURE BELOW TABLE VALUES \(P = 0\.48789 bara, T = 24\.734 C\)<\/code>/);
  assert.match(en, /<small>Look here in the case<\/small><span>Pipe DOWNSTREAM in flowpath MAIN, section 9\.<\/span>/);
  const ko = r.renderFailedRun('ko', table(pointer));
  assert.match(ko, /OLGA가 남긴 줄/);
  assert.match(ko, /플로패스 MAIN의 배관 DOWNSTREAM, 구간 9/);
});

test('a node stop and a rejected input each name their place', () => {
  assert.match(r.renderFailedRun('en', table({ kind: 'node', label: 'INLET' })), /Node INLET \(its PARAMETERS line\)\./);
  const rejected = r.renderFailedRun('en', {
    code: 'input_rejected', exit_code: 18, exit_message: 'verification failed', last_lines: [],
    evidence: 'BRANCH: TagsFrom component with LABEL or NUMBER 1 as referred to in key FLUID is not found.',
    pointer: { kind: 'keyword', component: 'FLOWPATH_1', keyword: 'BRANCH', key: 'FLUID' },
  });
  assert.match(rejected, /OLGA did not accept an input of the case/);
  assert.match(rejected, /Key FLUID of BRANCH in FLOWPATH_1\./);
  assert.match(r.renderFailedRun('ko', { code: 'input_rejected', last_lines: [] }), /OLGA가 사례의 입력값을 받아들이지 않았어요/);
});

test('an unknown stop shows its OLGA line but never a place, even if one is sent', () => {
  const html = r.renderFailedRun('en', {
    code: 'unknown', exit_code: 77, exit_message: 'something new', last_lines: ['x'],
    evidence: "**** OLGA stopped with exit message 'something new' (77) ****",
    pointer: { kind: 'node', label: 'INLET' },
  });
  assert.match(html, /OLGA wrote/);
  assert.doesNotMatch(html, /Look here in the case/);
});

test('a malformed pointer or no evidence renders neither line', () => {
  const html = r.renderFailedRun('en', { ...table({ kind: 'pipe', label: 'P', section: 'nine' }), evidence: null });
  assert.doesNotMatch(html, /OLGA wrote|Look here in the case/);
  assert.match(html, /The pressure fell below the fluid table/);
});
