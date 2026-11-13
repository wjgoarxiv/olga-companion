import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { translate } from '../src/i18n/index.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('Given mixed workspace inventory, when files render, then only OLGA cases are activation controls', async () => {
  const [panel, view] = await Promise.all([
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/WorkspaceView.tsx'),
  ]);

  // The Explorer owns the one inventory list: .tab takes the preview branch
  // before any activation path, and .genkey rows activate through onPick.
  assert.match(panel, /item\.suffix === '\.tab'/, 'support files take the preview branch');
  assert.match(panel, /window\.dispatchEvent\(requestTabPreview\(item\.rel\)\)/, 'a support file previews without touching case activation');
  assert.match(panel, /<button[^>]*className="wb-explorer-item"/, 'every inventory row is a control');
  assert.match(panel, /\{t\(GROUP_KEYS\[group\]\)\}/, 'support files expose their role through the group label');
  assert.match(panel, /showSuffix = group !== 'cases' && group !== 'pvt'/, 'homogeneous groups drop the repeated suffix');
  assert.match(panel, /\{showSuffix && item\.suffix && <span className="wb-explorer-ext">\{item\.suffix\}<\/span>\}/, 'mixed groups still pin the suffix so it is never clipped');
  assert.match(panel, /aria-label=\{`\$\{item\.name\}/, 'rows keep the full-name accessible name');

  // A PVT table preview is read-only: openTab never routes into the
  // case-activation path.
  assert.match(
    view,
    /async function openTab[\s\S]*?session\.inspectTab/,
    'previewing a support file reads it read-only instead of activating a case',
  );
});

test('Given mixed workspace inventory, when guidance renders, then cases and support files are counted separately', async () => {
  const view = await read('../src/WorkspaceView.tsx');

  assert.match(view, /const caseCount = cases\.filter\(\(candidate\) => candidate\.suffix === '\.genkey'\)\.length/);
  assert.match(view, /const supportFileCount = cases\.length - caseCount/);
  assert.match(view, /contextValue=\{t\('workspace\.pickContextValue', \{ case: caseCount\.toLocaleString\(\), support: supportFileCount\.toLocaleString\(\) \}\)/, 'pick count resolves through the ko dictionary');
  assert.equal(
    translate('ko', 'workspace.pickContextValue', { case: (3).toLocaleString(), support: (1).toLocaleString() }),
    `${(3).toLocaleString()}건 사례 · ${(1).toLocaleString()}건 지원 파일`,
    'ko pick count copy is pinned to the rendered dictionary value',
  );
});
