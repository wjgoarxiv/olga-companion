import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { translate } from '../src/i18n/index.ts';

const workspaceSource = await readFile(
  new URL('../src/WorkspaceView.tsx', import.meta.url),
  'utf8',
);
const promptCss = await readFile(
  new URL('../src/styles/workbench-prompts.css', import.meta.url),
  'utf8',
);
const workspaceCss = await readFile(
  new URL('../src/styles/workspace.css', import.meta.url),
  'utf8',
);

test('empty Workspace guidance remains correct when the inventory rail stacks on mobile', () => {
  assert.match(
    workspaceSource,
    /contextLabel=\{t\('workspace\.pickContextLabel'\)[\s\S]*?contextDetail=\{caseCount > 0 \? t\('workspace\.pickContextDetailCase'\)/,
    'the context card gives an orientation-independent next step',
  );
  assert.equal(translate('ko', 'workspace.pickContextLabel'), '고를 수 있는 목록', 'ko pick-list label is pinned to the rendered dictionary value');
  assert.equal(translate('ko', 'workspace.pickContextDetailCase'), '.genkey 파일을 골라 시작하세요', 'ko pick detail (with cases) is pinned to the rendered dictionary value');
  assert.equal(translate('ko', 'workspace.pickContextDetailNone'), '.genkey 파일을 넣어 시작하세요', 'ko pick detail (no cases) is pinned to the rendered dictionary value');
  assert.match(
    workspaceSource,
    /title=\{caseCount > 0 \? t\('workspace\.pickTitleCase'\)/,
    'the selection prompt resolves through the ko dictionary',
  );
  assert.equal(translate('ko', 'workspace.pickTitleCase'), '검사할 사례 고르기', 'ko pick title (with cases) is pinned to the rendered dictionary value');
  assert.equal(translate('ko', 'workspace.pickTitleNone'), 'OLGA 사례가 없습니다', 'ko pick title (no cases) is pinned to the rendered dictionary value');
  assert.doesNotMatch(
    workspaceSource,
    /Use the case rail on the left/,
    'responsive guidance must not describe a desktop-only position',
  );
  assert.match(
    promptCss,
    /@media \(max-width: 760px\)[\s\S]*?\.ws-selection-state,[\s\S]*?\.rv-selection-state\s*\{\s*margin:\s*0;/,
    'the stacked mobile prompt stays adjacent to the inventory instead of centering in leftover space',
  );
  assert.match(
    workspaceSource,
    /ws-view\$\{cases\.length === 0 \? ' empty' : !selected \? ' awaiting-selection' : ''\}/,
    'the workspace identifies the inventory-only state for responsive layout',
  );
  assert.match(
    workspaceCss,
    /@media \(max-width: 760px\)[\s\S]*?\.ws-view\.awaiting-selection\s*\{\s*display:\s*block/,
    'the single-column canvas holds its prompt while awaiting a selection',
  );
});
