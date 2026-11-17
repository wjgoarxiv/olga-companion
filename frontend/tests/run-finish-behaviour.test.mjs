import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { translate } from '../src/i18n/index.ts';

const poll = await import('../src/runFinishPoll.ts');
const store = await import('../src/runFinishStore.ts');

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function status(state) {
  return { run_id: 'run-1', state, cancel_requested: false };
}

function harness(next) {
  store.clearRunFinishStore();
  const polls = [];
  const terminals = [];
  const unknowns = [];
  const io = {
    getFinish: (runId) => store.getRunFinish(runId),
    pollStatus: (runId) => {
      polls.push(runId);
      return Promise.resolve(next());
    },
    publishFinish: (runId, finish) => store.publishRunFinish(runId, finish),
  };
  const events = {
    onTerminal: (finish) => terminals.push(finish),
    onUnknown: (state) => unknowns.push(state),
  };
  return { polls, terminals, unknowns, io, events };
}

test('FER2-M2: a completed poll publishes the finish and reports it', async () => {
  const states = ['running', 'completed'];
  const h = harness(() => status(states.shift() ?? 'completed'));
  const stop = poll.startRunFinishPoll('run-1', h.io, h.events, { intervalMs: 5 });
  await sleep(60);
  stop();
  assert.equal(store.getRunFinish('run-1'), 'completed');
  assert.deepEqual(h.terminals, ['completed']);
  assert.equal(h.polls.length, 2);
  store.clearRunFinishStore();
});

test('FER2-M2: a restored card finishes from the store without polling', async () => {
  const h = harness(() => status('running'));
  store.publishRunFinish('run-1', 'failed');
  const stop = poll.startRunFinishPoll('run-1', h.io, h.events, { intervalMs: 5 });
  await sleep(40);
  stop();
  assert.equal(h.polls.length, 0);
  assert.deepEqual(h.terminals, []);
  assert.deepEqual(h.unknowns, []);
  store.clearRunFinishStore();
});

test('FER2-M2: polling stops when the store fills mid-loop', async () => {
  const states = ['running', 'running', 'running'];
  const h = harness(() => status(states.shift() ?? 'running'));
  let polls = 0;
  const io = {
    ...h.io,
    pollStatus: (runId) => {
      polls += 1;
      return h.io.pollStatus(runId);
    },
    getFinish: (runId) => (polls > 0 ? 'cancelled' : store.getRunFinish(runId)),
  };
  const stop = poll.startRunFinishPoll('run-1', io, h.events, { intervalMs: 5 });
  await sleep(60);
  stop();
  assert.equal(polls, 1);
  assert.deepEqual(h.terminals, []);
  assert.deepEqual(h.unknowns, []);
  store.clearRunFinishStore();
});

test('FER2-M2: stop ends polling', async () => {
  const h = harness(() => status('running'));
  const stop = poll.startRunFinishPoll('run-1', h.io, h.events, { intervalMs: 5, maxAttempts: 100 });
  await sleep(25);
  stop();
  const count = h.polls.length;
  assert.ok(count > 0, 'at least one poll happened before stop');
  await sleep(40);
  assert.equal(h.polls.length, count);
  store.clearRunFinishStore();
});

test('FER2-M2: a failed terminal is published and reported', async () => {
  const h = harness(() => status('failed'));
  const stop = poll.startRunFinishPoll('run-1', h.io, h.events, { intervalMs: 5 });
  await sleep(40);
  stop();
  assert.equal(store.getRunFinish('run-1'), 'failed');
  assert.deepEqual(h.terminals, ['failed']);
  store.clearRunFinishStore();
});

test('FER2-M2: a rejected poll stops silently', async () => {
  const h = harness(() => status('running'));
  let calls = 0;
  const io = {
    ...h.io,
    pollStatus: () => {
      calls += 1;
      return Promise.reject(new Error('sidecar down'));
    },
  };
  const stop = poll.startRunFinishPoll('run-1', io, h.events, { intervalMs: 5 });
  await sleep(40);
  stop();
  assert.equal(calls, 1);
  assert.equal(store.getRunFinish('run-1'), null);
  assert.deepEqual(h.terminals, []);
  assert.deepEqual(h.unknowns, []);
  store.clearRunFinishStore();
});

test('FER2-M3: a non-pollable, non-terminal state reports unknown without publishing', async () => {
  const h = harness(() => status('mystery'));
  const stop = poll.startRunFinishPoll('run-1', h.io, h.events, { intervalMs: 5 });
  await sleep(40);
  stop();
  assert.deepEqual(h.unknowns, ['mystery']);
  assert.equal(store.getRunFinish('run-1'), null);
  assert.deepEqual(h.terminals, []);
  assert.equal(h.polls.length, 1);
  store.clearRunFinishStore();
});

test('FER2-M3: the poll gives up after the attempt cap', async () => {
  const h = harness(() => status('running'));
  const stop = poll.startRunFinishPoll('run-1', h.io, h.events, { intervalMs: 5, maxAttempts: 3 });
  await sleep(60);
  stop();
  assert.equal(h.polls.length, 3);
  assert.equal(store.getRunFinish('run-1'), null);
  assert.deepEqual(h.terminals, []);
  store.clearRunFinishStore();
});

test('FER2-LOW: the first terminal state wins', async () => {
  const store = await import('../src/runFinishStore.ts');
  store.clearRunFinishStore();
  store.publishRunFinish('run-1', 'completed');
  store.publishRunFinish('run-1', 'failed');
  assert.equal(store.getRunFinish('run-1'), 'completed');
  store.clearRunFinishStore();
});

test('FER2-M1: failed and cancelled titles use the run.state dictionary', async () => {
  const card = await read('../src/LifecycleEvidence.tsx');
  assert.match(card, /run\.state\.\$\{/, 'the terminal title reads run.state.*');
  assert.doesNotMatch(card, /patrolState', \{ state \}/, 'no raw state word reaches the title');
  for (const [key, ko, en] of [
    ['run.state.failed', '실패함', 'failed'],
    ['run.state.cancelled', '취소됨', 'cancelled'],
    ['run.state.timed_out', '시간 초과', 'timed out'],
  ]) {
    assert.equal(translate('ko', key), ko);
    assert.equal(translate('en', key), en);
  }
});

test('FER2-LOW: the late-finish detail is per-state, in the 요 register', async () => {
  const card = await read('../src/LifecycleEvidence.tsx');
  assert.match(card, /patrolLateFinish\./, 'the card picks a per-state detail');
  for (const key of [
    'lifecycle.patrolLateFinish.completed',
    'lifecycle.patrolLateFinish.failed',
    'lifecycle.patrolLateFinish.cancelled',
    'lifecycle.patrolLateFinish.timed_out',
  ]) {
    const ko = translate('ko', key);
    const en = translate('en', key);
    assert.notEqual(ko, key, `${key} resolves in ko`);
    assert.notEqual(en, key, `${key} resolves in en`);
    assert.notEqual(ko, en, `${key} is translated, not copied`);
    assert.doesNotMatch(en, /[가-힣]/, `${key} en carries no Hangul`);
  }
  assert.match(translate('ko', 'lifecycle.patrolLateFinish.completed'), /요\./);
  assert.doesNotMatch(translate('ko', 'lifecycle.patrolLateFinish.completed'), /습니다/);
});

test('FER2-LOW: an unrecognized end state shows unknown and points at Run', async () => {
  const card = await read('../src/LifecycleEvidence.tsx');
  assert.match(card, /patrolUnknown/, 'the card has an unknown-end branch');
  for (const key of ['lifecycle.patrolUnknown', 'lifecycle.patrolUnknownDetail']) {
    const ko = translate('ko', key);
    const en = translate('en', key);
    assert.notEqual(ko, key, `${key} resolves in ko`);
    assert.notEqual(en, key, `${key} resolves in en`);
    assert.notEqual(ko, en, `${key} is translated, not copied`);
    assert.doesNotMatch(en, /[가-힣]/, `${key} en carries no Hangul`);
  }
  assert.match(translate('ko', 'lifecycle.patrolUnknownDetail'), /실행 화면/);
  assert.match(translate('en', 'lifecycle.patrolUnknownDetail'), /Run view/);
});

test('FER2-LOW: the store subscription is stable across renders', async () => {
  const store = await read('../src/runFinishStore.ts');
  assert.match(store, /useCallback/, 'the subscribe closure is memoized');
});
