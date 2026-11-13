import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  claimExampleInstall,
  exampleErrorKey,
  getExampleInstallBusy,
  loadRememberedExample,
  releaseExampleInstall,
  rememberExampleInstall,
} from '../src/exampleInstallState.mjs';
import { demoRunSignal } from '../src/tutorialRunWatch.mjs';
import { publishTaskbarObservation, rememberTaskbarTarget, resetTaskbarRunFeed, subscribeRunObservations, subscribeTaskbarObservations } from '../src/taskbarRunFeed.mjs';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('a run-view status for the installed case counts, and a different case does not', () => {
  const installed = 'air_water_horizontal.genkey';
  const running = demoRunSignal({
    kind: 'run',
    status: { run_id: 'run-1', state: 'running', command: ['olga', `C:/cases/${installed}`] },
  }, installed);
  assert.equal(running?.started, true);
  assert.equal(running?.finished, false);
  const done = demoRunSignal({
    kind: 'run',
    status: { run_id: 'run-1', state: 'completed', source_name: installed },
  }, installed);
  assert.equal(done?.finished, true);
  assert.equal(demoRunSignal({
    kind: 'run',
    status: { run_id: 'run-2', state: 'running', source_name: 'other.genkey' },
  }, installed), null);
});

test('taskbar observations reach a subscriber', () => {
  resetTaskbarRunFeed();
  const seen = [];
  const stop = subscribeTaskbarObservations((observation) => seen.push(observation.status.run_id));
  publishTaskbarObservation({ kind: 'run', status: { run_id: 'run-9', state: 'running' } });
  stop();
  publishTaskbarObservation({ kind: 'run', status: { run_id: 'run-10', state: 'running' } });
  assert.deepEqual(seen, ['run-9']);
  resetTaskbarRunFeed();
});

test('the tour channel sees a run the taskbar is not following', () => {
  resetTaskbarRunFeed();
  rememberTaskbarTarget({ kind: 'run', id: 'older-run' });
  const seen = [];
  const stop = subscribeRunObservations((observation) => seen.push(observation.status.run_id));
  publishTaskbarObservation({ kind: 'run', status: { run_id: 'demo-run', state: 'running' } });
  stop();
  assert.deepEqual(seen, ['demo-run']);
  resetTaskbarRunFeed();
});

test('the tour subscribes to run-view observations and status polls publish them', () => {
  const host = read('../src/TutorialHost.tsx');
  const api = read('../src/runApi.ts');
  assert.match(host, /subscribeRunObservations/);
  assert.match(api, /publishTaskbarObservation/);
  assert.match(host, /setValidatedCaseName\(null\)/);
  assert.match(host, /setValidationOk\(false\)/);
});

test('one install claim blocks a second gallery', () => {
  releaseExampleInstall(getExampleInstallBusy() ?? '');
  assert.equal(claimExampleInstall('air-water-horizontal'), true);
  assert.equal(claimExampleInstall('simple-pipeline'), false);
  releaseExampleInstall('air-water-horizontal');
  assert.equal(getExampleInstallBusy(), null);
});

test('a remembered demo applies only in the workspace that installed it', () => {
  const storage = { value: null, getItem: () => storage.value, setItem: (_key, value) => { storage.value = value; } };
  rememberExampleInstall({
    id: 'air-water-horizontal',
    demo: true,
    case_name: 'air_water_horizontal.genkey',
    case_rel: 'air_water_horizontal.genkey',
    table_rel: 'air_water.tab',
    topology: 'simple_pipeline',
    fluid: 'AIR_WATER',
    title_ko: '',
    title_en: '',
    description_ko: '',
    description_en: '',
    next: 'validate',
  }, storage, '/work/one');
  const home = loadRememberedExample(storage, '/work/one');
  assert.equal(home?.caseName, 'air_water_horizontal.genkey');
  assert.equal(loadRememberedExample(storage, '/work/two'), null);
});

test('install failures map to copy keys and the gallery does not show the server sentence', () => {
  assert.equal(exampleErrorKey('The workspace folder is not writable.'), 'examples.notWritable');
  assert.equal(exampleErrorKey('value or file not found'), 'examples.installFailed');
  const gallery = read('../src/ExampleGallery.tsx');
  const host = read('../src/TutorialHost.tsx');
  assert.match(gallery, /exampleErrorKey/);
  assert.doesNotMatch(gallery, /cause\.message/);
  assert.match(host, /exampleErrorKey/);
  assert.match(gallery, /aria-modal="true"/);
  assert.match(gallery, /stopPropagation/);
  assert.match(gallery, /focus\(/);
});

test('the gallery says it is loading, not empty, until the list arrives', () => {
  const gallery = read('../src/ExampleGallery.tsx');
  assert.match(gallery, /examples\.loading/);
  assert.match(gallery, /examples\.loadFailed/);
  assert.doesNotMatch(gallery, /\.catch\(\(\) => \{ if \(!cancelled\) setErrorKey\('examples\.installFailed'\)/);
  for (const file of ['../src/i18n/ko.ts', '../src/i18n/en.ts']) {
    const text = read(file);
    assert.match(text, /'examples\.loading':/);
    assert.match(text, /'examples\.loadFailed':/);
  }
});
