import assert from 'node:assert/strict';
import test from 'node:test';
import { describeChatError } from '../src/chatErrorPresentation.ts';
import { classifyApprovalResumeFailure } from '../src/runtimeLifecycle.mjs';
import { consumeApprovalResumeEvents } from '../src/sseClient.ts';

function conflictResponse(code, message) {
  return new Response(
    JSON.stringify({ code, message, state: 'failed', resume_allowed: false }),
    { status: 409, headers: { 'Content-Type': 'application/json' } },
  );
}

for (const code of ['approval_context_changed', 'approval_rejected', 'approval_dispatch_uncertain']) {
  test(`resume 409 ${code} is non-recoverable`, async () => {
    let observed;
    try {
      await consumeApprovalResumeEvents(conflictResponse(code, 'stale'), () => {});
    } catch (error) {
      observed = error;
    }
    assert.ok(observed, 'resume rejects on a 409 body');
    assert.match(observed.message, new RegExp(`\\(HTTP 409 ${code}\\)`));
    assert.equal(observed.code, code);
    assert.equal(describeChatError(observed.message).code, code);
    assert.deepEqual(classifyApprovalResumeFailure(observed), {
      state: 'failed',
      recoverable: false,
    });
  });
}

test('resume 409 without a code keeps the old recoverable behavior', async () => {
  let observed;
  try {
    await consumeApprovalResumeEvents(
      new Response('conflict', { status: 409 }),
      () => {},
    );
  } catch (error) {
    observed = error;
  }
  assert.match(observed?.message ?? '', /HTTP 409/);
  assert.equal(observed?.code, undefined);
  assert.deepEqual(classifyApprovalResumeFailure(observed), {
    state: 'finalizing',
    recoverable: true,
  });
});

test('resume 500 stays recoverable', async () => {
  let observed;
  try {
    await consumeApprovalResumeEvents(new Response('boom', { status: 500 }), () => {});
  } catch (error) {
    observed = error;
  }
  assert.deepEqual(classifyApprovalResumeFailure(observed), {
    state: 'finalizing',
    recoverable: true,
  });
});
