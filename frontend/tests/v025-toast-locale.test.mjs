// 0.1.25 row 4: an away toast raised in Korean reads in English after the UI is switched,
// because the toast keeps the i18n key and is translated when it is drawn.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const src = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');

test('a toast raised in Korean shows English after the switch', () => {
  const html = r.renderToastAfterSwitch('ko', 'en', { kind: 'chat-done', titleKey: 'notify.chatDone' });
  assert.match(html, /Chat answer is ready/);
  assert.doesNotMatch(html, /답변이 왔습니다/);
  const back = r.renderToastAfterSwitch('en', 'ko', { kind: 'chat-done', titleKey: 'notify.chatDone' });
  assert.match(back, /답변이 왔습니다/);
});

test('a toast with plain text still shows that text, with its count', () => {
  const html = r.renderToastAfterSwitch('ko', 'en', { kind: 'chat-done', title: 'Plain words', count: 3 });
  assert.match(html, /Plain words ×3/);
});

test('the away hook hands over keys, not text resolved when the toast was raised', () => {
  const hook = src('useAwayNotify.ts');
  assert.doesNotMatch(hook, /textRef/);
  assert.doesNotMatch(hook, /t\('notify\./);
  for (const key of ['notify.runFinished', 'notify.runFailed', 'notify.approvalNeeded', 'notify.chatDone', 'notify.updateReady']) {
    assert.match(hook, new RegExp(`'${key.replace('.', '\\.')}'`), key);
  }
  assert.match(src('ui/Toast.tsx'), /toast\.titleKey \? t\(toast\.titleKey\) : toast\.title/);
});
