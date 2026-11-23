// 0.1.23 row 1: the open case can be closed from the case bar or the command palette; no file is touched.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('the case bar shows a close button only while a case is open, in both languages', async () => {
  const r = await reviewNotesRenderer();
  assert.match(r.renderWorkspaceBar('ko', 'a.genkey'), /<button[^>]*aria-label="사례 닫기"/);
  assert.match(r.renderWorkspaceBar('en', 'a.genkey'), /<button[^>]*aria-label="Close case"/);
  assert.doesNotMatch(r.renderWorkspaceBar('ko', null), /사례 닫기/);
});

test('closing calls the clear route with the workspace generation and never a file route', async () => {
  const api = await read('../src/workspaceApi.ts');
  const fn = api.match(/export async function clearActiveCase[\s\S]*?\n}\n/)?.[0] ?? '';
  assert.match(fn, /'\/api\/workspace\/active\/clear'/);
  assert.match(fn, /context_generation: contextGeneration/);
  const app = await read('../src/App.tsx');
  assert.match(app, /session\.clearActiveCase\(workspaceContext\.generation\)/);
  assert.match(app, /onCloseCase=\{\(\) => void pickCase\(null\)\}/);
});

test('the command palette has a close-case entry that only asks the case bar to close', async () => {
  const commands = await read('../src/shell/commands.ts');
  assert.match(commands, /\{ id: 'close-case', labelKey: 'shell\.cmdCloseCase' \}/);
  const run = await read('../src/shell/useWorkbenchCommands.ts');
  assert.match(run, /id === 'close-case'\) requestCaseClose\(\)/);
  const bar = await read('../src/WorkspaceBar.tsx');
  assert.match(bar, /CLOSE_CASE_EVENT/);
});
