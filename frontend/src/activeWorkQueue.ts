export type QueuePolicy = 'steer' | 'next';

export interface QueuedMessage {
  readonly id: string;
  readonly message: string;
  readonly policy: QueuePolicy;
  readonly createdAt: number;
  /** The chat it was queued in; delivery to any other chat is refused. */
  readonly sessionId?: string;
}

export function appendQueuedMessage(
  queue: readonly QueuedMessage[],
  item: QueuedMessage,
): readonly QueuedMessage[] {
  if (!item.message.trim() || queue.some((candidate) => candidate.id === item.id)) {
    return queue;
  }
  return [...queue, { ...item, message: item.message.trim() }];
}

export function nextQueuedMessage(
  queue: readonly QueuedMessage[],
): QueuedMessage | undefined {
  return queue.find((item) => item.policy === 'steer') ?? queue[0];
}

export function removeQueuedMessage(
  queue: readonly QueuedMessage[],
  id: string,
): readonly QueuedMessage[] {
  return queue.filter((item) => item.id !== id);
}

export function updateQueuedMessage(
  queue: readonly QueuedMessage[],
  id: string,
  message: string,
): readonly QueuedMessage[] {
  const trimmed = message.trim();
  if (!trimmed) return queue;
  return queue.map((item) => item.id === id ? { ...item, message: trimmed } : item);
}
