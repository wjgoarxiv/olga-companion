import { useEffect, useRef, useState } from 'react';
import {
  appendQueuedMessage,
  nextQueuedMessage,
  removeQueuedMessage,
  updateQueuedMessage,
  type QueuedMessage,
  type QueuePolicy,
} from './activeWorkQueue';
import { readLocalStorage, writeLocalStorage } from './safeLocalStorage';

export const ACTIVE_WORK_QUEUE_KEY = 'olga_chat_work_queue';

function readStoredQueue(): readonly QueuedMessage[] {
  try {
    const value: unknown = JSON.parse(readLocalStorage(ACTIVE_WORK_QUEUE_KEY) ?? '[]');
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is QueuedMessage => (
      typeof item === 'object'
      && item !== null
      && 'id' in item
      && typeof item.id === 'string'
      && 'message' in item
      && typeof item.message === 'string'
      && 'policy' in item
      && (item.policy === 'steer' || item.policy === 'next')
      && 'createdAt' in item
      && typeof item.createdAt === 'number'
      && (!('sessionId' in item) || typeof item.sessionId === 'string')
    ));
  } catch {
    return [];
  }
}

export function useActiveWorkQueue() {
  const [queued, setQueued] = useState<readonly QueuedMessage[]>(readStoredQueue);
  const queuedRef = useRef(queued);
  queuedRef.current = queued;

  useEffect(() => {
    writeLocalStorage(ACTIVE_WORK_QUEUE_KEY, JSON.stringify(queued));
  }, [queued]);

  function enqueue(message: string, policy: QueuePolicy, sessionId = ''): void {
    const item: QueuedMessage = {
      id: crypto.randomUUID(),
      message,
      policy,
      createdAt: Date.now(),
      ...(sessionId ? { sessionId } : {}),
    };
    setQueued((current) => appendQueuedMessage(current, item));
  }

  function takeNext(): QueuedMessage | undefined {
    const item = nextQueuedMessage(queuedRef.current);
    if (!item) return undefined;
    const next = removeQueuedMessage(queuedRef.current, item.id);
    queuedRef.current = next;
    setQueued(next);
    return item;
  }

  function remove(id: string): void {
    setQueued((current) => removeQueuedMessage(current, id));
  }

  function update(id: string, message: string): void {
    setQueued((current) => updateQueuedMessage(current, id, message));
  }

  return { enqueue, queued, remove, takeNext, update };
}
