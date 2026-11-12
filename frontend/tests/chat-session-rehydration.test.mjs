import assert from 'node:assert/strict';
import test from 'node:test';
import {
  bootstrapChatSession,
  selectRestorableSession,
  visibleChatSessions,
} from '../src/chatSessionBootstrap.ts';
import { isSuccessfulToolStatus, rehydrateTimeline } from '../src/timeline.ts';

test('canonical approval history restores server identity and terminal state', () => {
  // Given: canonical pending and completed approval records from one session.
  const records = [
    {
      schema_version: 1,
      sequence: 4,
      record: 'approval',
      record_id: 'approval_pending',
      pending_id: 'pending_1',
      call_id: 'call_1',
      name: 'case_publish',
      args: { transaction_id: 'tx_1' },
      state: 'awaiting-approval',
      actionable: true,
    },
    {
      schema_version: 1,
      sequence: 7,
      record: 'approval',
      record_id: 'approval_completed',
      pending_id: 'pending_2',
      call_id: 'call_2',
      name: 'run_execute',
      args: { run_id: 'run_1' },
      state: 'completed',
    },
  ];

  // When: the persisted records cross the timeline boundary.
  const items = rehydrateTimeline(records);

  // Then: exact actionable receipts and resolved state are retained.
  assert.deepEqual(items, [
    {
      kind: 'approval',
      id: 'approval_pending',
      request: {
        name: 'case_publish',
        call_id: 'call_1',
        pending_id: 'pending_1',
        args: { transaction_id: 'tx_1' },
      },
      resolved: false,
    },
    {
      kind: 'approval',
      id: 'approval_completed',
      request: {
        name: 'run_execute',
        call_id: 'call_2',
        pending_id: 'pending_2',
        args: { run_id: 'run_1' },
      },
      resolved: true,
    },
  ]);
});

test('reconnect replay deduplicates canonical records without collapsing equal legacy text', () => {
  // Given: a reconnect repeats canonical records and one legacy equal-text turn follows.
  const records = [
    { record: 'assistant', record_id: 'assistant_1', text: 'Ready.' },
    { record: 'assistant', record_id: 'assistant_1', text: 'Ready.' },
    { record: 'assistant', text: 'Ready.' },
  ];

  // When: the combined replay is rehydrated once.
  const items = rehydrateTimeline(records);

  // Then: durable identity deduplicates only the repeated canonical record.
  assert.deepEqual(items, [
    { kind: 'assistant', id: 'assistant_1', text: 'Ready.' },
    { kind: 'assistant', id: 'assistant-2', text: 'Ready.' },
  ]);
});

test('legacy expired approval remains resolved and non-actionable', () => {
  // Given: a pre-schema approval record already invalidated by context drift.
  const records = [{
    record: 'approval',
    record_id: 'approval_expired',
    pending_id: 'pending_expired',
    call_id: 'call_expired',
    name: 'run_execute',
    args: {},
    resolved: true,
    resolution: 'context-expired',
  }];

  // When: legacy history is restored.
  const items = rehydrateTimeline(records);

  // Then: the approval cannot return as an actionable pending card.
  assert.deepEqual(items, [{
    kind: 'approval',
    id: 'approval_expired',
    request: {
      name: 'run_execute',
      call_id: 'call_expired',
      pending_id: 'pending_expired',
      args: {},
    },
    resolved: true,
    resolution: 'context-expired',
  }]);
});

test('session inventory keeps legacy sessions and hides tombstones', () => {
  // Given: one legacy session plus two tombstone representations.
  const sessions = [
    { session_id: 'legacy', title: 'Legacy' },
    { session_id: 'gone_a', title: 'Gone', tombstoned: true },
    { session_id: 'gone_b', title: 'Gone', state: 'tombstoned' },
  ];

  // When: the server inventory is projected for the menu.
  const visible = visibleChatSessions(sessions);

  // Then: backward-compatible live history remains and detached history is hidden.
  assert.deepEqual(visible, [{ session_id: 'legacy', title: 'Legacy' }]);
});

test('last selected session restores only when it is still valid', () => {
  // Given: a newest session and an older persisted selection.
  const sessions = [
    { session_id: 'newest', title: 'Newest' },
    { session_id: 'selected', title: 'Selected' },
  ];

  // When: selection is resolved against the live inventory.
  const selected = selectRestorableSession(sessions, 'selected');
  const fallback = selectRestorableSession(sessions, 'missing');

  // Then: a valid persisted selection wins and an invalid one falls back safely.
  assert.equal(selected?.session_id, 'selected');
  assert.equal(fallback?.session_id, 'newest');
});

test('StrictMode bootstrap remains read-only when the server has no chat history', async () => {
  // Given: two mounts race while the server has no chat history.
  let creates = 0;
  let releaseCreate = () => undefined;
  const createGate = new Promise((resolve) => { releaseCreate = resolve; });
  const dependencies = {
    preferredId: '',
    list: async () => [],
    create: async () => {
      creates += 1;
      await createGate;
      return 'created';
    },
    history: async () => [],
  };

  // When: both mounts request bootstrap before creation completes.
  const first = bootstrapChatSession(dependencies);
  const second = bootstrapChatSession(dependencies);
  releaseCreate();
  const [firstResult, secondResult] = await Promise.all([first, second]);

  // Then: opening the app does not create persisted empty history.
  assert.equal(creates, 0);
  assert.equal(firstResult.sessionId, '');
  assert.equal(secondResult.sessionId, '');
  assert.equal(firstResult.created, false);
});

test('bootstrap restores selected history without creating a replacement', async () => {
  // Given: a valid persisted session with canonical history.
  let creates = 0;
  const dependencies = {
    preferredId: 'selected',
    list: async () => [
      { session_id: 'newest', title: 'Newest' },
      { session_id: 'selected', title: 'Selected' },
    ],
    create: async () => {
      creates += 1;
      return 'unexpected';
    },
    history: async (id) => [{ record: 'user', record_id: 'user_1', text: id }],
  };

  // When: application bootstrap resolves the initial chat.
  const result = await bootstrapChatSession(dependencies);

  // Then: history is restored and no mutating create request is made.
  assert.equal(result.sessionId, 'selected');
  assert.equal(result.created, false);
  assert.deepEqual(result.records, [{ record: 'user', record_id: 'user_1', text: 'selected' }]);
  assert.equal(creates, 0);
});

test('canonical and legacy terminal success statuses both expose evidence', () => {
  // Given: the canonical persisted status and the live legacy status.
  // When: evidence eligibility is derived.
  // Then: both success spellings remain readable during migration.
  assert.equal(isSuccessfulToolStatus('completed'), true);
  assert.equal(isSuccessfulToolStatus('done'), true);
  assert.equal(isSuccessfulToolStatus('running'), false);
});

test('canonical approval completion folds into its pending card and retains reviewed args', () => {
  // Given: a reviewed approval followed by a sparse canonical execution receipt.
  const records = [
    { record: 'approval', record_id: 'pending', pending_id: 'p1', call_id: 'c1', name: 'case_publish', args: { transaction_id: 'tx1' }, state: 'awaiting-approval' },
    { record: 'approval', record_id: 'terminal', pending_id: 'p1', call_id: 'c1', name: 'case_publish', result: { ok: true }, state: 'completed', lifecycle: 'completed' },
  ];

  // When: canonical history is rehydrated.
  const items = rehydrateTimeline(records);

  // Then: one resolved card keeps the arguments the operator reviewed.
  assert.deepEqual(items, [{
    kind: 'approval', id: 'pending', resolved: true,
    request: { name: 'case_publish', call_id: 'c1', pending_id: 'p1', args: { transaction_id: 'tx1' } },
  }]);
});

test('legacy approval execution resolves its pending event without duplicating the card', () => {
  // Given: the historical event pair emitted by approval_execution.
  const records = [
    { record: 'event', record_id: 'legacy_pending', type: 'approval_required', pending_id: 'p1', call_id: 'c1', name: 'run_execute', args: { run_id: 'r1' } },
    { record: 'event', record_id: 'legacy_terminal', type: 'approval_executed', pending_id: 'p1', call_id: 'c1', name: 'run_execute', result: { ok: true } },
  ];

  // When: legacy history is rehydrated.
  const items = rehydrateTimeline(records);

  // Then: the original card is terminal and retains its exact request.
  assert.deepEqual(items, [{
    kind: 'approval', id: 'legacy_pending', resolved: true,
    request: { name: 'run_execute', call_id: 'c1', pending_id: 'p1', args: { run_id: 'r1' } },
  }]);
});

test('approval folding never merges distinct pending identities', () => {
  // Given: two requests share a call identity but have different pending receipts.
  const records = [
    { record: 'approval', record_id: 'first', pending_id: 'p1', call_id: 'c1', name: 'run_execute', args: {}, state: 'awaiting-approval' },
    { record: 'approval', record_id: 'second', pending_id: 'p2', call_id: 'c1', name: 'run_execute', args: {}, state: 'awaiting-approval' },
  ];

  // When: canonical history is rehydrated.
  const items = rehydrateTimeline(records);

  // Then: both independent approvals remain visible.
  assert.deepEqual(items.map((item) => item.id), ['first', 'second']);
});
