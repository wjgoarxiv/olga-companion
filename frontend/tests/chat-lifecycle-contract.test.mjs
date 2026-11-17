import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import * as progressPresentation from '../src/progressPresentation.mjs';
import * as resultPresentation from '../src/resultPresentation.ts';
import * as runtimeLifecycle from '../src/runtimeLifecycle.mjs';
import * as timeline from '../src/timeline.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('rehydrated tool events return exact call identity, arguments, result, and lifecycle', () => {
  // Given: the persisted legacy event pair for one completed tool call.
  const args = { result_id: 'result_A', variables: ['PT', 'TM'] };
  const result = { ok: true, rows: [{ time_s: 0, PT: 2.4 }] };
  const records = [
    {
      record: 'event',
      record_id: 'record_tool_call_1',
      type: 'tool_call',
      call_id: 'call_exact_42',
      name: 'results_series',
      args,
    },
    {
      record: 'event',
      record_id: 'record_tool_result_1',
      type: 'tool_result',
      call_id: 'call_exact_42',
      name: 'results_series',
      result,
    },
  ];

  // When: the existing executable rehydrator restores the timeline.
  const items = timeline.rehydrateTimeline(records);

  // Then: the two events become one exact evidence unit.
  assert.deepEqual(items, [{
    kind: 'tool',
    id: 'record_tool_call_1',
    callId: 'call_exact_42',
    name: 'results_series',
    args,
    result,
    status: 'completed',
  }]);
});

test('rehydrated approval event returns the exact actionable server receipt', () => {
  // Given: one persisted unresolved approval event.
  const args = { source_id: 'case_A', source_sha256: 'a'.repeat(64) };
  const records = [{
    record: 'event',
    record_id: 'record_approval_1',
    type: 'approval_required',
    call_id: 'call_publish_1',
    pending_id: 'pending_publish_1',
    name: 'case_publish',
    args,
    actionable: true,
  }];

  // When: the existing executable rehydrator restores the timeline.
  const items = timeline.rehydrateTimeline(records);

  // Then: only the exact actionable approval is reconstructed.
  assert.deepEqual(items, [{
    kind: 'approval',
    id: 'record_approval_1',
    request: {
      name: 'case_publish',
      call_id: 'call_publish_1',
      pending_id: 'pending_publish_1',
      args,
    },
    resolved: false,
  }]);
});

test('rehydrated run approval preserves the separate server-reviewed display receipt', () => {
  const args = { source: 'case.genkey', selection_id: 'selection_exact' };
  const display = {
    case: 'case.genkey',
    selection_id: 'selection_exact',
    runtime_id: 'olga-2022.1',
    source_sha256: 'a'.repeat(64),
    output_target: 'managed-run-sandbox',
  };
  const items = timeline.rehydrateTimeline([{
    record: 'event', record_id: 'run_approval', type: 'approval_required',
    call_id: 'call_run', pending_id: 'pending_run', name: 'run_execute',
    args, display, actionable: true,
  }]);

  assert.deepEqual(items, [{
    kind: 'approval', id: 'run_approval', resolved: false,
    request: { name: 'run_execute', call_id: 'call_run', pending_id: 'pending_run', args, display },
  }]);
});

test('persisted pending approval expires after restart without server actionability proof', () => {
  // Given: history says pending, but the restarted server did not prove the receipt is active.
  const records = [{
    record: 'approval',
    record_id: 'approval_stale_1',
    pending_id: 'pending_stale_1',
    call_id: 'call_stale_1',
    name: 'case_publish',
    args: { transaction_id: 'tx_stale_1' },
    state: 'pending',
  }];

  // When: persisted history is restored after restart.
  const items = timeline.rehydrateTimeline(records);

  // Then: stale history cannot mint an actionable approval card.
  assert.deepEqual(items, [{
    kind: 'approval',
    id: 'approval_stale_1',
    request: {
      name: 'case_publish',
      call_id: 'call_stale_1',
      pending_id: 'pending_stale_1',
      args: { transaction_id: 'tx_stale_1' },
    },
    resolved: true,
    resolution: 'context-expired',
  }]);
});

test('assistant rehydration deduplicates by durable identity rather than equal text', () => {
  // Given: one repeated record and another distinct record with the same text.
  const records = [
    { record: 'assistant', record_id: 'assistant_1', text: '검토가 완료되었습니다.' },
    { record: 'assistant', record_id: 'assistant_1', text: '검토가 완료되었습니다.' },
    { record: 'assistant', record_id: 'assistant_2', text: '검토가 완료되었습니다.' },
  ];

  // When: the existing executable rehydrator restores the timeline.
  const items = timeline.rehydrateTimeline(records);

  // Then: the duplicate identity is removed while the distinct turn remains.
  assert.deepEqual(items, [
    { kind: 'assistant', id: 'assistant_1', text: '검토가 완료되었습니다.' },
    { kind: 'assistant', id: 'assistant_2', text: '검토가 완료되었습니다.' },
  ]);
});

test('runtime lifecycle presenter maps all eight production states without generic done', () => {
  // Given: every explicit lifecycle state accepted by the production contract.
  const states = [
    'awaiting-approval',
    'dispatched',
    'running',
    'finalizing',
    'completed',
    'failed',
    'uncertain',
    'cancelled',
  ];
  assert.equal(typeof runtimeLifecycle.presentToolLifecycle, 'function');

  // When: the existing lifecycle module presents each state.
  const presented = states.map((state) => runtimeLifecycle.presentToolLifecycle({ state }));

  // Then: state identity is retained and the ambiguous legacy done state is absent.
  assert.deepEqual(presented.map((item) => item.state), states);
  assert.equal(presented.some((item) => item.state === 'done'), false);
});

test('completed run evidence with ok false is presented as failed', () => {
  // Given: terminal output exists but the authoritative receipt reports failure.
  const result = {
    id: 'result_failed_1',
    name: 'case.tpl',
    rel: 'case.tpl',
    origin: 'run',
    size: 100,
    suffix: '.tpl',
    modified_ns: 1,
    run_state: 'completed',
    run_ok: false,
  };

  // When: the existing executable result presenter labels the receipt.
  const label = resultPresentation.resultStatusLabel(result);

  // Then: ok:false cannot become Completed or Partial.
  assert.equal(label, 'Failed');
});

test('result presenter returns opaque artifact metadata and contained destination actions', () => {
  // Given: one authenticated plot artifact receipt.
  const receipt = {
    artifact_id: 'artifact_plot_1',
    kind: 'plot',
    mime: 'image/png',
    suggested_filename: 'pressure-profile.png',
    size: 1024,
    sha256: 'b'.repeat(64),
  };
  assert.equal(typeof resultPresentation.presentArtifactReceipt, 'function');

  // When: the existing result presentation module builds the UI receipt.
  const presentation = resultPresentation.presentArtifactReceipt(receipt);

  // Then: actions retain only the opaque identifier, never a sandbox pseudo-link.
  assert.deepEqual(presentation, {
    receipt,
    actions: [
      { kind: 'save-as', artifact_id: 'artifact_plot_1' },
      { kind: 'open-results', artifact_id: 'artifact_plot_1' },
    ],
  });
  assert.equal(JSON.stringify(presentation).includes('sandbox:'), false);
});

test('progress presenter returns deterministic phase, elapsed, cancel, and static motion', () => {
  // Given: a cancellable running activity under reduced-motion preference.
  assert.equal(typeof progressPresentation.presentChatActivity, 'function');
  const input = {
    phase: 'running',
    started_at_ms: 1_000,
    now_ms: 4_500,
    cancellable: true,
    reduced_motion: true,
  };

  // When: the existing progress presentation module renders supplied timestamps.
  const presentation = progressPresentation.presentChatActivity(input);

  // Then: activity is truthful, deterministic, and non-animated.
  assert.deepEqual(presentation, {
    phase: 'running',
    label: 'Running',
    elapsed_ms: 3_500,
    can_cancel: true,
    motion: 'static',
  });
  assert.equal(progressPresentation.presentChatActivity({ ...input, phase: 'finalizing' }).can_cancel, false);
});

test('CJK and technical evidence use Pretendard with local table and plot overflow', async () => {
  // Given: Korean prose, long paths and hashes, wide tables, and plots.
  const [base, messages, tools] = await Promise.all([
    read('../src/styles/base.css'),
    read('../src/styles/chat-messages.css'),
    read('../src/styles/chat-tools.css'),
  ]);

  // When: the supplemental rendered-style contract is inspected.
  // Then: typography wraps and horizontal scrolling belongs to local viewports.
  assert.match(base, /--font-ui:\s*"Pretendard Variable"/);
  assert.match(messages, /\.bubble\s*\{[^}]*overflow-wrap:\s*anywhere/s);
  assert.match(messages, /\.md-table-wrap\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(tools, /\.evidence-value-technical\s*\{[^}]*overflow-wrap:\s*anywhere/s);
  assert.match(tools, /\.evidence-plot-viewport\s*\{[^}]*overflow-x:\s*auto/s);
  assert.doesNotMatch(base, /(?:html|body)[^{]*\{[^}]*overflow-x:\s*hidden/s);
});
