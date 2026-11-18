import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readResultsSource } from './results-source.mjs';
import { readSessionSource } from './session-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('native dialog request IDs are generated client-side and satisfy the backend token contract', async () => {
  const helpers = await import('../src/nativeDialogRequest.mjs');
  const ids = Array.from({ length: 32 }, () => helpers.createNativeDialogRequestId());

  assert.equal(new Set(ids).size, ids.length);
  ids.forEach((id) => assert.match(id, /^[A-Za-z0-9_-]{1,64}$/));
});

test('native context payload contains only the exact request ID and nonnegative captured generation', async () => {
  const helpers = await import('../src/nativeDialogRequest.mjs');
  assert.equal(typeof helpers.createNativeContextRequestPayload, 'function');

  const payload = helpers.createNativeContextRequestPayload('dialog_exact', 7);
  assert.deepEqual(payload, { request_id: 'dialog_exact', context_generation: 7 });
  assert.deepEqual(Object.keys(payload), ['request_id', 'context_generation']);
  assert.throws(() => helpers.createNativeContextRequestPayload('dialog_exact', -1), /nonnegative integer/i);
  assert.throws(() => helpers.createNativeContextRequestPayload('dialog_exact', 1.5), /nonnegative integer/i);
});

test('same-generation context actions accept superseded as silent terminal and reject completion after generation change', async () => {
  const { createNativeDialogLifecycle } = await import('../src/nativeDialogLifecycle.mjs');
  const cancellations = [];
  const makeLifecycle = () => createNativeDialogLifecycle((requestId, options) => {
    cancellations.push({ requestId, keepalive: options.keepalive });
    return Promise.resolve();
  });
  const older = makeLifecycle();
  const newer = makeLifecycle();
  assert.equal(typeof older.cancelForContextChange, 'function');
  let generation = 11;
  const olderHandle = older.begin('workspace_request', generation);
  const newerHandle = newer.begin('case_request', generation);
  const selected = [];
  const errors = [];
  const cancellationsSeen = [];
  assert.equal(olderHandle.contextGeneration, 11);
  assert.equal(newerHandle.contextGeneration, 11);

  const settle = (lifecycle, handle, result) => {
    if (!lifecycle.markTerminal(handle, generation)) return;
    if (result.status === 'selected') selected.push(result.name);
    if (result.status === 'unavailable') errors.push(result.reason);
    if (result.status === 'cancelled') cancellationsSeen.push(handle.requestId);
  };

  settle(older, olderHandle, { status: 'superseded' });
  assert.deepEqual(selected, [], 'same-generation superseded response never selects context');
  assert.deepEqual(errors, [], 'same-generation superseded response is not an error');
  assert.deepEqual(cancellationsSeen, [], 'superseded is not presented as user cancellation');
  assert.equal(older.dispose(), null, 'current superseded response coherently clears the active lifecycle');

  generation = 12;
  assert.equal(newer.cancelForContextChange(generation), 'case_request');
  await Promise.resolve();
  settle(newer, newerHandle, { status: 'cancelled' });
  settle(newer, newerHandle, { status: 'selected', name: 'stale context' });
  if (newer.markTerminal(newerHandle, generation)) errors.push('stale request failed');

  assert.deepEqual(cancellations, [{ requestId: 'case_request', keepalive: true }], 'generation change cancels the exact still-current request');
  assert.deepEqual(selected, [], 'late selected completion cannot call the selected callback');
  assert.deepEqual(errors, [], 'late success, cancellation, or failure remains silent');
  assert.deepEqual(cancellationsSeen, [], 'stale cancelled completion is silent after generation change');
});

test('session exposes typed context and native dialog APIs with authenticated artifact-only payloads', async () => {
  const [api, transport] = await Promise.all([
    readSessionSource(import.meta.url),
    read('../src/sessionTransport.ts'),
  ]);

  for (const contract of [
    'WorkspaceContext',
    'NativeContextDialogResult',
    'NativeSaveAsResult',
    'NativeDialogCancelResult',
    'SaveAsRecoveryError',
  ]) assert.match(api, new RegExp(`(?:interface|type|class) ${contract}\\b`), contract);

  assert.match(api, /\| \{ readonly status: 'superseded' \}/, 'wire-level superseded status is an exact typed terminal variant');

  assert.match(api, /fetchWorkspaceContext\(\)[\s\S]*apiFetch\('\/api\/workspace\/context'/);
  assert.match(api, /chooseNativeWorkspace\(requestId: string, contextGeneration: number\)[\s\S]*'\/api\/native-dialogs\/workspace'[\s\S]*createNativeContextRequestPayload\(requestId, contextGeneration\)/);
  assert.match(api, /openNativeCase\(requestId: string, contextGeneration: number\)[\s\S]*'\/api\/native-dialogs\/open-case'[\s\S]*createNativeContextRequestPayload\(requestId, contextGeneration\)/);
  assert.match(api, /saveArtifactAs\(requestId:[\s\S]*artifact:[\s\S]*'\/api\/native-dialogs\/save-as'/);
  assert.match(api, /cancelNativeDialog\(requestId:[\s\S]*'\/api\/native-dialogs\/cancel'/);
  assert.match(api, /initial_path: initialPath/, 'Save As suggests the workspace start folder, never a destination');
  assert.match(api, /body: JSON\.stringify\(\{ request_id: requestId \}\)/);
  assert.match(transport, /headers\.set\('X-Session-Token', sessionToken\)/, 'the transport injects the latest token into every protected request');
  assert.equal((api.match(/\bfetch\s*\(/g) ?? []).length, 1, 'only the transport boundary owns a raw fetch call');
  assert.match(transport, /return await fetch\(resolveLocalInput\(input\), init\)/);
  assert.doesNotMatch(transport, /\bretry\b|setTimeout|replay/i, 'the transport cannot retry or replay a request');
  assert.doesNotMatch(api, /destination\s*:/i, 'browser APIs never accept a Save As destination');
  const saveAsStart = api.indexOf('export async function saveArtifactAs');
  const saveAsEnd = api.indexOf('export async function cancelNativeDialog', saveAsStart);
  assert.doesNotMatch(api.slice(saveAsStart, saveAsEnd), /contextGeneration|context_generation/, 'Save As contract remains generation-free');
});

test('structured recovery errors retain only the public code/message/id and redact arbitrary object details', async () => {
  const api = await readSessionSource(import.meta.url);

  assert.match(api, /class SaveAsRecoveryError extends Error/);
  assert.match(api, /code[^=]*= 'save_as_recovery_required'/);
  assert.match(api, /recoveryId/);
  assert.match(api, /detail\.code === 'save_as_recovery_required'/);
  assert.match(api, /detail\.recovery_id/);
  assert.doesNotMatch(api, /JSON\.stringify\(detail\)/, 'unknown structured errors must not be rendered as path-bearing JSON');
  assert.doesNotMatch(api, /backup_path|destination_path/i);
});

test('workspace controls use shared native actions with exact-ID cancellation and honest terminal status', async () => {
  const [actions, bar, settings, chromeCss, explorer] = await Promise.all([
    read('../src/NativeContextActions.tsx'),
    read('../src/WorkspaceBar.tsx'),
    read('../src/SettingsView.tsx'),
    read('../src/styles/chrome.css'),
    read('../src/shell/ExplorerPanel.tsx'),
  ]);

  assert.match(actions, /createNativeDialogRequestId\(\)/);
  assert.match(actions, /pendingRequestRef\.current = \{ requestId, kind, handle, contextGeneration: requestGeneration \}/);
  assert.match(actions, /const requestGeneration = contextGeneration/);
  assert.match(actions, /chooseNativeWorkspace\(requestId, requestGeneration\)/);
  assert.match(actions, /openNativeCase\(requestId, requestGeneration\)/);
  assert.match(actions, /cancelForContextChange\(contextGeneration\)/);
  assert.match(actions, /markTerminal\(handle, contextGenerationRef\.current\)/);
  assert.match(actions, /result\.status === 'superseded'[\s\S]*setNotice\(null\)/, 'current superseded terminal clears busy/focus state without a notice');
  assert.match(actions, /cancelNativeDialog\(pending\.requestId\)/);
  assert.match(actions, /\{t\('native\.pickWorkspace'\)\}<\/Button>/);
  assert.match(actions, /\{t\('native\.openCase'\)\}<\/Button>/);
  assert.match(actions, /titleKey: 'native\.dialogUnavailable'/);
  assert.match(actions, /titleKey: 'native\.selectionCancelled'/);
  assert.match(actions, /<OperationStatus/);
  assert.match(actions, /useLayoutEffect\([\s\S]*scheduleFocusReturn\(previousFocusRef\.current, undefined, stableContextFocusOwner\)/);
  assert.match(bar, /<NativeContextActions[^>]*contextGeneration=\{contextGeneration\}/s);
  assert.match(settings, /<NativeContextActions[^>]*contextGeneration=\{contextGeneration\}/s);
  assert.match(explorer, /<NativeContextActions[^>]*contextGeneration=\{contextGeneration\}/s, 'Explorer header reuses the shared native actions');
  assert.doesNotMatch(explorer, /<input[^>]*type="text"/, 'the tree filter is search, never a typed path');
  for (const source of [bar, settings]) {
    assert.doesNotMatch(source, /<input\b/);
    assert.doesNotMatch(source, /onChangeRoot|rootInput|Workspace path|Change workspace folder/);
  }
  assert.match(chromeCss, /\.case-list\s*\{[^}]*max-height:\s*min\(36vh, 320px\)[^}]*overflow-y:\s*auto/s, 'long workspaces keep native action status in view');
});

test('App applies one selected context atomically and invalidates stale context-bound work', async () => {
  const [app, bar, centre, chat] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/TitleBar.tsx'),
    read('../src/shell/CentreViews.tsx'),
    read('../src/useChatController.ts'),
  ]);

  assert.match(app, /useState<session\.WorkspaceContext>/);
  assert.match(app, /workspaceRefreshEpochRef = useRef\(createRequestEpoch\(\)\)/);
  assert.match(app, /const requestId = workspaceRefreshEpochRef\.current\.begin\(\)/);
  assert.match(app, /workspaceRefreshEpochRef\.current\.isCurrent\(requestId\)/);
  assert.match(app, /function applyWorkspaceContext\(next: session\.NativeSelectedContext\)/);
  assert.match(app, /workspaceRefreshEpochRef\.current\.invalidate\(\)/);
  assert.match(app, /chat\.invalidateContext\(\)/);
  assert.match(app, /setPreferredResultId\(null\)/);
  assert.match(app, /setWorkspaceContext\([\s\S]*root: next\.root[\s\S]*cases: next\.cases[\s\S]*active: next\.active[\s\S]*generation: next\.generation/);
  assert.match(bar, /<WorkspaceBar[^>]*contextGeneration=\{contextGeneration\}/s);
  assert.match(centre, /<SettingsView[^>]*contextGeneration=\{contextGeneration\}/s);
  for (const view of ['WorkspaceView', 'ResultsView', 'RunView']) {
    assert.match(centre, new RegExp(`<${view}[^>]*key=\\{contextKey\\}`, 's'), `${view} remounts on context switch`);
  }
  assert.doesNotMatch(app, /setWorkspaceRoot\(/, 'workspace identity is not committed through split state updates');
  assert.match(chat, /function invalidateContext\(\)/);
  assert.match(chat, /stream\.invalidate\(\)/);
  assert.match(chat, /approvals\.invalidate\(\)/);
  assert.match(chat, /kind === 'approval' && !item\.resolved[\s\S]*resolution: 'context-expired'/);
});

test('Results makes native Save As primary for each contained artifact and never supplies a destination', async () => {
  const [results, saveAs, en] = await Promise.all([
    readResultsSource(import.meta.url),
    read('../src/NativeSaveAsAction.tsx'),
    read('../src/i18n/en.ts'),
  ]);

  assert.match(saveAs, /saveArtifactAs\(requestId, artifact\)/);
  assert.match(saveAs, /cancelNativeDialog\(pending\.requestId\)/);
  assert.match(saveAs, /t\('saveas\.unavailable'\)/);
  assert.match(saveAs, /t\('saveas\.cancelledTitle'\)/);
  assert.match(saveAs, /t\('saveas\.completeTitle'\)/);
  assert.match(saveAs, /t\('saveas\.recoveryRequired'\)/);
  assert.match(en, /'saveas\.unavailable': 'Save As unavailable'/);
  assert.match(en, /'saveas\.cancelledTitle': 'Save As cancelled'/);
  assert.match(en, /'saveas\.completeTitle': 'Save As complete'/);
  assert.match(en, /'saveas\.recoveryRequired': 'Recovery required'/);
  assert.match(saveAs, /result\.basename/);
  assert.match(saveAs, /result\.size/);
  assert.doesNotMatch(saveAs, /destination|result\.path/i);
  assert.match(results, /<NativeSaveAsAction[^>]*artifact=\{publication\.plots\[0\]\}/s);
  assert.match(results, /<NativeSaveAsAction[^>]*artifact=\{publication\.documents\[0\]\}/s);
  assert.match(results, /<NativeSaveAsAction[^>]*artifact=\{csvExport\.download_path\}/s);
  assert.doesNotMatch(results, /href=\{session\.resultDownloadUrl/, 'native Save As is the primary export action');
});
