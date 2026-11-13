import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readSessionSource } from './session-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test('delayed approval mint cannot send a token, report an error, or release newer busy state after invalidation', async () => {
  const { createApprovalMintLifecycle, runApprovalMint } = await import('../src/approvalMintLifecycle.mjs');
  const lifecycle = createApprovalMintLifecycle();
  const mint = deferred();
  const sent = [];
  const errors = [];
  let busyOwner = 'approval-1';

  const pending = runApprovalMint(
    lifecycle,
    7,
    () => 7,
    (signal) => {
      assert.equal(signal.aborted, false);
      return mint.promise;
    },
    {
      onToken: async (token) => { sent.push(token); },
      onError: (error) => { errors.push(error.message); },
      onFinish: () => { busyOwner = null; },
    },
  );

  lifecycle.invalidate();
  busyOwner = 'new-context';
  mint.resolve('stale-token');
  await pending;

  assert.deepEqual(sent, []);
  assert.deepEqual(errors, []);
  assert.equal(busyOwner, 'new-context', 'stale finally must not release state owned by the new context');
});

test('delayed approval mint rejection is silent after generation changes without an explicit abort race', async () => {
  const { createApprovalMintLifecycle, runApprovalMint } = await import('../src/approvalMintLifecycle.mjs');
  const lifecycle = createApprovalMintLifecycle();
  const mint = deferred();
  const errors = [];
  let generation = 4;
  let finished = 0;

  const pending = runApprovalMint(
    lifecycle,
    generation,
    () => generation,
    () => mint.promise,
    {
      onToken: async () => { throw new Error('token must not be sent'); },
      onError: (error) => { errors.push(error.message); },
      onFinish: () => { finished += 1; },
    },
  );
  generation = 5;
  mint.reject(new Error('old generation failed'));
  await pending;

  assert.deepEqual(errors, []);
  assert.equal(finished, 0);
});

test('native dialog disposal cancels only its exact active ID and rejects every late completion', async () => {
  const { createNativeDialogLifecycle } = await import('../src/nativeDialogLifecycle.mjs');
  const cancellations = [];
  const lifecycle = createNativeDialogLifecycle((requestId, options) => {
    cancellations.push({ requestId, keepalive: options.keepalive });
    return Promise.resolve();
  });
  const first = lifecycle.begin('dialog_A');

  assert.equal(lifecycle.dispose(), 'dialog_A');
  await Promise.resolve();
  assert.deepEqual(cancellations, [{ requestId: 'dialog_A', keepalive: true }]);
  assert.equal(lifecycle.markTerminal(first), false, 'detached completion cannot mutate React state or call selected handlers');
  assert.equal(lifecycle.dispose(), null, 'repeated cleanup cannot cancel again');
});

test('terminal and superseded native dialog handles cannot make cleanup cancel the wrong request', async () => {
  const { createNativeDialogLifecycle } = await import('../src/nativeDialogLifecycle.mjs');
  const cancellations = [];
  const lifecycle = createNativeDialogLifecycle((requestId) => {
    cancellations.push(requestId);
    return Promise.resolve();
  });
  const terminal = lifecycle.begin('dialog_terminal');
  assert.equal(lifecycle.markTerminal(terminal), true);
  assert.equal(lifecycle.dispose(), null);
  assert.deepEqual(cancellations, [], 'already terminal work is never cancelled by cleanup');

  const secondLifecycle = createNativeDialogLifecycle((requestId) => {
    cancellations.push(requestId);
    return Promise.resolve();
  });
  const stale = secondLifecycle.begin('dialog_stale');
  const current = secondLifecycle.begin('dialog_current');
  assert.equal(secondLifecycle.markTerminal(stale), false);
  assert.equal(secondLifecycle.dispose(), 'dialog_current');
  await Promise.resolve();
  assert.deepEqual(cancellations, ['dialog_current']);
  assert.equal(secondLifecycle.markTerminal(current), false);
});

test('native lifecycle re-arms after React StrictMode effect replay', async () => {
  const { createNativeDialogLifecycle } = await import('../src/nativeDialogLifecycle.mjs');
  const lifecycle = createNativeDialogLifecycle(() => Promise.resolve());

  lifecycle.mount();
  lifecycle.dispose();
  lifecycle.mount();
  const request = lifecycle.begin('strict_replay_request');

  assert.equal(lifecycle.isDisposed(), false);
  assert.equal(lifecycle.markTerminal(request), true);
});

test('focus return falls back to a connected stable owner when the initiating control detached', async () => {
  const { scheduleFocusReturn } = await import('../src/focusReturn.mjs');
  const queued = [];
  const schedule = (callback) => {
    queued.push(callback);
    return () => {};
  };
  let ownerFocus = 0;
  const detachedInitiator = { isConnected: false, matches: () => false, focus: () => assert.fail('detached initiator focused') };
  const stableOwner = { isConnected: true, matches: () => false, focus: () => { ownerFocus += 1; } };

  scheduleFocusReturn(detachedInitiator, schedule, () => stableOwner);
  queued.shift()();
  assert.equal(ownerFocus, 1);
});

test('frontend approval contract sends top-level generation and a guarded abort signal', async () => {
  const [api, app, chat, continuation] = await Promise.all([
    readSessionSource(import.meta.url),
    read('../src/App.tsx'),
    read('../src/useChatController.ts'),
    read('../src/useApprovalContinuation.ts'),
  ]);

  assert.match(api, /executeApproval\(pendingId: string, sessionId: string, callId: string, contextGeneration: number, signal\?: AbortSignal\)/);
  assert.match(api, /body: JSON\.stringify\(\{ pending_id: pendingId, session_id: sessionId, call_id: callId, context_generation: contextGeneration \}\)/);
  assert.match(api, /signal/);
  assert.match(app, /workspaceGeneration: workspaceContext\.generation/);
  assert.match(chat, /workspaceGeneration/);
  assert.match(chat, /session\.executeApproval\([\s\S]*request\.pending_id,\s*sessions\.sessionId,\s*request\.call_id,\s*generation,\s*signal/);
  assert.match(continuation, /args\.executeApproval\(request, generation, handle\.signal\)/);
  assert.doesNotMatch(chat, /approval_token/);
  assert.doesNotMatch(api, /mintApproval/);
});

test('recovery lookup is authenticated, redacted, and display-only', async () => {
  const [api, saveAs, en] = await Promise.all([
    readSessionSource(import.meta.url),
    read('../src/NativeSaveAsAction.tsx'),
    read('../src/i18n/en.ts'),
  ]);

  assert.match(api, /interface SaveAsRecoveryStatus/);
  assert.match(api, /fetchSaveAsRecoveryStatus\(recoveryId: string, signal\?: AbortSignal\)/);
  assert.match(api, /\/api\/native-dialogs\/save-as\/recovery\/\$\{encodeURIComponent\(recoveryId\)\}/);
  assert.match(api, /fetchSaveAsRecoveryStatus[\s\S]*apiFetch\(\`\/api\/native-dialogs\/save-as\/recovery\//, 'recovery lookup crosses the centralized authenticated transport');
  assert.doesNotMatch(api, /SaveAsRecoveryStatus[\s\S]{0,500}(?:destination|backup_path|path:)/i);
  assert.match(saveAs, /t\('saveas\.checkRecovery'\)/);
  assert.match(en, /'saveas\.checkRecovery': 'Check recovery status'/);
  assert.match(saveAs, /backup_available/);
  assert.doesNotMatch(saveAs, /restore|delete backup|destination path/i);
});
