import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function promptBlock(source, className) {
  const start = source.indexOf(`className="${className}"`);
  assert.ok(start > 0, `${className} prompt exists`);
  const end = source.indexOf('</WorkbenchPrompt>', start);
  const selfClose = source.indexOf('/>', start);
  return source.slice(start, end > 0 && end < start + 6000 ? end : selfClose);
}

const entryButton = /<Button[^>]*variant="secondary"[^>]*onClick=\{[^}]*requestPipeTableWizard\(\)[^}]*\}[^>]*data-tour="pipe-case"[^>]*>\{t\('pipeWizard\.title'\)\}<\/Button>/;

test('the empty workspace screen has a secondary pipe-table button that only opens the wizard', async () => {
  const source = await read('../src/WorkspaceView.tsx');
  assert.match(source, /import \{ requestPipeTableWizard \} from '\.\/shell\/PipeTableWizard'/);
  const empty = promptBlock(source, 'ws-empty-state');
  assert.match(empty, entryButton);
  assert.equal((empty.match(/requestPipeTableWizard\(\)/g) ?? []).length, 1);
  assert.equal((empty.match(/variant="primary"/g) ?? []).length, 1, 'the existing primary stays the only primary outside the gallery');
});

test('the pick-a-case screen offers the same secondary button', async () => {
  const source = await read('../src/WorkspaceView.tsx');
  const pick = promptBlock(source, 'ws-selection-state');
  assert.match(pick, entryButton);
  assert.doesNotMatch(pick, /variant="primary"/, 'no second primary action on the pick screen');
});

test('the button only opens the wizard: no write, no send, no approval', async () => {
  const source = await read('../src/WorkspaceView.tsx');
  const handlers = source.match(/requestPipeTableWizard\(\)/g) ?? [];
  assert.equal(handlers.length, 2, 'one call per screen');
  assert.doesNotMatch(source, /setInput\(|sendMessage|approve\(/);
});

test('the label is the wizard title in both languages', () => {
  assert.equal(ko['pipeWizard.title'], '배관표로 사례 만들기');
  assert.notEqual(en['pipeWizard.title'], ko['pipeWizard.title']);
});
