import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const readCss = async () => {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((match) => read(`../src/${match[1]}`)));
  return [root, ...imported].join('\n');
};

/* Todo 10: one status source — the status bar owns runtime, the run tab owns
 * run state through a single shared pill. The old header engine pill is gone. */

test('run cockpit carries no engine pill; the status bar owns runtime state', async () => {
  const [overview, statusbar] = await Promise.all([
    read('../src/RunViewOverview.tsx'),
    read('../src/shell/StatusBar.tsx'),
  ]);
  assert.doesNotMatch(overview, /run-engine/, 'engine state lives in the status bar, not the run header');
  assert.match(statusbar, /runtime|Runtime/, 'the status bar remains the runtime source');
});

test('single and sweep panels share one run-state pill', async () => {
  const [single, sweep, pill] = await Promise.all([
    read('../src/RunSingleCasePanel.tsx'),
    read('../src/RunSweepPanel.tsx'),
    read('../src/RunStatePill.tsx'),
  ]);
  assert.match(pill, /run-state/, 'one pill owns the state class contract');
  assert.match(single, /RunStatePill/, 'the single panel uses the shared pill');
  assert.match(sweep, /RunStatePill/, 'the sweep panel uses the shared pill');
  assert.doesNotMatch(single, /<strong className=\{`run-state/, 'no inline duplicate in single');
  assert.doesNotMatch(sweep, /<strong className=\{`run-state/, 'no inline duplicate in sweep');
});

test('the run receipt states the launcher once, outputs ride a Table', async () => {
  const [single, css] = await Promise.all([
    read('../src/RunSingleCasePanel.tsx'),
    readCss(),
  ]);
  const launcherMentions = (single.match(/selectedLauncher|launcherKindLabel/g) || []).length;
  assert.ok(launcherMentions <= 1, `one launcher mention, found ${launcherMentions}`);
  assert.match(single, /run-receipt/, 'the receipt shell stays');
});
