// N7 (D1): a run failure reads in the UI language, picked by its code; an unknown code keeps
// the server's words.
import assert from 'node:assert/strict';
import test from 'node:test';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';
import { runFailureView } from '../src/runFailureText.mjs';
import { translate } from '../src/i18n/index.ts';

const r = await reviewNotesRenderer();
const english = (code, extra = {}) => ({
  code, title: 'OLGA process failed', detail: 'The native process returned exit 65; inspect the captured solver log for the case-specific cause.',
  action: 'Review the log and correct the reported condition before starting another run.', auto_retry_safe: false, ...extra,
});

test('the exit-65 failure reads in Korean with no English server text left (D1)', () => {
  const html = r.renderFailedRun('ko', null, english('native_process_failed'));
  assert.match(html, /<strong>OLGA 프로세스가 실패했어요<\/strong>/);
  assert.match(html, /종료 코드 65를 냈어요/);
  assert.match(html, /로그를 읽고 보고된 조건을 고친 뒤 다시 실행하세요/);
  assert.doesNotMatch(html, /OLGA process failed|native process returned|Review the log|Operator recovery steps/);
});

test('every known code has a title, a detail and every step in both languages', () => {
  const codes = ['run_cancelled', 'run_timed_out', 'run_helper_failed', 'opi_engine_start_failed', 'olga_dll_load_failed',
    'native_communication_failure', 'native_process_failed', 'process_start_failed', 'run_interrupted'];
  for (const code of codes) {
    for (const variant of code === 'run_interrupted' ? ['app_closed', 'helper_gone'] : [undefined]) {
      const view = runFailureView({ code, variant, detail: 'x' }, 65);
      for (const key of [view.titleKey, view.detailKey, ...view.stepKeys]) {
        for (const locale of ['en', 'ko']) assert.notEqual(translate(locale, key, view.params), key, `${locale} ${key}`);
      }
    }
  }
});

test('the interrupted variants have their own words', () => {
  assert.match(r.renderFailedRun('en', null, english('run_interrupted', { variant: 'helper_gone' })), /Run stopped before OLGA finished/);
  assert.match(r.renderFailedRun('en', null, english('run_interrupted', { variant: 'app_closed' })), /Run stopped when the app closed/);
});

test('the operating system reason of a helper failure is kept as given, without the English paragraph', () => {
  const detail = 'OLGA is started through a small helper program (olga-explorer-broker.exe) that the app builds on this PC. '
    + 'The helper did not start or stopped responding, so OLGA did not run the case. Reason: broker exited 5';
  const html = r.renderFailedRun('ko', null, english('run_helper_failed', { detail }));
  assert.match(html, /앱의 실행 도우미가 멈췄어요/);
  assert.match(html, /<small>알려진 이유:<\/small> broker exited 5<\/p>/);
  assert.doesNotMatch(html, /small helper program/);
  const bare = r.renderFailedRun('ko', null, english('run_helper_failed', { detail: 'No reason marker here.' }));
  assert.doesNotMatch(bare, /알려진 이유/);
  const start = r.renderFailedRun('ko', null, english('process_start_failed', { detail: '[WinError 2] The system cannot find the file' }));
  assert.match(start, /<small>알려진 이유:<\/small> \[WinError 2\] The system cannot find the file/);
});

test('an unknown failure code keeps the server words', () => {
  const html = r.renderFailedRun('ko', null, english('something_new', { title: 'A new failure', detail: 'Server detail.', action: 'Do X.' }));
  assert.match(html, /<strong>A new failure<\/strong>/);
  assert.match(html, /Server detail\./);
  assert.match(html, /<li>Do X\.<\/li>/);
});
