import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';

const { activeCaseStepFacts, deriveStepStates, deriveStatusLine } = await import('../src/shell/useStepState.ts');

const file = (name, suffix) => ({ name, rel: name, suffix, size: 1 });
const states = (over) => deriveStepStates({
  activeCaseName: 'net.genkey', tabCount: 1, hasRunOutputs: false, errorCount: 0,
  hasEvidence: false, preferredResultId: null, ...over,
});
const line = (over, timeline = []) => deriveStatusLine({ states: states(over), timeline, activeCaseName: 'net.genkey' });

test('each step state names where the user is and the one next action', () => {
  assert.deepEqual(line({ hasWorkspace: false }), { key: 'stepbar.line.noWorkspace', params: {} });
  assert.equal(deriveStatusLine({ states: states({ activeCaseName: null }), timeline: [], activeCaseName: null }).key, 'stepbar.line.noCase');
  assert.deepEqual(line({ tabCount: 0 }), { key: 'stepbar.line.noTab', params: { case: 'net.genkey' } });
  assert.deepEqual(line({ errorCount: 2 }), { key: 'stepbar.line.errors', params: { case: 'net.genkey', count: 2 } });
  assert.equal(line({}).key, 'stepbar.line.saved');
  assert.equal(line({ hasEvidence: true }).key, 'stepbar.line.checked');
  assert.equal(line({ hasEvidence: true, runInFlight: true }).key, 'stepbar.line.running');
  assert.equal(line({ hasEvidence: true, hasRunOutputs: true }).key, 'stepbar.line.ran');
  assert.equal(line({ hasEvidence: true, preferredResultId: 'r1' }).key, 'stepbar.line.resultOpen');
});

test('a pending approval card wins over the step: the user has to answer it first', () => {
  const pending = { kind: 'approval', id: 'a', resolved: false, request: { name: 'run_execute', call_id: 'c', pending_id: 'p', args: {} } };
  assert.deepEqual(line({ hasEvidence: true }, [pending]), { key: 'stepbar.line.approval', params: { action: 'run' } });
  assert.equal(line({ hasEvidence: true }, [{ ...pending, resolved: true }]).key, 'stepbar.line.checked');
  const publish = { ...pending, request: { ...pending.request, name: 'case_publish' } };
  assert.deepEqual(line({}, [publish]).params, { action: 'save' });
});

test('once the user has answered the card, the line stops asking while the work finishes', () => {
  const pending = { kind: 'approval', id: 'a', resolved: false, request: { name: 'run_execute', call_id: 'c', pending_id: 'p', args: {} } };
  assert.equal(line({ hasEvidence: true }, [{ ...pending, lifecycle: 'awaiting-approval' }]).key, 'stepbar.line.approval');
  for (const lifecycle of ['dispatched', 'running', 'finalizing']) {
    assert.notEqual(line({ hasEvidence: true }, [{ ...pending, lifecycle }]).key, 'stepbar.line.approval', lifecycle);
  }
  assert.equal(line({ hasEvidence: true }, [{ ...pending, lifecycle: 'failed', recoverable: true }]).key, 'stepbar.line.approval',
    'a card that needs the user again still asks');
});

test('a clean review or a run preview from chat counts as the check for that case', () => {
  const cases = [file('net.genkey', '.genkey'), file('fluid.tab', '.tab')];
  const review = { kind: 'tool', id: 't', name: 'genkey_review', callId: 'c', status: 'completed', args: { path: 'net.genkey' }, result: { path: 'C:/w/net.genkey', valid: true } };
  assert.equal(activeCaseStepFacts({ activeCaseName: 'net.genkey', cases, timeline: [review] }).hasEvidence, true);
  assert.equal(activeCaseStepFacts({ activeCaseName: 'net.genkey', cases, timeline: [{ ...review, result: { ...review.result, valid: false } }] }).hasEvidence, false);
  assert.equal(activeCaseStepFacts({ activeCaseName: 'other.genkey', cases, timeline: [review] }).hasEvidence, false);
  const preview = { kind: 'tool', id: 'p', name: 'run_preview', callId: 'c2', status: 'completed', args: {}, result: { source: 'C:/w/net.genkey', command: ['opi'] } };
  assert.equal(activeCaseStepFacts({ activeCaseName: 'net.genkey', cases, timeline: [preview] }).hasEvidence, true);
});

test('ko and en carry every status-line key, and the bar shows the line', async () => {
  const keys = (dict) => Object.keys(dict).filter((key) => key.startsWith('stepbar.line.') || key.startsWith('stepbar.approvalAction.')).sort();
  assert.ok(keys(ko).length >= 11);
  assert.deepEqual(keys(ko), keys(en));
  const bar = await readFile(new URL('../src/shell/StepBar.tsx', import.meta.url), 'utf8');
  assert.match(bar, /deriveStatusLine\(/);
  assert.match(bar, /className="stepbar-line"/);
});
