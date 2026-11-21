import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { editFromRun, editTargetStep, openFromRun } from '../src/editFromRunModel.mjs';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

/* 0.1.22 row 9: a result offers "Edit from this run" only while its case still holds the bytes the run
 * used. The click opens the edit table on that case with nothing typed in; otherwise one line says why. */

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('the button exists only for a case whose bytes match the run', () => {
  assert.deepEqual(editFromRun({ edit_source: { rel: 'cases/a.genkey' } }), { kind: 'open', rel: 'cases/a.genkey' });
  assert.deepEqual(editFromRun({ edit_source: { reason: 'changed' } }), { kind: 'reason', key: 'results.editFromRun.reason.changed' });
  assert.deepEqual(editFromRun({ edit_source: { reason: 'brand_new' } }), { kind: 'reason', key: 'results.editFromRun.reason.unknown' });
  assert.equal(editFromRun({}), null, 'a workspace file that is no run result has neither');
});

test('the workspace opens the table once that case is the one shown, and waits while it becomes so', () => {
  const target = { rel: 'cases/a.genkey' };
  assert.equal(editTargetStep({ target, selected: 'cases/a.genkey', activeRel: 'cases/a.genkey', activeAtRequest: 'cases/b.genkey' }), 'open');
  assert.equal(editTargetStep({ target, selected: 'cases/b.genkey', activeRel: 'cases/a.genkey', activeAtRequest: 'cases/b.genkey' }), 'wait');
  assert.equal(editTargetStep({ target, selected: 'cases/b.genkey', activeRel: 'cases/b.genkey', activeAtRequest: 'cases/b.genkey' }), 'wait');
  assert.equal(editTargetStep({ target, selected: 'cases/c.genkey', activeRel: 'cases/c.genkey', activeAtRequest: 'cases/b.genkey' }), 'drop',
    'another case became active instead: the request is dropped, never applied later');
  assert.equal(editTargetStep({ target: null, selected: 'cases/b.genkey', activeRel: 'cases/b.genkey', activeAtRequest: null }), 'open');
});

test('review R1: a failed case switch sends no edit request, so nothing opens later by surprise', async () => {
  const calls = [];
  const deps = (picked) => ({
    activeName: 'b.genkey',
    pickCase: async (rel) => { calls.push(`pick ${rel}`); return picked; },
    openWorkspace: () => calls.push('workspace'),
    request: (rel) => calls.push(`edit ${rel}`),
  });
  assert.equal(await openFromRun('cases/a.genkey', deps(false)), false);
  assert.deepEqual(calls, ['pick cases/a.genkey']);
  calls.length = 0;
  assert.equal(await openFromRun('cases/a.genkey', deps(true)), true);
  assert.deepEqual(calls, ['pick cases/a.genkey', 'workspace', 'edit cases/a.genkey']);
  calls.length = 0;
  assert.equal(await openFromRun('cases/b.genkey', deps(false)), true, 'already active: no switch needed');
  assert.deepEqual(calls, ['workspace', 'edit cases/b.genkey']);
});

test('PVT D5: a case in a subfolder opens although Windows lists it with a backslash', async () => {
  const target = { rel: 'mfl_only/mfl_only_case.genkey' };
  assert.equal(editTargetStep({ target, selected: 'mfl_only\\mfl_only_case.genkey', activeRel: 'mfl_only/mfl_only_case.genkey', activeAtRequest: 'choke_pid.genkey' }), 'open');
  assert.equal(editTargetStep({ target, selected: 'choke_pid.genkey', activeRel: 'mfl_only/mfl_only_case.genkey', activeAtRequest: 'choke_pid.genkey' }), 'wait');
  let picked = 0;
  await openFromRun('mfl_only/mfl_only_case.genkey', { activeName: 'mfl_only_case.genkey', pickCase: async () => { picked += 1; return true; }, openWorkspace: () => {}, request: () => {} });
  assert.equal(picked, 0, 'the case already active by name is not picked again');
});

test('review R1: a case whose name another case shares gets its own reason', async () => {
  assert.deepEqual(editFromRun({ edit_source: { reason: 'same_name' } }), { kind: 'reason', key: 'results.editFromRun.reason.same_name' });
  const { renderEditFromRun } = await reviewNotesRenderer();
  assert.match(renderEditFromRun('ko', { edit_source: { reason: 'same_name' } }), /같은 이름/);
  assert.match(renderEditFromRun('en', { edit_source: { reason: 'same_name' } }), /same name/);
});

for (const locale of ['ko', 'en']) {
  test(`${locale}: the result header shows the button or the reason, never both`, async () => {
    const { renderEditFromRun } = await reviewNotesRenderer();
    const open = renderEditFromRun(locale, { edit_source: { rel: 'cases/a.genkey' } });
    assert.match(open, locale === 'ko' ? /이 실행으로 수정/ : /Edit from this run/);
    assert.match(open, /<button/);
    const changed = renderEditFromRun(locale, { edit_source: { reason: 'changed' } });
    assert.doesNotMatch(changed, /<button/);
    assert.match(changed, locale === 'ko' ? /사례 파일이 바뀌/ : /case file changed/);
    assert.equal(renderEditFromRun(locale, {}), '');
  });
}

test('the click carries only the case path, so nothing is typed into the table', async () => {
  const events = await read('../src/shell/workspaceEvents.ts');
  assert.match(events, /new CustomEvent\(EDIT_FROM_RUN_EVENT, \{ detail: \{ rel \} \}\)/);
  const app = await read('../src/App.tsx');
  assert.match(app, /useEditFromRun\(workspaceContext\.active\.name, pickCase, /);
  const hook = await read('../src/shell/useEditFromRun.ts');
  assert.match(hook, /window\.addEventListener\(EDIT_FROM_RUN_EVENT/);
  assert.match(hook, /requestCaseEdit\(\{ rel \}\)/);
  const view = await read('../src/WorkspaceView.tsx');
  assert.match(view, /editTargetStep\(/);
});
