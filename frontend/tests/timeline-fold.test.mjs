import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { foldClosedApprovals } from '../src/timelineFold.mjs';
import { APPROVAL_EXPIRED_SENTENCE } from '../src/approvalExpiry.mjs';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

/* 0.1.22 row 4: approval requests that can no longer be approved (expired, or closed when the case
 * or workspace changed) fold into one read-only row. Pending, approved and declined cards stay. */

const request = (id, name = 'case_publish', args = {}) => ({ name, call_id: `c-${id}`, pending_id: `p-${id}`, args });
const closed = (id, extra = {}) => ({ kind: 'approval', id, request: request(id, 'case_publish', { destination_rel: `cases/${id}.edit1.genkey` }), resolved: true, resolution: 'context-expired', ...extra });
const expired = (id) => ({ kind: 'approval', id, request: request(id, 'run_case'), resolved: true, detail: APPROVAL_EXPIRED_SENTENCE });
const pending = (id) => ({ kind: 'approval', id, request: request(id), resolved: false });
const rejected = (id) => ({ kind: 'approval', id, request: request(id), resolved: true, resolution: 'rejected' });
const user = (id) => ({ kind: 'user', id, text: 'hi' });

test('three closed requests in a row fold into one row with a count of three', () => {
  const folded = foldClosedApprovals([user('u'), closed('a'), expired('b'), closed('c')]);
  assert.equal(folded.length, 2);
  assert.equal(folded[1].kind, 'closed-approvals');
  assert.equal(folded[1].items.length, 3);
  assert.equal(folded[1].id, 'closed-a');
});

test('a pending card between closed ones splits the fold and stays itself', () => {
  const folded = foldClosedApprovals([closed('a'), closed('b'), pending('p'), closed('c')]);
  assert.deepEqual(folded.map((entry) => entry.kind), ['closed-approvals', 'approval', 'closed-approvals']);
  assert.equal(folded[1].id, 'p');
  assert.equal(folded[1].resolved, false);
});

test('declined and other items are left as they are', () => {
  const items = [rejected('r'), user('u'), { kind: 'approval', id: 'done', request: request('d'), resolved: true }];
  assert.deepEqual(foldClosedApprovals(items), items);
});

test('the folded row says how many closed requests it holds, in each language', async () => {
  const { renderClosedApprovals } = await reviewNotesRenderer();
  assert.match(renderClosedApprovals('ko', [closed('a'), expired('b'), closed('c')]), /닫힌 요청 3개/);
  assert.match(renderClosedApprovals('en', [closed('a'), expired('b'), closed('c')]), /3 closed requests/);
  assert.match(renderClosedApprovals('en', [closed('a')]), /1 closed request\b/);
});

test('the expanded list names tool, target and reason and has no approve control', async () => {
  const { renderClosedApprovals } = await reviewNotesRenderer();
  const html = renderClosedApprovals('en', [closed('a'), expired('b')], true);
  assert.match(html, /<details[^>]*open/);
  assert.match(html, /a\.edit1\.genkey/);
  assert.match(html, /Closed when the case or workspace changed/);
  assert.match(html, /Time ran out/);
  assert.doesNotMatch(html, /<button/);
  assert.doesNotMatch(html, /Approve/);
});

test('the chat renders the fold in place of the closed cards', async () => {
  const chat = await readFile(new URL('../src/ChatView.tsx', import.meta.url), 'utf8');
  assert.match(chat, /foldClosedApprovals\(props\.timeline\)/);
  assert.match(chat, /<ClosedApprovals\b/);
});
