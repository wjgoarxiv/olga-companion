import assert from 'node:assert/strict';
import test from 'node:test';

import { SESSION_PAGE_SIZE, sessionWindow } from '../src/sessionWindow.ts';

test('session window renders a bounded first page for a large history', () => {
  const sessions = Array.from({ length: 3_224 }, (_, index) => ({ session_id: String(index) }));

  const result = sessionWindow(sessions, SESSION_PAGE_SIZE);

  assert.equal(result.visible.length, 50);
  assert.equal(result.remaining, 3_174);
  assert.equal(result.visible[49]?.session_id, '49');
});

test('session window reveals another page without duplicating rows', () => {
  const sessions = Array.from({ length: 120 }, (_, index) => ({ session_id: String(index) }));

  const result = sessionWindow(sessions, SESSION_PAGE_SIZE * 2);

  assert.equal(result.visible.length, 100);
  assert.equal(result.remaining, 20);
  assert.equal(new Set(result.visible.map((session) => session.session_id)).size, 100);
});

test('session window clamps the final page to the available history', () => {
  const sessions = Array.from({ length: 12 }, (_, index) => ({ session_id: String(index) }));

  const result = sessionWindow(sessions, SESSION_PAGE_SIZE * 2);

  assert.deepEqual(result.visible, sessions);
  assert.equal(result.remaining, 0);
});
