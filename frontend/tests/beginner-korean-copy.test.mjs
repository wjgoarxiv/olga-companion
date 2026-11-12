import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('run cockpit headings speak Korean', async () => {
  const [overview, ko] = await Promise.all([
    read('../src/RunViewOverview.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  for (const key of ['run.titleReady', 'run.titleLoading', 'run.titleNoCase', 'run.emptyTitle']) {
    assert.match(overview, new RegExp(`t\\('${key.replace('.', '\\.')}'\\)`), `heading uses ${key}`);
  }
  assert.match(ko, /'run\.titleReady': '실행 조작'/);
  assert.match(ko, /'run\.emptyTitle': '먼저 사례를 고르세요'/);
  assert.doesNotMatch(overview, /Execution controls/);
  assert.doesNotMatch(overview, /Loading active case/);
  assert.doesNotMatch(overview, /No active case/);
});

test('approval card keeps exact button labels with a Korean helper line', async () => {
  const [card, ko, en] = await Promise.all([
    read('../src/ApprovalCard.tsx'),
    read('../src/i18n/ko.ts'),
    read('../src/i18n/en.ts'),
  ]);
  assert.match(card, /t\('approval\.approvePublish'\)/);
  assert.match(card, /t\('approval\.approveRun'\)/);
  assert.match(ko, /'approval\.approvePublish': '승인하고 게시'/);
  assert.match(ko, /'approval\.approveRun': '승인하고 실행'/);
  assert.match(en, /'approval\.approvePublish': 'Approve and publish'/);
  assert.match(en, /'approval\.approveRun': 'Approve and run'/);
  assert.match(card, /t\('approval\.title'\)/);
  assert.match(card, /t\('approval\.publishRefused'\)/);
  assert.match(card, /t\('approval\.resolvedTitle'\)/);
  assert.match(card, /t\('approval\.hintHuman'\)/);
  assert.match(ko, /'approval\.hintHuman': '어시스턴트가 대신 승인할 수 없습니다\.'/);
  assert.doesNotMatch(card, /Approval required —/);
  assert.doesNotMatch(card, /Publish refused/);
  assert.doesNotMatch(card, /Approval request resolved/);
});

test('case evidence, results prompts and workspace empty states speak Korean', async () => {
  const [evidence, prompts, workspace, explorer, ko] = await Promise.all([
    read('../src/CaseSpecEvidence.tsx'),
    read('../src/ResultsPrompts.tsx'),
    read('../src/WorkspaceView.tsx'),
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.match(evidence, /사례 명세가 맞습니다/);
  assert.match(prompts, /t\('results\.pickTitle'\)/);
  assert.match(prompts, /t\('results\.emptyTitle'\)/);
  assert.match(prompts, /t\('results\.loadingTitle'\)/);
  assert.match(explorer, /t\(GROUP_KEYS\[group\]\)/, 'file roles stay labelled in the one tree');
  assert.match(ko, /'explorer\.groupPvt': 'PVT 표'/);
  assert.match(workspace, /t\('workspace\.emptyList'\)/);
  assert.match(workspace, /설정 열기/);
  assert.doesNotMatch(evidence, /Case specification valid/);
  assert.doesNotMatch(prompts, /No OLGA results found/);
});

test('settings and sweep status labels speak Korean', async () => {
  const [settings, sweep, ko] = await Promise.all([
    read('../src/SettingsView.tsx'),
    read('../src/RunSweepStatus.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.match(settings, /t\('settings\.providerTitle'\)/);
  assert.match(settings, /t\('settings\.significantFigures'\)/);
  assert.match(ko, /'settings\.providerTitle': 'AI 공급자'/);
  assert.match(ko, /'settings\.significantFigures': '유효 숫자'/);
  assert.match(sweep, /t\('run\.sweepStatusAria'\)/);
  assert.match(sweep, /t\('run\.sweepResultsAria'\)/);
  assert.doesNotMatch(settings, /<span>Significant figures<\/span>/);
});
