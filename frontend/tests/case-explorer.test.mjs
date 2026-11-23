import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('explorer groups inventory into cases, PVT tables and outputs with one filter', async () => {
  const [panel, css] = await Promise.all([
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/styles/workbench.css'),
  ]);
  assert.match(panel, /role="tree"/, 'tree keeps its ARIA role');
  assert.match(panel, /\.genkey/, 'genkey cases form a group');
  assert.match(panel, /PVT|pvt/i, 'PVT tables form a group');
  assert.match(panel, /type="search"/, 'one filter searches the tree');
  assert.match(panel, /role="group"|aria-label=.*group/i, 'groups are labelled');
  assert.match(css, /\.wb-explorer-group/, 'groups have a style contract');
});

test('explorer shows full file names with an ellipsis only on real overflow, plus sizes', async () => {
  const [panel, css] = await Promise.all([
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/styles/workbench.css'),
  ]);
  assert.match(panel, /title=\{item\.name\}/, 'full name stays on the tooltip');
  assert.doesNotMatch(panel, /displayStem/, 'long stems are never mid-truncated in the tree');
  assert.match(panel, /aria-label=\{`\$\{item\.name\}/, 'full name stays on the accessible name');
  assert.match(css, /\.wb-explorer-name-head\s*\{[^}]*text-overflow:\s*ellipsis/s, 'overflow truncates the head with an ellipsis only when it really overflows');
  assert.match(css, /\.wb-explorer-tree\s*\{[^}]*overflow-x:\s*(hidden|clip)/s, 'the tree never scrolls sideways');
  assert.match(panel, /KB/, 'sizes render beside names');
  assert.match(panel, /<Icon name=\{iconFor/, 'file types carry vector icons');
});

test('explorer header reuses the shared native context actions with no typed paths', async () => {
  const panel = await read('../src/shell/ExplorerPanel.tsx');
  assert.match(panel, /NativeContextActions/, 'header reuses the shared native lifecycle');
  assert.doesNotMatch(panel, /<input[^>]*type="text"/, 'no typed path input in the tree');
});

test('explorer routes .tab to a read-only preview and .genkey to activation', async () => {
  const [panel, workspace] = await Promise.all([
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/WorkspaceView.tsx'),
  ]);
  assert.match(panel, /requestTabPreview/, 'tab clicks dispatch a preview request');
  assert.match(panel, /window\.dispatchEvent\(requestTabPreview\(item\.rel\)\)/, 'preview carries the file path');
  assert.doesNotMatch(panel, /onPick\(item\.rel\)[^}]*\.tab/, 'tabs never go through case activation');
  assert.match(workspace, /OPEN_TAB_PREVIEW_EVENT/, 'the case surface listens for preview requests');
  assert.match(workspace, /parseTabPreviewEvent\(event\)/, 'preview requests are typed');
  assert.match(workspace, /void openTab\(target\)/, 'preview opens read-only');
});
