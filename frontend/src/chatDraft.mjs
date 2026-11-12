export const DRAFT_LIMIT = 20000;

const CLEARS_DRAFT = new Set(['open', 'text', 'done', 'error', 'tool_call', 'approval_required']);

export function reduceDraft(draft, event) {
  if (event.type === 'draft') {
    const next = draft + String(event.data.text ?? '');
    return next.length > DRAFT_LIMIT ? next.slice(next.length - DRAFT_LIMIT) : next;
  }
  return CLEARS_DRAFT.has(event.type) ? '' : draft;
}

export function draftToShow(draft) {
  if (!draft.trim()) return null;
  return draft.length > DRAFT_LIMIT ? draft.slice(draft.length - DRAFT_LIMIT) : draft;
}
