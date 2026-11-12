import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('(a) each input row keeps name left and value right in the same row', async () => {
  const css = await read('../src/styles/chat-tools.css');
  assert.match(
    css,
    /\.approval-input-row\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto/s,
    'name and value share one row instead of running together',
  );
  assert.match(css, /\.approval-expiry\s*\{[^}]*margin/s, 'the expiry line keeps normal text spacing');
  assert.match(
    css,
    /\.approval-input-group\s+dl\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s,
    'the inputs dl is single-column so rows cannot pair up in inherited card columns',
  );
});

test('(b) save-as opens in the workspace folder and the report names the run', async () => {
  const [api, route, panel] = await Promise.all([
    read('../src/nativeDialogApi.ts'),
    read('../../src/olga_companion/sidecar_native_save_routes.py'),
    read('../src/FindingsPanel.tsx'),
  ]);
  assert.match(api, /initial_path/, 'the frontend passes the workspace folder to the dialog');
  assert.match(route, /initial_path/, 'the backend honors the requested start folder');
  assert.match(panel, /initialPath|wsRoot|workspaceRoot/, 'the findings report starts from the result workspace');
  assert.match(panel, /run_id/, 'the saved report names the run receipt id');
  assert.match(panel, /saveArtifactAs\(nativeRequestId, report\.artifact, workspaceRoot\)/, 'the dialog starts in the result workspace folder');
});

test('(d) remaining screens speak Korean', async () => {
  const [inspection, presenter, runView, overview, failure, rail, actions, update, ko] = await Promise.all([
    read('../src/InspectionEvidence.tsx'),
    read('../src/inspectionPresentation.ts'),
    read('../src/RunView.tsx'),
    read('../src/RunViewOverview.tsx'),
    read('../src/RunFailurePanel.tsx'),
    read('../src/ResultsInventoryRail.tsx'),
    read('../src/NativeContextActions.tsx'),
    read('../src/UpdatePanel.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.doesNotMatch(inspection + presenter, /GENKEY REVIEW/);
  assert.doesNotMatch(presenter, /Technical evidence/);
  assert.match(inspection, /t\('inspect\.genkeyReview'\)[\s\S]{0,1200}t\('inspect\.techBasis'\)/);
  assert.doesNotMatch(inspection + presenter, /Case validation passed/);
  assert.doesNotMatch(inspection + presenter, /Network topology/);
  assert.match(ko, /'inspect\.genkeyReview': 'GENKEY 검토'/);
  assert.doesNotMatch(runView, />Advanced sweep</);
  assert.match(runView, /t\('run\.advancedSweep'\)/);
  assert.doesNotMatch(overview, /Runtime strategy/);
  assert.doesNotMatch(overview, /Other installed runtimes/);
  assert.doesNotMatch(overview, /Selected runtime/);
  assert.match(overview + failure, /t\('run\.selectedEnv'\)/);
  assert.doesNotMatch(failure, /Process state/);
  assert.doesNotMatch(failure, /Output inventory/);
  assert.doesNotMatch(failure, /Open TPL in Results/);
  assert.match(failure, /t\('run\.outputsTitle'\)/);
  assert.match(failure, /t\('run\.openTpl'\)/);
  assert.match(failure, /t\('run\.processState'\)/);
  assert.doesNotMatch(rail, /RESULT INVENTORY/);
  assert.doesNotMatch(rail, />Refresh results</);
  assert.match(rail, /t\('results\.kicker'\)/);
  assert.doesNotMatch(actions, /Choose workspace/);
  assert.match(actions, /t\('native\.pickWorkspace'\)/);
  const [lifecycle, chat] = await Promise.all([
    read('../src/LifecycleEvidence.tsx'),
    read('../src/ChatView.tsx'),
  ]);
  assert.doesNotMatch(lifecycle, /Case change compiled for review/);
  assert.doesNotMatch(lifecycle, /Source remains unchanged until/);
  assert.doesNotMatch(lifecycle, /Case published/);
  assert.doesNotMatch(lifecycle, /compiled bytes were installed/);
  assert.doesNotMatch(lifecycle, /Audit receipt/);
  assert.match(lifecycle, /바꿀 내용을 검토용으로 묶었어요/);
  assert.match(lifecycle, /사례를 발행했어요/);
  assert.match(lifecycle, /t\('lifecycle\.audit'\)/);
  assert.doesNotMatch(chat, /Stop response/);
  assert.match(chat, /t\('chat\.stopAnswer'\)/);
  assert.doesNotMatch(update, /Check for updates/);
  assert.doesNotMatch(update, /Install and restart/);
  assert.match(update, /t\('update\.check'\)/);
  assert.match(update, /t\('update\.installRestart'\)/);
});
