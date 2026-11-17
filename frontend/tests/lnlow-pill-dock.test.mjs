import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

// lnlow #4 RED-first: the sticky Recent-chat pill must never cover message
// text, so it is docked outside the scrollable text column (in normal flow
// after the timeline scroller), not stuck over the scrolled replies.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const view = fs.readFileSync(path.join(root, 'src', 'ChatView.tsx'), 'utf8');

// Find the matching close of the timeline scroller div that opens with
// data-testid="chat-timeline", via a small tag-depth scan.
function timelineRange(source) {
  const marker = 'data-testid="chat-timeline"';
  const markerAt = source.indexOf(marker);
  assert.ok(markerAt !== -1, 'timeline scroller must exist');
  const openAt = source.lastIndexOf('<div', markerAt);
  let depth = 0;
  const tag = /<(\/?)div[\s>]/g;
  tag.lastIndex = openAt;
  let match;
  while ((match = tag.exec(source)) !== null) {
    depth += match[1] === '/' ? -1 : 1;
    if (depth === 0) return { openAt, closeAt: tag.lastIndex };
  }
  throw new Error('unbalanced timeline div');
}

test('lnlow #4: recent pill is docked outside the scrollable text column', () => {
  const { openAt, closeAt } = timelineRange(view);
  const pillAt = view.indexOf('onScrollToBottom}');
  assert.ok(pillAt !== -1, 'pill must still call onScrollToBottom');
  assert.ok(pillAt < openAt || pillAt > closeAt, 'pill must not render inside the timeline scroller');
});

test('lnlow #4: docked pill keeps its action contract and opaque styling', () => {
  assert.match(view, /aria-label=\{t\('chat\.recentChatAria'\)\}/);
  assert.match(view, /onClick=\{props\.onScrollToBottom\}/);
  const pillAt = view.indexOf('onClick={props.onScrollToBottom}');
  const open = view.lastIndexOf('<Button', pillAt);
  assert.ok(open !== -1, 'pill must be a Button');
  assert.ok(!/variant="quiet"/.test(view.slice(open, pillAt)), 'pill must stay opaque');
});
