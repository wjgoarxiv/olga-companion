import test from 'node:test';
import assert from 'node:assert/strict';

import * as requestHelpers from '../src/requestEpoch.mjs';

const { createRequestEpoch } = requestHelpers;

test('request epochs accept only the latest begun request', () => {
  const epoch = createRequestEpoch();
  const first = epoch.begin();
  const second = epoch.begin();

  assert.equal(epoch.isCurrent(first), false);
  assert.equal(epoch.isCurrent(second), true);
});

test('invalidate rejects an in-flight completion and the next begin is current', () => {
  const epoch = createRequestEpoch();
  const inFlight = epoch.begin();

  epoch.invalidate();
  assert.equal(epoch.isCurrent(inFlight), false);

  const resumed = epoch.begin();
  assert.equal(epoch.isCurrent(resumed), true);
});

test('out-of-order completions cannot become current again', () => {
  const epoch = createRequestEpoch();
  const completions = [epoch.begin(), epoch.begin(), epoch.begin()];

  assert.deepEqual(completions.map((request) => epoch.isCurrent(request)), [false, false, true]);
  epoch.invalidate();
  assert.deepEqual(completions.map((request) => epoch.isCurrent(request)), [false, false, false]);
});

test('poll generations reject out-of-order ticks and every response after cancellation', () => {
  const generations = createRequestEpoch();
  const requests = createRequestEpoch();
  const generation = generations.begin();
  const firstTick = requests.begin();
  const secondTick = requests.begin();

  const canCommit = (tick) => generations.isCurrent(generation) && requests.isCurrent(tick);
  assert.equal(canCommit(firstTick), false, 'an older overlapping tick cannot commit');
  assert.equal(canCommit(secondTick), true, 'the current tick can commit before cancellation');

  generations.invalidate();
  requests.invalidate();
  assert.equal(canCommit(firstTick), false);
  assert.equal(canCommit(secondTick), false, 'cancellation invalidates an in-flight current tick');
});

test('one operation epoch rejects superseded work and every continuation after teardown', () => {
  const operations = createRequestEpoch();
  let mounted = true;
  const preview = operations.begin();
  const execute = operations.begin();
  const canCommit = (request) => mounted && operations.isCurrent(request);

  assert.equal(canCommit(preview), false, 'a newer operation supersedes an older continuation');
  assert.equal(canCommit(execute), true);

  mounted = false;
  operations.invalidate();
  assert.equal(canCommit(execute), false, 'unmount rejects even the latest continuation');
});

test('owned single-flight rejects rapid duplicates and stale releases cannot unlock newer work', () => {
  assert.equal(typeof requestHelpers.createSingleFlight, 'function', 'single-flight helper must exist');
  const gate = requestHelpers.createSingleFlight();
  const first = gate.begin();

  assert.equal(typeof first, 'number');
  assert.equal(gate.begin(), null, 'a rapid second activation is rejected synchronously');
  gate.end(first + 1);
  assert.equal(gate.begin(), null, 'a stale owner cannot release the active request');
  gate.end(first);

  const second = gate.begin();
  assert.equal(typeof second, 'number');
  gate.reset();
  const third = gate.begin();
  assert.equal(typeof third, 'number', 'teardown reset releases the gate');
  gate.end(second);
  assert.equal(gate.begin(), null, 'a pre-reset owner cannot unlock newer work');
  gate.end(third);
});
