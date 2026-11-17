import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  appendQueuedMessage,
  nextQueuedMessage,
  removeQueuedMessage,
  updateQueuedMessage,
} from '../src/activeWorkQueue.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('steer messages take the next safe boundary without losing queued work', () => {
  const queued = appendQueuedMessage([], {
    id: 'next-1',
    message: 'Compare the completed outputs.',
    policy: 'next',
    createdAt: 10,
  });
  const withSteer = appendQueuedMessage(queued, {
    id: 'steer-1',
    message: 'Use PT rather than TM.',
    policy: 'steer',
    createdAt: 20,
  });

  assert.equal(nextQueuedMessage(withSteer)?.id, 'steer-1');
  assert.deepEqual(removeQueuedMessage(withSteer, 'steer-1'), [queued[0]]);
  assert.equal(
    updateQueuedMessage(withSteer, 'next-1', 'Compare only the newest run.')[0]?.message,
    'Compare only the newest run.',
  );
});

test('busy composer keeps input active and exposes separate steer, queue, and response stop controls', async () => {
  const [view, queued, controller, stream, api, en] = await Promise.all([
    read('../src/ChatView.tsx'),
    read('../src/QueuedMessages.tsx'),
    read('../src/useChatController.ts'),
    read('../src/useChatStream.ts'),
    read('../src/chatSessionApi.ts'),
    read('../src/i18n/en.ts'),
  ]);

  assert.doesNotMatch(view, /disabled=\{props\.busy \|\| !props\.sessionId\}/);
  assert.match(view, /t\('chat\.steerNow'\)/);
  assert.match(view, /t\('chat\.queueNext'\)/);
  assert.match(en, /'chat\.steerNow': 'Steer now'/);
  assert.match(en, /'chat\.queueNext': 'Queue next'/);
  assert.match(view, /t\('chat\.stopAnswer'\)/);
  assert.match(queued, /t\('queue\.rejectSteer'\)/);
  assert.match(en, /'queue\.rejectSteer': 'Reject and apply steer'/);
  assert.match(stream, /stopChatResponse/);
  assert.match(
    stream,
    /await session\.stopChatResponse\(sessionId\)[\s\S]*controller\.abort\(\)/,
    'the old response is claimed server-side before its queued successor can start',
  );
  assert.doesNotMatch(controller, /runCancel|sweepCancel/);
  assert.match(api, /\/api\/chat\/response\/stop/);
});

test('chat queue is durable and the top-level Chats action does not expose a raw total', async () => {
  const [queue, menu] = await Promise.all([
    read('../src/useActiveWorkQueue.ts'),
    read('../src/SessionMenu.tsx'),
  ]);

  assert.match(queue, /writeLocalStorage/);
  assert.match(queue, /olga_chat_work_queue/);
  assert.doesNotMatch(menu, /className="session-count"/);
  assert.doesNotMatch(menu, /toLocaleString\(\)/);
});
