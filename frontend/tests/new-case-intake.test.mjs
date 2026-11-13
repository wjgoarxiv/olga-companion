import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const STARTER = 'OLGA 초보자입니다. 새 케이스를 처음부터 만들고 싶습니다. 필요한 값을 하나씩 물어봐 주세요.';

test('new-case checklist renders from requirements data with no preset values', async () => {
  const card = await read('../src/NewCaseChecklist.tsx');
  assert.match(card, /\/api\/case-spec\/requirements/, 'the field list comes from the backend schema route');
  assert.match(card, /미입력/, 'each item shows whether it is still missing');
  assert.match(card, /입력됨/, 'each item shows whether it is already given');
  assert.doesNotMatch(card, /defaultValue\s*=\s*\{[^}]*[1-9]/, 'no numeric preset is shipped');
  assert.doesNotMatch(card, /value="[^"]+"/, 'no text value is prefilled');
  assert.doesNotMatch(card, /onPickStarter|chat\.send|approveSweep|executeApproval/, 'the card never sends or approves');
});

test('missing PVT table names the file the workspace needs', async () => {
  const card = await read('../src/NewCaseChecklist.tsx');
  assert.match(
    card,
    /PVT 표\(\.tab\)는 유체 물성 프로그램\(예: Multiflash, PVTsim\)에서 만든 파일입니다\. 앱은 유체 데이터를 만들지 않습니다\./,
    'the .tab explainer keeps tool names as examples only',
  );
  assert.match(card, /\.tab/, 'the recovery line names the missing table file');
});

test('chat and workspace entries only fill the starter, never send it', async () => {
  const [guide, workspace, slot] = await Promise.all([
    read('../src/SimulationGuide.tsx'),
    read('../src/WorkspaceView.tsx'),
    read('../src/shell/StepBarSlot.tsx'),
  ]);
  for (const source of [guide, workspace]) {
    assert.match(source, /새 케이스 만들기/, 'the intake entry is labelled for beginners');
  }
  assert.match(guide, /onDraft|onNewCase/, 'the chat entry fills the composer through the draft path');
  assert.doesNotMatch(guide, /새 케이스 만들기[\s\S]{0,300}onPickStarter/, 'the chat entry does not reach the send path');
  assert.match(slot, /새 케이스를 처음부터 만들고 싶습니다/, 'pressing the entry fills the exact Korean starter');
});
