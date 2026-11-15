import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('reviewed inputs render as a grouped Korean section above the action bar', async () => {
  const [card, ko] = await Promise.all([
    read('../src/ApprovalCard.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.match(card, /t\('approval\.inputsTitle'\)/, 'the section is labelled for beginners');
  assert.match(ko, /'approval\.inputsTitle': '입력값 확인'/, 'ko section label is exact');
  assert.match(card, /request\.display/, 'inputs come from the reviewed payload the backend adds later');
  const section = card.indexOf('approval-inputs');
  const summary = card.indexOf('approval-sticky-summary');
  const actions = card.indexOf('approval-actions');
  assert.ok(section >= 0 && summary > section && actions > section, 'inputs sit above the summary line and the buttons');
  assert.match(card, /{item\.value}/, 'values render as given, never reformatted');
  assert.doesNotMatch(card, /Number\(/, 'no numeric reshaping on the card');
});

test('the inputs section stays absent without payload and wraps at 390 px', async () => {
  const [card, css] = await Promise.all([
    read('../src/ApprovalCard.tsx'),
    read('../src/styles/chat-tools.css'),
  ]);
  assert.match(card, /inputGroups\.length > 0|inputs\.length > 0/, 'empty or missing inputs render exactly as today');
  assert.match(
    css,
    /\.approval-inputs[^{]*\{[^}]*overflow-wrap:\s*anywhere/s,
    'long values wrap instead of scrolling sideways',
  );
  assert.match(
    css,
    /\.approval-inputs[\s\S]*?min-width:\s*0/s,
    'the section shrinks inside the 390 px card',
  );
});
