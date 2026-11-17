import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { translate } from '../src/i18n/index.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('FEW1: the run finish store holds one terminal state per run id', async () => {
  const store = await import('../src/runFinishStore.ts');
  store.clearRunFinishStore();
  assert.equal(store.getRunFinish('run-1'), null);

  const seen = [];
  const unsubscribe = store.subscribeRunFinish('run-1', () => {
    seen.push(store.getRunFinish('run-1'));
  });
  store.publishRunFinish('run-1', 'completed');
  assert.equal(store.getRunFinish('run-1'), 'completed');
  assert.deepEqual(seen, ['completed']);

  // Review-1: a later terminal report for the same run is stale, the first one wins.
  store.publishRunFinish('run-1', 'failed');
  assert.equal(store.getRunFinish('run-1'), 'completed');
  assert.deepEqual(seen, ['completed']);

  // Runs are isolated from each other.
  assert.equal(store.getRunFinish('run-2'), null);
  store.publishRunFinish('run-2', 'cancelled');
  assert.equal(store.getRunFinish('run-2'), 'cancelled');
  assert.equal(store.getRunFinish('run-1'), 'completed');

  // Unsubscribing stops notifications.
  unsubscribe();
  store.publishRunFinish('run-1', 'completed');
  assert.equal(store.getRunFinish('run-1'), 'completed');
  assert.deepEqual(seen, ['completed']);

  // Every terminal state maps into the store; pollable states map to nothing.
  assert.equal(store.toRunFinishState('completed'), 'completed');
  assert.equal(store.toRunFinishState('failed'), 'failed');
  assert.equal(store.toRunFinishState('cancelled'), 'cancelled');
  assert.equal(store.toRunFinishState('running'), null);
  assert.equal(store.toRunFinishState('finalizing'), null);
  store.clearRunFinishStore();
});

test('FEW1: the opener publishes every terminal state to the store', async () => {
  const opener = await read('../src/useRunCompletionOpener.ts');
  assert.match(opener, /runFinishStore/, 'the opener writes to the run finish store');
  assert.match(opener, /publishRunFinish/, 'the opener publishes terminal states');
  assert.match(opener, /toRunFinishState/, 'the opener maps every terminal state, not just completed');
  assert.match(opener, /runStatusIsPollable/, 'polling still stops at a terminal state');
  assert.match(
    opener,
    /state === 'completed'\) announce\(runId\)/,
    'only a completed run still opens Results through announce',
  );
});

test('FEW1: a non-terminal patrol card subscribes and checks the store before polling', async () => {
  const card = await read('../src/LifecycleEvidence.tsx');
  assert.match(card, /runFinishStore/, 'the patrol card reads the run finish store');
  assert.match(card, /getRunFinish|useRunFinish/, 'the card checks the store first');
  assert.match(card, /startRunFinishPoll/, 'the fallback poll is the bounded shared controller');
  assert.match(card, /pollStatus: runStatus/, 'the controller poll asks the runner for the state');
  assert.match(card, /onUnknown/, 'an unrecognized end state has its own branch');
  assert.match(card, /return \(\) =>/, 'the fallback poll stops on unmount');
});

test('FEW1: a finished card shows the terminal title and labels the old percentage as last seen', async () => {
  const card = await read('../src/LifecycleEvidence.tsx');
  assert.match(card, /LastSeen|lastSeen|last_seen/, 'the stale percentage is labelled as last seen');
  for (const key of ['lifecycle.vendorProgressLastSeen', 'lifecycle.patrolLateFinishDetail']) {
    const ko = translate('ko', key);
    const en = translate('en', key);
    assert.notEqual(ko, key, `${key} resolves in ko`);
    assert.notEqual(en, key, `${key} resolves in en`);
    assert.notEqual(ko, en, `${key} is translated, not copied`);
    assert.doesNotMatch(en, /[가-힣]/, `${key} en carries no Hangul`);
  }
});

test('FEW1: the card path never opens Results a second time', async () => {
  const [completion, card] = await Promise.all([
    read('../src/runCompletion.ts'),
    read('../src/LifecycleEvidence.tsx'),
  ]);
  assert.doesNotMatch(completion, /runFinishStore/, 'findRunCompletion never reads card state');
  assert.doesNotMatch(card, /findRunCompletion/, 'the card never re-announces a completion');
  assert.doesNotMatch(card, /openResultsView|preferResult|selectView\('results'\)/, 'the card never opens Results itself');
});
