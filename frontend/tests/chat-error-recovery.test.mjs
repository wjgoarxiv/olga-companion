import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { describeChatError } from '../src/chatErrorPresentation.ts';
import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';

test('a context-changed 409 is recovered by asking the AI again (a new turn, a new approval)', () => {
  const described = describeChatError(
    'Workspace context changed; refresh the preview and approve again. (HTTP 409 approval_context_changed)',
  );
  assert.equal(described.recovery, 'ask-again');
});

test('an uncertain-dispatch 409 sends the user to the run history and offers no retry', () => {
  const described = describeChatError(
    'The approved action outcome could not be confirmed. (HTTP 409 approval_dispatch_uncertain)',
  );
  assert.equal(described.recovery, 'open-history');
});

test('other errors keep the plain retry', () => {
  for (const raw of [
    'This approval was rejected by the user. (HTTP 409 approval_rejected)',
    'HTTP 409 Conflict',
    'Failed to fetch',
    'plain failure',
    'HTTP 429',
  ]) {
    assert.equal(describeChatError(raw).recovery, 'retry', raw);
  }
});

test('the recovery labels exist in both locales', () => {
  for (const [name, dict] of [['ko', ko], ['en', en]]) {
    assert.ok(dict['chat.retryAskAgain'], `${name} chat.retryAskAgain`);
    assert.ok(dict['chat.openRunHistory'], `${name} chat.openRunHistory`);
  }
  assert.equal(ko['chat.retryAskAgain'], '다시 요청');
  assert.equal(ko['chat.openRunHistory'], '실행 기록 열기');
  assert.equal(en['chat.retryAskAgain'], 'Ask again');
  assert.equal(en['chat.openRunHistory'], 'Open run history');
});

test('the pinned conflict keys keep their values', () => {
  assert.equal(ko['chat.retry'], '다시 시도');
  assert.equal(en['chat.retry'], 'Retry');
  for (const key of ['chat.errConflict', 'chat.errConflictContext', 'chat.errConflictUncertain', 'chat.errConflictRejected']) {
    assert.ok(ko[key] && en[key], key);
  }
});

test('the error row never re-dispatches an approval and routes open-history to the workspace', () => {
  const view = readFileSync(new URL('../src/ChatView.tsx', import.meta.url), 'utf8');
  const start = view.indexOf("case 'error':");
  const row = view.slice(start, view.indexOf('default:', start));
  assert.match(row, /described\.recovery/);
  assert.match(row, /props\.onOpenWorkspace/);
  assert.match(row, /chat\.openRunHistory/);
  assert.match(row, /chat\.retryAskAgain/);
  assert.doesNotMatch(row, /onApprove|onRecoverApproval|approvals/);
});
