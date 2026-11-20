import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';
import {
  blankEnd, isPipeTableWizardShown, markPipeTableWizardShown, subscribePipeTableWizardShown, wizardBoundaries, wizardRequest,
} from '../src/pipeTableWizard.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const filled = (node, kind) => ({
  ...blankEnd(node), kind, pressureBar: '12', temperatureC: '40', gasFraction: '1', waterFraction: '0.9',
});

test('end value fields shrink to the dialog instead of spilling past its edge', async () => {
  const css = await read('../src/styles/fluid-table-flow.css');
  const rule = (selector) => css.match(new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`))?.[1] ?? '';
  assert.match(rule('.pipe-wizard-ends fieldset'), /min-inline-size:\s*0/);
  assert.match(rule('.pipe-wizard-ends .fluid-field'), /min-width:\s*0/);
  assert.match(rule('.pipe-wizard-ends .fluid-field input, .pipe-wizard-ends .fluid-field select'), /width:\s*100%/);
});

test('opening the wizard closes the step guide that launched it, so two dialogs never overlap', async () => {
  const bar = await read('../src/shell/StepBar.tsx');
  assert.match(bar, /subscribePipeTableWizard\(\(\) => setOpenStep\(null\)\)/);
});

test('only one table dialog is open at a time', async () => {
  const slot = await read('../src/shell/StepBarSlot.tsx');
  assert.match(slot, /if \(flowSignal > 0\) \{ setFlowOpen\(true\); setWizardOpen\(false\); \}/);
  assert.match(slot, /if \(wizardSignal > 0\) \{ setWizardOpen\(true\); setFlowOpen\(false\); \}/);
});

test('the wizard reports while it is on screen, and listeners hear each change once', () => {
  const heard = [];
  const stop = subscribePipeTableWizardShown(() => heard.push(isPipeTableWizardShown()));
  markPipeTableWizardShown(true);
  markPipeTableWizardShown(true);
  markPipeTableWizardShown(false);
  stop();
  markPipeTableWizardShown(true);
  markPipeTableWizardShown(false);
  assert.deepEqual(heard, [true, false]);
});

test('while the wizard is open the tour keeps running and only its card steps aside', async () => {
  const [host, wizard] = await Promise.all([read('../src/TutorialHost.tsx'), read('../src/shell/PipeTableWizard.tsx')]);
  // Pausing would rebase the pipe-case step on the newly saved case, so the step could never complete.
  assert.doesNotMatch(host, /subscribePipeTableWizard\(/);
  assert.match(host, /useSyncExternalStore\(subscribePipeTableWizardShown, isPipeTableWizardShown/);
  assert.match(host, /step !== null && !chipPending && !wizardShown/);
  assert.match(wizard, /markPipeTableWizardShown\(true\);\s*return \(\) => markPipeTableWizardShown\(false\);/);
});

test('table problems read in the app language, and a missing line column says how to fix it', async () => {
  const wizard = await read('../src/shell/PipeTableWizard.tsx');
  assert.match(wizard, /formatDraftReason\(/);
  assert.doesNotMatch(wizard, /\{issue\.reason\}/);
  assert.match(wizard, /missing_flowpath[\s\S]{0,200}pipeWizard\.needLineColumn/);
  assert.ok(ko['pipeWizard.needLineColumn'] && en['pipeWizard.needLineColumn']);
  assert.notEqual(ko['pipeWizard.needLineColumn'], en['pipeWizard.needLineColumn']);
  assert.match(ko['pipeWizard.needLineColumn'], /라인/);
});

test('end values become SI boundaries the chat import takes as they are', () => {
  assert.deepEqual(wizardBoundaries([filled('유정A', 'source'), filled('분리기', 'sink')]), [
    { node: '유정A', kind: 'source', pressure_pa: 1200000, temperature_c: 40, gas_fraction: 1, water_fraction: 0.9 },
    { node: '분리기', kind: 'sink', pressure_pa: 1200000, temperature_c: 40, gas_fraction: 1, water_fraction: 0.9 },
  ]);
});

test('a missing kind, a blank value or a fraction above 1 holds the save', () => {
  assert.equal(wizardBoundaries([{ ...filled('A', 'source'), kind: '' }]), null);
  assert.equal(wizardBoundaries([{ ...filled('A', 'source'), pressureBar: '' }]), null);
  assert.equal(wizardBoundaries([{ ...filled('A', 'source'), pressureBar: '-1' }]), null);
  assert.equal(wizardBoundaries([{ ...filled('A', 'source'), waterFraction: '1.2' }]), null);
  assert.deepEqual(wizardBoundaries([]), []);
});

test('the save request names the table, the .tab, the end time and the exact boundaries', () => {
  const t = (key, params) => Object.entries(params ?? {}).reduce(
    (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)), ko[key]);
  const text = wizardRequest(t, {
    path: '집유망.csv', tab: 'fluid.tab', endTimeS: 600, thermal: 'adiabatic',
    boundaries: wizardBoundaries([filled('유정A', 'source')]),
  });
  assert.match(text, /집유망\.csv/);
  assert.match(text, /fluid\.tab/);
  assert.match(text, /600/);
  assert.match(text, /"pressure_pa":1200000/);
  assert.match(text, /pipe_table_import/);
});

test('ko and en carry the same wizard keys', () => {
  const keys = (dict) => Object.keys(dict).filter((key) => key.startsWith('pipeWizard.')).sort();
  assert.ok(keys(ko).length > 10);
  assert.deepEqual(keys(ko), keys(en));
});

test('the wizard saves only by drafting a chat request: no approval, no write of its own', async () => {
  const source = await read('../src/shell/PipeTableWizard.tsx');
  assert.doesNotMatch(source, /approve|approval_token|case_publish|\/api\/(?!pipe-table\/)/);
  assert.match(source, /chat\.setInput\(/);
  assert.match(source, /onOpenDock\(\)/);
});

test('the wizard opens from the palette and from step ① detail', async () => {
  const [keymap, commands, hook, guide, slot] = await Promise.all([
    read('../src/shell/keymap.ts'), read('../src/shell/commands.ts'), read('../src/shell/useWorkbenchCommands.ts'),
    read('../src/SimulationGuide.tsx'), read('../src/shell/StepBarSlot.tsx'),
  ]);
  assert.match(keymap, /\| 'pipe-table-wizard'/);
  assert.match(commands, /id: 'pipe-table-wizard'/);
  assert.match(hook, /id === 'pipe-table-wizard'/);
  assert.match(guide, /PIPE_TABLE_WIZARD_EVENT/);
  assert.match(slot, /<PipeTableWizard/);
});
