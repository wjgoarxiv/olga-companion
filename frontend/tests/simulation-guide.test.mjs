import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { translate } from '../src/i18n/index.ts';

test('the beginner journey covers creation, safe editing, preflight, approved run and evidence-based analysis', async () => {
  const { SIMULATION_STEPS } = await import('../src/simulationSteps.ts');
  assert.deepEqual(SIMULATION_STEPS.map((step) => step.id), ['create', 'edit', 'validate', 'run', 'analyze']);
  assert.equal(SIMULATION_STEPS[0].requiresCase, false);
  assert.ok(SIMULATION_STEPS.slice(1).every((step) => step.requiresCase));
  for (const step of SIMULATION_STEPS) {
    assert.ok(step.titleKey && step.descriptionKey && step.promptKey && step.checkKey);
    assert.ok(translate('ko', step.titleKey).length > 0, `${step.id} title resolves in ko`);
    assert.ok(translate('en', step.titleKey).length > 0, `${step.id} title resolves in en`);
    assert.ok(translate('ko', step.promptKey).length > 0, `${step.id} prompt resolves in ko`);
    assert.ok(translate('en', step.promptKey).length > 0, `${step.id} prompt resolves in en`);
  }
  assert.match(translate('ko', SIMULATION_STEPS[0].promptKey), /하나씩/);
  assert.match(translate('ko', SIMULATION_STEPS[0].promptKey), /임의로/);
  assert.match(translate('ko', SIMULATION_STEPS[1].promptKey), /원본/);
  assert.match(translate('ko', SIMULATION_STEPS[2].promptKey), /실행하지/);
  assert.match(translate('ko', SIMULATION_STEPS[3].promptKey), /승인/);
  assert.match(translate('ko', SIMULATION_STEPS[4].promptKey), /단위/);
  assert.match(translate('ko', SIMULATION_STEPS[4].promptKey), /결과 파일/);
  assert.match(translate('en', SIMULATION_STEPS[0].promptKey), /approval/i);
  assert.match(translate('en', SIMULATION_STEPS[2].promptKey), /yet/i);
  assert.doesNotMatch(translate('en', SIMULATION_STEPS[0].promptKey), /[가-힣]/, 'en prompt carries no Hangul');
});

test('guide prepares an editable message, never sends or approves it, and preserves a safe recovery path', async () => {
  const guide = await readFile(new URL('../src/SimulationGuide.tsx', import.meta.url), 'utf8');
  const chat = await readFile(new URL('../src/ChatView.tsx', import.meta.url), 'utf8');
  assert.match(guide, /selectedStep/, 'the popover owns which step detail shows');
  assert.match(guide, /onDraft\(t\(step\.promptKey\)\)/);
  assert.match(guide, /onOpenWorkspace/);
  assert.match(guide, /onOpenSettings/);
  assert.match(guide, /disabled=\{blocked \|\| props.hasDraft\}/);
  assert.doesNotMatch(guide, /run_execute|executeApproval|onApprove|onPickStarter/);
  assert.match(chat, /props.onInput\(prompt\)/);
  assert.match(chat, /if \(props.input.trim\(\)\) return/);
  assert.match(chat, /composerRef.current\?\.focus\(\)/);
  assert.match(chat, /aria-label=\{t\('composer\.questionLabel'\)\}/);
});

test('composer supports reviewing multiline drafts, explicit clearing and composition-safe keyboard submission', async () => {
  const chat = await readFile(new URL('../src/ChatView.tsx', import.meta.url), 'utf8');
  assert.match(chat, /useRef<HTMLTextAreaElement>/);
  assert.match(chat, /<textarea[\s\S]*rows=\{3\}/);
  assert.match(chat, /event\.nativeEvent\.isComposing/);
  assert.match(chat, /event\.ctrlKey \|\| event\.metaKey/);
  assert.match(chat, /requestSubmit\(\)/);
  assert.match(chat, /onInput\(''\)/);
  assert.match(chat, /t\('composer\.clearAction'\)/);
  assert.match(chat, /aria-describedby="chat-composer-hint"/);
  assert.match(chat, /props.timeline.length > 0 && !props.atBottom/);
  assert.doesNotMatch(chat, /className="to-bottom"/);
});

test('first screen removes repeated context and navigates steps from the step-bar popover', async () => {
  const empty = await readFile(new URL('../src/EmptyState.tsx', import.meta.url), 'utf8');
  const guide = await readFile(new URL('../src/SimulationGuide.tsx', import.meta.url), 'utf8');
  const stepbar = await readFile(new URL('../src/shell/StepBar.tsx', import.meta.url), 'utf8');
  const css = await readFile(new URL('../src/styles/simulation-guide.css', import.meta.url), 'utf8');
  assert.doesNotMatch(empty, /empty-context/);
  assert.doesNotMatch(guide, /simulation-guide-context/);
  assert.doesNotMatch(guide, /<select/, 'the step picker lives in the stepper, not the popover');
  assert.match(stepbar, /stepbar\.prevStep/, 'popover footer steps back');
  assert.match(stepbar, /stepbar\.nextStep/, 'popover footer steps forward');
  assert.match(css, /\.simulation-guide-detail dl\s*\{[^}]*display:\s*block/s);
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.simulation-guide-steps\s*\{\s*display:\s*none/s);
});
