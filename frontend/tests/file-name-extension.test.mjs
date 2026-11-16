import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('explorer and results rows pin the filename extension and keep the full name', async () => {
  const [centre, explorer, results] = await Promise.all([
    read('../src/WorkspaceView.tsx'),
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/ResultsInventoryRail.tsx'),
  ]);

  assert.doesNotMatch(centre, /ws-file-name/, 'the centre no longer duplicates the inventory rows');
  assert.match(explorer, /className="wb-explorer-name"/);
  assert.match(explorer, /className="wb-explorer-ext"/);
  assert.match(explorer, /title=\{item\.name\}/);
  assert.match(explorer, /aria-label=\{`\$\{item\.name\}/);
  assert.match(results, /className="ws-file-name case-name"/);
  assert.match(results, /className="case-name-stem"/);
  assert.match(results, /className="case-name-extension"/);
  assert.match(results, /title=\{`\$\{f\.name\}/);
  assert.match(results, /aria-label=\{`\$\{f\.name\}/);
});
