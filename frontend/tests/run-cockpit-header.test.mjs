import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readRunSource } from './run-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('run state has a single source: status bar for runtime, run tab for run state', async () => {
  const [run, statusbar] = await Promise.all([
    readRunSource(),
    read('../src/shell/StatusBar.tsx'),
  ]);
  assert.doesNotMatch(run, /run-engine/, 'no engine pill duplicates the status bar runtime item');
  assert.match(statusbar, /runtime|Runtime/, 'the status bar owns runtime state');
  assert.match(run, /RunStatePill/, 'the run tab owns run state through one shared pill');
});
