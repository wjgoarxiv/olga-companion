import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('run failure suggestions are labelled as proposals and only prefill a question', async () => {
  const panel = await read('../src/RunFailurePanel.tsx');
  const app = await read('../src/App.tsx');

  assert.match(panel, /t\('run\.suggestionNote'\)/);
  assert.match(panel, /onDraftQuestion\?\.\(/);
  assert.doesNotMatch(panel, /runExecute|onSubmit|run_execute/);
  assert.match(app, /onDraftQuestion=\{\(prompt\) => \{ chat\.setInput\(prompt\); setDockOpen\(true\); \}\}/, 'suggestions prefill the dock composer without navigating away');
  assert.doesNotMatch(app, /onDraftQuestion=\{[^}]*chat\.(submit|send|approve)/);
});
