import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('App renders one truthful runtime state and never exposes raw transport detail', async () => {
  const [app, status] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/StatusBar.tsx'),
  ]);

  assert.match(app, /import \{ useRuntimeConnection \} from '\.\/useRuntimeConnection'/);
  assert.match(app, /const runtime = useRuntimeConnection\(/);
  assert.match(status, /stateKey\(state\)/, 'the status-bar item is the single runtime-state source');
  assert.match(status, /operatorDetailText\(t, detail\)/, 'sidecar detail reads the shared presenter');
  assert.match(status, /onRetry\(\); setOpen\(false\)/, 'the retry action lives with the status popover');
  assert.match(status, /<Popover open=\{open\} onClose/, 'one popover carries every runtime-state readout');
  assert.doesNotMatch(app, /e instanceof Error \? e\.message|String\(e\)/, 'raw transport detail cannot reach global runtime UI');
});

test('runtime connection coordinates safe hydration, single initial chat, and visibility-aware timeouts', async () => {
  const hook = await read('../src/useRuntimeConnection.ts');

  assert.match(hook, /createRuntimeRecovery/);
  assert.match(hook, /subscribeTransportFailures/);
  assert.match(hook, /fetchHealth/);
  assert.match(hook, /fetchSessionToken/);
  assert.match(hook, /fetchProviders/);
  assert.match(hook, /fetchWorkspaceContext/);
  assert.match(hook, /if \(!sessionId\)[^]*?await startInitialSession\(\)/, 'recovery cannot duplicate an existing chat session');
  assert.match(hook, /visibilitychange/);
  assert.match(hook, /createProbeTimer/, 'heartbeat and reconnect chains arm through one single-arm timer');
  assert.match(hook, /return \(\) => \{[^]*?clearTimer\(\)[^]*?unsubscribe\(\)/, 'unmount clears the pending probe');
  assert.match(hook, /visibilityState !== 'visible'\) clearTimer\(\)/, 'hiding the tab clears the pending probe');
  assert.match(hook, /if \(activeRunRef\.current\) return activeRunRef\.current/, 'a manual retry reuses the in-flight run');
  assert.doesNotMatch(hook, /setInterval/, 'heartbeat and reconnect chains cannot overlap');
  assert.doesNotMatch(hook, /newSession|setActiveCase|runExecute|sweepExecute|streamChat/, 'automatic recovery remains GET-only');
});

test('protected views cannot issue requests before safe runtime hydration completes', async () => {
  const [app, centre] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/CentreViews.tsx'),
  ]);

  assert.match(app, /runtime\.state === 'online' && \(/, 'the centre mounts only after safe hydration');
  for (const view of ['WorkspaceView', 'ResultsView', 'RunView', 'SettingsView']) {
    assert.match(
      centre,
      new RegExp(`<${view}[^>]*key=\\{contextKey\\}`),
      `${view} must not mount with an empty or stale per-boot session token`,
    );
  }
});

test('safe runtime hydration unlocks chat without creating a session on page load', async () => {
  const [dock, hook] = await Promise.all([
    read('../src/shell/ChatDockView.tsx'),
    read('../src/useRuntimeConnection.ts'),
  ]);
  const onlineTransition = hook.indexOf("transition('online')");
  const chatBootstrap = hook.indexOf('if (initialSessionIntentRef.current.isPending())');

  assert.ok(onlineTransition >= 0 && chatBootstrap >= 0 && onlineTransition < chatBootstrap, 'verified runtime state must not remain Connecting while chat history loads');
  assert.match(dock, /healthReady=\{runtimeOnline\}/, 'online chat accepts the first prompt before a session id exists');
  assert.match(hook, /if \(!sessionId\) await startInitialSession\(\)/, 'post-hydration history bootstrap stays read-only');
});

test('all local browser requests are centralized without automatic mutation replay', async () => {
  const paths = [
    '../src/chatSessionApi.ts',
    '../src/workspaceApi.ts',
    '../src/nativeDialogApi.ts',
    '../src/resultApi.ts',
    '../src/runApi.ts',
    '../src/sweepApi.ts',
  ];
  const modules = await Promise.all(paths.map(read));
  const transport = await read('../src/sessionTransport.ts');

  for (const source of modules) {
    assert.doesNotMatch(source, /\bfetch\(/);
    assert.match(source, /apiFetch/);
  }
  assert.equal((transport.match(/\bfetch\(/g) ?? []).length, 1);
  assert.doesNotMatch(transport, /retry\s*\(|while\s*\(|setInterval/, 'transport observes failures but never replays a request');
  assert.match(transport, /Local runtime is offline/);
  assert.match(transport, /Local session expired/);
  assert.doesNotMatch(transport, /Failed to fetch|response\.statusText|response\.url/);
});

test('packaged Tauri requests resolve to the loopback sidecar without changing dev proxy behavior', async () => {
  const transport = await read('../src/sessionTransport.ts');

  assert.match(transport, /const PACKAGED_SIDECAR_ORIGIN = 'http:\/\/127\.0\.0\.1:8865'/);
  assert.match(transport, /location\.hostname === 'tauri\.localhost'/);
  assert.match(transport, /location\.protocol === 'tauri:'/);
  assert.match(transport, /new URL\(input, PACKAGED_SIDECAR_ORIGIN\)/);
  assert.match(transport, /fetch\(resolveLocalInput\(input\), init\)/);
});
