import { useState } from 'react';
import { reduceDraft } from './chatDraft';
import type { AgentEvent } from './types';

export function useChatDraft() {
  const [draft, setDraft] = useState('');
  return {
    draft,
    observe: (event: AgentEvent) => setDraft((current) => reduceDraft(current, event)),
    clear: () => setDraft(''),
  };
}
