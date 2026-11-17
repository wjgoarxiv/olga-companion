import assert from 'node:assert/strict';
import test from 'node:test';

// lnlow step-bar RED-first: a successful source-mode case_edit_plan result
// with clean validation counts as case evidence (no case_spec_validate card
// exists in that chat, so the bar must not stall on "2 Edit").
const tool = (overrides = {}) => ({
  kind: 'tool',
  id: 't1',
  name: 'case_edit_plan',
  callId: 'c1',
  status: 'completed',
  args: { source: 'copy.genkey', source_hash: '0'.repeat(64), operations: [] },
  result: {
    publishable: true,
    source_kind: 'source',
    validation: { clean: true, parser_clean: true, validator_clean: true, diagnostics: [] },
  },
  ...overrides,
});

test('lnlow step-bar: successful source-mode case_edit_plan is case evidence', async () => {
  const { latestCaseEvidence } = await import('../src/shell/useStepState.ts');
  assert.ok(latestCaseEvidence([tool()]) !== null, 'clean source-mode edit plan must count');
});

test('lnlow step-bar: failed or unclean edit plans are not evidence', async () => {
  const { latestCaseEvidence } = await import('../src/shell/useStepState.ts');
  assert.equal(
    latestCaseEvidence([tool({ result: { publishable: false, source_kind: 'source', failed_step: 0, errors: [] } })]),
    null,
  );
  assert.equal(
    latestCaseEvidence([tool({
      result: {
        publishable: true, source_kind: 'source',
        validation: { clean: false, parser_clean: true, validator_clean: false, diagnostics: ['x'] },
      },
    })]),
    null,
  );
});

test('lnlow step-bar: source-mode evidence completes Edit and Check', async () => {
  const { deriveStepStates, latestCaseEvidence } = await import('../src/shell/useStepState.ts');
  const hasEvidence = latestCaseEvidence([tool()]) !== null;
  const states = deriveStepStates({
    activeCaseName: 'copy.genkey', tabCount: 1, hasRunOutputs: false,
    errorCount: 0, hasEvidence, preferredResultId: null,
  });
  assert.equal(states[1].status, 'done', '2 Edit must be done');
  assert.equal(states[2].status, 'done', '3 Check must be done');
});
