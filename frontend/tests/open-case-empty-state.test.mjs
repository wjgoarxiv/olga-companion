// With a case open the chat start screen is about that case: no template gallery.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('the template gallery shows only when no case is open', async () => {
  const empty = await read('../src/EmptyState.tsx');
  assert.match(empty, /\{!activeCaseName && <ExampleGallery/);
  assert.match(empty, /activeCaseName && \(\s*<p className="empty-open-case"/);
  assert.doesNotMatch(empty, /^\s*<ExampleGallery disabled=\{disabled\} \/>$/m);
});

test('the open-case line exists in English and Korean', async () => {
  for (const file of ['../src/i18n/en.ts', '../src/i18n/ko.ts']) {
    assert.match(await read(file), /'empty\.openCase':/, file);
  }
});

test('the open-case note keeps its own height in the stretched empty-state grid', async () => {
  const css = await readFile(new URL('../src/styles/chat-messages.css', import.meta.url), 'utf8');
  assert.match(css, /\.empty-open-case \{[^}]*align-self: start;/);
});
