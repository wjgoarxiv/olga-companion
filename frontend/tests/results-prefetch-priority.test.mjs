import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('background Results prefetch yields to the initial Chat session bootstrap', async () => {
  const app = await read('../src/App.tsx');

  assert.match(
    app,
    /runtime\.state !== 'online' \|\| !workspaceRoot \|\| !chat\.sessionId/,
    'the background filesystem scan must wait until the initial Chat session is usable',
  );
  assert.match(
    app,
    /\[runtime\.state, workspaceRoot, chat\.sessionId\]/,
    'prefetch must resume as soon as the Chat session bootstrap completes',
  );
});
