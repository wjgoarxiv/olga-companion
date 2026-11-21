import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import {
  classifyApprovalReceipt,
  classifyApprovalResumeFailure,
  createApprovalActionGuard,
  presentToolLifecycle,
  resolveApprovalCardLifecycle,
} from '../src/runtimeLifecycle.mjs';
import { describeChatError } from '../src/chatErrorPresentation.ts';
import { rehydrateTimeline } from '../src/timeline.ts';
import { consumeApprovalResumeEvents } from '../src/sseClient.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('approval receipt classification retains every explicit lifecycle state', () => {
  // Given: each server lifecycle and one authoritative ok:false receipt.
  const receipts = [
    { state: 'awaiting-approval' },
    { state: 'dispatched' },
    { state: 'running' },
    { state: 'resume_pending' },
    { state: 'completed', result: { ok: true } },
    { state: 'resumed', result: { ok: true } },
    { state: 'completed', result: { ok: false } },
    { state: 'uncertain' },
    { state: 'rejected' },
  ];

  // When: untrusted server receipts are classified for presentation.
  const states = receipts.map(classifyApprovalReceipt);

  // Then: no dispatch or ok:false response is mislabeled as done.
  assert.deepEqual(states, [
    'awaiting-approval',
    'dispatched',
    'running',
    'finalizing',
    'completed',
    'completed',
    'failed',
    'uncertain',
    'cancelled',
  ]);
  assert.deepEqual(states.map((state) => presentToolLifecycle({ state }).state), states);
});

test('approval guard claims dispatch once while allowing resume-only recovery', () => {
  // Given: one approval identity and a fresh action guard.
  const guard = createApprovalActionGuard();
  const identity = 'session-1:pending-1:call-1:7';

  // When: duplicate dispatch and simultaneous resume attempts arrive.
  const dispatch = guard.claimDispatch(identity);
  const duplicateDispatch = guard.claimDispatch(identity);
  const resume = guard.beginResume(identity);
  const duplicateResume = guard.beginResume(identity);

  // Then: dispatch is permanently single-use and resume is single-flight.
  assert.ok(dispatch);
  assert.equal(duplicateDispatch, null);
  assert.ok(resume);
  assert.equal(duplicateResume, null);
  guard.finishResume(resume);
  assert.ok(guard.beginResume(identity), 'transport recovery may retry resume without redispatch');
});

test('approval guard invalidation seals late dispatch and resume completions', () => {
  // Given: an in-flight dispatch and resume in the old workspace context.
  const guard = createApprovalActionGuard();
  const dispatch = guard.claimDispatch('old-context');
  const resume = guard.beginResume('old-context');
  assert.ok(dispatch);
  assert.ok(resume);

  // When: the workspace context is invalidated.
  guard.invalidate();

  // Then: both abort and neither can commit late UI state.
  assert.equal(dispatch.signal.aborted, true);
  assert.equal(resume.signal.aborted, true);
  assert.equal(guard.isCurrent(dispatch), false);
  assert.equal(guard.isCurrent(resume), false);
});

test('chat approval controller uses execute, resume SSE, and server rejection endpoints', async () => {
  // Given: the production controller and authenticated session API source.
  const [controller, api] = await Promise.all([
    read('../src/useChatController.ts'),
    read('../src/chatSessionApi.ts'),
  ]);

  // When/Then: approval dispatch and recovery never become synthetic user turns.
  assert.match(controller, /session\.executeApproval\(/);
  assert.match(controller, /session\.resumeApproval\(/);
  assert.match(controller, /session\.rejectApproval\(/);
  assert.doesNotMatch(controller, /Do not run it|Cancel that request/);
  assert.match(api, /\/api\/approvals\/resume/);
  assert.match(api, /\/api\/approvals\/reject/);
});

test('approval card keeps continuation recovery actionable after transport failure', async () => {
  // Given: the rendered approval card source.
  const [card, ko] = await Promise.all([
    read('../src/ApprovalCard.tsx'),
    read('../src/i18n/ko.ts'),
  ]);

  // When/Then: terminal resolution and resume recovery are distinct controls.
  assert.match(card, /t\('approval\.retryContinuation'\)/);
  assert.match(ko, /'approval\.retryContinuation': '계속 진행 다시 시도'/);
  assert.match(card, /finalizing|uncertain/);
  assert.match(card, /onRecover/);
});

test('settled resume marks the approved tool completed without replacing its receipt', async () => {
  // Given: the approval continuation hook owns the final stream settlement.
  const continuation = await read('../src/useApprovalContinuation.ts');

  // When/Then: stream settlement changes lifecycle only and preserves result evidence.
  assert.match(continuation, /updateTool\(request\.call_id, \{ status: 'completed' \}\)/);
  assert.doesNotMatch(continuation, /updateTool\(request\.call_id, \{ status: 'completed', result:/);
});

test('rehydration keeps a persisted resume-pending approval actionable without duplicating it', () => {
  // Given: dispatch succeeded, but assistant continuation was not observed before reload.
  const records = [
    { record: 'approval', record_id: 'pending', pending_id: 'p1', call_id: 'c1', name: 'case_publish', args: { transaction_id: 'tx1' }, state: 'awaiting-approval', actionable: true },
    { record: 'approval', record_id: 'receipt', pending_id: 'p1', call_id: 'c1', name: 'case_publish', state: 'resume_pending', resume_allowed: true },
  ];

  // When: canonical history is restored after transport or process recovery.
  const approvals = rehydrateTimeline(records).filter((item) => item.kind === 'approval');

  // Then: the original reviewed identity remains as one resume-only action.
  assert.equal(approvals.length, 1);
  assert.equal(approvals[0].resolved, false);
  assert.equal(approvals[0].lifecycle, 'finalizing');
  assert.equal(approvals[0].recoverable, true);
  assert.deepEqual(approvals[0].request.args, { transaction_id: 'tx1' });
});

test('legacy terminal approval records still render a truthful lifecycle label', () => {
  assert.equal(resolveApprovalCardLifecycle({ resolved: true }), 'completed');
  assert.equal(resolveApprovalCardLifecycle({ resolved: true, resolution: 'rejected' }), 'cancelled');
  assert.equal(resolveApprovalCardLifecycle({ resolved: false }), 'awaiting-approval');
  assert.equal(resolveApprovalCardLifecycle({ resolved: true, lifecycle: 'failed' }), 'failed');
});

test('HTTP-200 resume SSE rejects after forwarding an error event', async () => {
  const observed = [];
  const response = new Response('event: error\ndata: {"message":"provider continuation failed"}\n\n', {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  });

  await assert.rejects(
    consumeApprovalResumeEvents(response, (event) => observed.push(event)),
    /provider continuation failed/,
  );
  assert.equal(observed.length, 1);
  assert.equal(observed[0].type, 'error');
});

test('authoritative uncertain resume error is inspection-only while transport failure remains recoverable', async () => {
  const response = new Response(
    'event: error\ndata: {"message":"provider outcome is uncertain","state":"uncertain","resume_allowed":false}\n\n',
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  );
  let uncertainty;
  try {
    await consumeApprovalResumeEvents(response, () => {});
  } catch (error) {
    uncertainty = error;
  }

  assert.deepEqual(classifyApprovalResumeFailure(uncertainty), {
    state: 'uncertain',
    recoverable: false,
  });
  assert.deepEqual(classifyApprovalResumeFailure(new TypeError('connection reset')), {
    state: 'finalizing',
    recoverable: true,
  });
});

test('a bare 400 approval body is a closed refusal, never an uncertain card', async () => {
  // Given: the session API translation of an approval execute response.
  const [api] = await Promise.all([read('../src/chatSessionApi.ts')]);

  // When/Then: a body without a usable lifecycle state becomes failed with its detail intact.
  assert.match(api, /typeof record\.state === 'string' \? record\.state : 'failed'/);
  assert.doesNotMatch(api, /record\.state : 'uncertain'/);
});

test('uncertain is not a terminal approval state anywhere', async () => {
  // Given: the continuation hook and the shared presentation table.
  const [continuation, lifecycle] = await Promise.all([
    read('../src/useApprovalContinuation.ts'),
    read('../src/approvalActionLifecycle.mjs'),
  ]);

  // When/Then: both agree that an uncertain outcome is not settled.
  assert.match(lifecycle, /uncertain: Object\.freeze\(\{[^}]*terminal: false/);
  assert.doesNotMatch(continuation, /case 'uncertain':\s*\n\s*case 'cancelled':\s*\n\s*return true/);
});

test('a failed approval click keeps the refusal detail on the card', async () => {
  // Given: the approval continuation hook owns the click failure path.
  const [continuation] = await Promise.all([read('../src/useApprovalContinuation.ts')]);

  // When/Then: the caught detail is stored as the card result, not dropped.
  assert.match(continuation, /finishApproval\(request, state, \{ error:/);
});

test('sidecar failures do not wear the provider-response label', () => {
  // Given: a sidecar payload refusal and a real provider rejection.
  const sidecar = describeChatError("Unknown temperature unit 'C'.");
  const provider = describeChatError('The provider rejected the request (400): quota');

  // When/Then: only the provider failure keeps the provider label.
  assert.equal(sidecar.detailsKey, 'chat.errSidecarDetails');
  assert.equal(provider.detailsKey, 'chat.errDetails');
});

test('the error row names only real provider failures as provider responses', async () => {
  // Given: both locales and the chat error row.
  const [ko, en, view] = await Promise.all([
    read('../src/i18n/ko.ts'),
    read('../src/i18n/en.ts'),
    read('../src/ChatView.tsx'),
  ]);

  // When/Then: the sidecar label exists in ko and en and the row uses the described key.
  assert.match(ko, /'chat\.errSidecarDetails':/);
  assert.match(en, /'chat\.errSidecarDetails':/);
  assert.match(view, /described\.detailsKey/);
  assert.doesNotMatch(view, /\{t\('chat\.errDetails'\)\}/);
});
