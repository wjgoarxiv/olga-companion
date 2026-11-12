import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

import { normalizeModelEffort } from '../src/modelEffort.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const sol = {
  id: 'gpt-5.6-sol',
  reasoning_efforts: ['max', 'xhigh', 'high', 'medium', 'low'],
  default_effort: 'medium'
};

const legacy = {
  id: 'gpt-5.5',
  reasoning_efforts: ['xhigh', 'high', 'medium', 'low'],
  default_effort: 'medium'
};

test('model effort normalization preserves valid max and repairs stale pairs', () => {
  assert.equal(normalizeModelEffort(sol, 'max'), 'max');
  assert.equal(normalizeModelEffort(legacy, 'max'), 'medium');
  assert.equal(normalizeModelEffort(sol, 'ultra'), 'medium');
});

test('provider panel renders backend model capabilities rather than a global effort list', async () => {
  const panel = await read('../src/ProviderPanel.tsx');
  const types = await read('../src/types.ts');

  assert.match(types, /reasoning_efforts/);
  assert.match(types, /default_effort/);
  assert.match(panel, /activeModel.*reasoning_efforts/s);
  assert.match(panel, /max:\s*'max'/);
  assert.match(panel, /medium:\s*'medium'/);
  assert.doesNotMatch(panel, /balanced/, 'the UI exposes the real API effort tier');
  assert.match(panel, /normalizeModelEffort/);
  assert.doesNotMatch(panel, /value:\s*['"]ultra['"]/, 'Ultra is orchestration, not reasoning.effort');
});
