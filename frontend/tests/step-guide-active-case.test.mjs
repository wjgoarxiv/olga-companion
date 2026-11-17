import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function file(name, suffix, rel = name) {
  return { name, rel, suffix, size: 1 };
}

function sourcePlan(source) {
  return {
    kind: 'tool',
    id: `edit-${source}`,
    name: 'case_edit_plan',
    callId: `c-${source}`,
    status: 'completed',
    args: { source, source_hash: 'a'.repeat(64), operations: [{ op: 'note' }] },
    result: {
      publishable: true,
      source_kind: 'source',
      validation: { clean: true, parser_clean: true, validator_clean: true, diagnostics: [] },
    },
  };
}

function compiledSpec(owner, pvt) {
  return {
    kind: 'tool',
    id: `compile-${owner}`,
    name: 'case_spec_compile',
    callId: `c-${owner}`,
    status: 'completed',
    args: { owner_source: owner, spec: { pvt_reference: pvt } },
    result: {
      valid: true,
      normalized: { pvt_reference: pvt, fluid_label: 'air-water' },
    },
  };
}

const workspace = [
  file('old.genkey', '.genkey'),
  file('old.tpl', '.tpl'),
  file('old.ppl', '.ppl'),
  file('fluid.tab', '.tab'),
  file('example.genkey', '.genkey'),
];

test('older outputs and evidence do not finish a fresh example case', async () => {
  const { activeCaseStepFacts, deriveStepStates, deriveNextAction } = await import('../src/shell/useStepState.ts');
  const facts = activeCaseStepFacts({
    activeCaseName: 'example.genkey',
    cases: workspace,
    timeline: [sourcePlan('old.genkey'), compiledSpec('old.genkey', 'fluid.tab')],
  });
  assert.equal(facts.hasRunOutputs, false);
  assert.equal(facts.hasEvidence, false);
  assert.equal(facts.tabCount, 1, 'PVTFILE is unknown, so any workspace .tab still counts');
  const states = deriveStepStates({
    activeCaseName: 'example.genkey',
    tabCount: facts.tabCount,
    hasRunOutputs: facts.hasRunOutputs,
    errorCount: 0,
    hasEvidence: facts.hasEvidence,
    preferredResultId: null,
  });
  assert.deepEqual(states.map((step) => step.status), ['done', 'upcoming', 'current', 'upcoming', 'upcoming']);
  const next = deriveNextAction({ states, canCreateFluid: true, activeView: 'workspace' });
  assert.equal(next.labelKey, 'stepbar.next.validate');
  assert.notEqual(next.labelKey, 'stepbar.next.results');
});

test('outputs and evidence count only when they name the active case', async () => {
  const { activeCaseStepFacts, deriveStepStates, deriveNextAction } = await import('../src/shell/useStepState.ts');
  const withOwnOutput = activeCaseStepFacts({
    activeCaseName: 'example.genkey',
    cases: [...workspace, file('runs/example.tpl', '.tpl', 'runs/example.tpl')],
    timeline: [sourcePlan('old.genkey')],
  });
  assert.equal(withOwnOutput.hasRunOutputs, true);
  assert.equal(withOwnOutput.hasEvidence, false);

  const named = activeCaseStepFacts({
    activeCaseName: 'example.genkey',
    cases: workspace,
    timeline: [sourcePlan('old.genkey'), sourcePlan('cases/example.genkey')],
  });
  assert.equal(named.hasEvidence, true);
  const ready = deriveStepStates({
    activeCaseName: 'example.genkey',
    tabCount: named.tabCount,
    hasRunOutputs: false,
    errorCount: 0,
    hasEvidence: named.hasEvidence,
    preferredResultId: null,
  });
  assert.equal(deriveNextAction({ states: ready, canCreateFluid: true }).labelKey, 'stepbar.next.run');
});

test('a knowable PVTFILE scopes the table check; an unnamed spec does not', async () => {
  const { activeCaseStepFacts, deriveStepStates, deriveNextAction } = await import('../src/shell/useStepState.ts');
  const missing = activeCaseStepFacts({
    activeCaseName: 'example.genkey',
    cases: workspace,
    timeline: [compiledSpec('example.genkey', 'example.tab')],
  });
  assert.equal(missing.hasEvidence, true);
  assert.equal(missing.tabCount, 0, 'example.tab is the case table and it is absent');
  const blocked = deriveStepStates({
    activeCaseName: 'example.genkey',
    tabCount: missing.tabCount,
    hasRunOutputs: missing.hasRunOutputs,
    errorCount: 0,
    hasEvidence: missing.hasEvidence,
    preferredResultId: null,
  });
  assert.equal(blocked[2].status, 'blocked');
  assert.equal(blocked[2].reason, 'noTab');
  assert.equal(deriveNextAction({ states: blocked, canCreateFluid: true }).labelKey, 'stepbar.next.createFluid');

  const present = activeCaseStepFacts({
    activeCaseName: 'example.genkey',
    cases: [...workspace, file('example.tab', '.tab')],
    timeline: [compiledSpec('subdir/example.genkey', 'tables/example.tab')],
  });
  assert.equal(present.tabCount, 1);

  const unnamed = activeCaseStepFacts({
    activeCaseName: 'example.genkey',
    cases: workspace,
    timeline: [{
      kind: 'tool',
      id: 'validate-unnamed',
      name: 'case_spec_validate',
      callId: 'c-unnamed',
      status: 'completed',
      args: { spec: { pvt_reference: 'missing.tab' } },
      result: { valid: true, normalized: { pvt_reference: 'missing.tab' } },
    }],
  });
  assert.equal(unnamed.hasEvidence, false);
  assert.equal(unnamed.tabCount, 1, 'a spec with no case name is not this case\'s PVTFILE');
});

test('step state is computed once and passed into the bar', async () => {
  const [bar, slot] = await Promise.all([
    read('../src/shell/StepBar.tsx'),
    read('../src/shell/StepBarSlot.tsx'),
  ]);
  assert.doesNotMatch(bar, /useStepStates\(/);
  assert.match(slot, /useStepStates\(/);
  assert.match(slot, /states=\{states\}/);
});

test('a clean title-bar validation of the active case moves the bar to running', async () => {
  const { activeCaseStepFacts, deriveStepStates, deriveNextAction } = await import('../src/shell/useStepState.ts');
  const { recordDirectValidation, getDirectValidations, resetDirectValidations } = await import('../src/shell/directValidation.ts');
  resetDirectValidations();
  recordDirectValidation('other.genkey', true);
  const before = activeCaseStepFacts({
    activeCaseName: 'example.genkey', cases: workspace, timeline: [], directValidations: getDirectValidations(),
  });
  assert.equal(before.hasEvidence, false, 'another case validating does not count');
  recordDirectValidation('example.genkey', true);
  const facts = activeCaseStepFacts({
    activeCaseName: 'example.genkey', cases: workspace, timeline: [], directValidations: getDirectValidations(),
  });
  assert.equal(facts.hasEvidence, true);
  const states = deriveStepStates({
    activeCaseName: 'example.genkey',
    tabCount: facts.tabCount,
    hasRunOutputs: facts.hasRunOutputs,
    errorCount: 0,
    hasEvidence: facts.hasEvidence,
    preferredResultId: null,
  });
  assert.equal(states[2].status, 'done');
  assert.equal(states[3].status, 'current');
  assert.notEqual(deriveNextAction({ states, canCreateFluid: true, activeView: 'workspace' }).labelKey, 'stepbar.next.validate');
  recordDirectValidation('example.genkey', false);
  assert.equal(activeCaseStepFacts({
    activeCaseName: 'example.genkey', cases: workspace, timeline: [], directValidations: getDirectValidations(),
  }).hasEvidence, false, 'a later failed check withdraws it');
  resetDirectValidations();
});

test('a run started from the Run view shows the active case as running', async () => {
  const { recordDirectRun, directRunInFlight, resetDirectValidations } = await import('../src/shell/directValidation.ts');
  resetDirectValidations();
  const source = 'C:\\ws\\example.genkey';
  recordDirectRun({ run_id: 'r1', state: 'running', source });
  assert.equal(directRunInFlight('example.genkey'), true);
  assert.equal(directRunInFlight('other.genkey'), false);
  recordDirectRun({ run_id: 'r1', state: 'completed', source });
  assert.equal(directRunInFlight('example.genkey'), false);
  recordDirectRun({ run_id: 'r2', state: 'running', source_name: 'example.genkey' });
  assert.equal(directRunInFlight('example.genkey'), true);
  resetDirectValidations();
  assert.equal(directRunInFlight('example.genkey'), false);
});

test('the step bar listens to Run-view runs', async () => {
  const slot = await read('../src/shell/StepBarSlot.tsx');
  assert.match(slot, /subscribeRunObservations/);
  assert.match(slot, /directRunInFlight/);
});

test('Run-view status observations carry the case the run was started for', async () => {
  const api = await read('../src/runApi.ts');
  assert.match(api, /runSources\.set\(/);
  assert.match(api, /const source = runSources\.get\(runId\)/);
});

test('an open result counts only for the case it was opened under', async () => {
  const slot = await read('../src/shell/StepBarSlot.tsx');
  assert.match(slot, /resultOwner/);
  assert.match(slot, /preferredResultId: scopedResultId/);
});
