import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('application shell owns safe artifact navigation and propagates workspace generation', async () => {
  const [app, dock, chat, tool, evidence] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/ChatDockView.tsx'),
    read('../src/ChatView.tsx'),
    read('../src/ToolUnit.tsx'),
    read('../src/EvidenceBlock.tsx'),
  ]);

  assert.match(app, /OPEN_ARTIFACT_IN_RESULTS_EVENT/);
  assert.match(app, /parseOpenArtifactEventDetail\(event\.detail\)/);
  assert.match(app, /openResult\(detail\.result_id\)/);
  assert.match(dock, /<ChatView[\s\S]*workspaceGeneration=\{workspaceGeneration\}/);
  assert.match(chat, /<ToolUnit[\s\S]*currentWorkspaceGeneration=\{props\.workspaceGeneration\}/);
  assert.match(tool, /<EvidenceBlock[\s\S]*currentWorkspaceGeneration=\{currentWorkspaceGeneration\}/);
  assert.match(evidence, /<ArtifactCard[\s\S]*currentWorkspaceGeneration=\{currentWorkspaceGeneration\}/);
});
